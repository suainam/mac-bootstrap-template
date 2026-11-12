import { getHuashuClient } from "./huashu_driver.mjs";

const sleep = ms => new Promise(r => setTimeout(r, ms));
const clean = t => t.replace(/（提示：.*?）/gs, "").trim();

/**
 * 页面结构选择器（2026-11 实测 next.dslbuy.com 测试工作台）。
 * 页面改版时只改这里，或通过各函数的 `selectors` 选项局部覆盖；不要把选择器散落进 expr。
 */
export const SELECTORS = {
  card: ".case-card",               // 用例卡片；状态由 class 表达：pending / passed / failed
  cardActive: ".case-card.active",
  passBtn: ".result-btn.passed-btn",
  loadingMask: ".el-loading-mask",
  storyStatus: ".twf-status-tag",   // 头部 Story 状态标签（如「验证中」）
  stageBar: ".bottom-smoke-actions",// 底部阶段流转按钮栏
  msgBox: ".el-message-box__wrapper, .el-dialog__wrapper",
  msgBoxConfirm: ".el-message-box__btns .el-button--primary, .el-dialog__footer .el-button--primary",
};

/** 阶段流转按钮文案（仅用于在 stageBar 内识别按钮并断言弹窗语义，不作为点击依据） */
export const STAGE_ACTIONS = ["冒烟通过", "完成测试"];

const DEFAULT_BASE = "https://next.dslbuy.com/?qaCtx=workbench";
const workbenchBase = () => process.env.TEST_WORKBENCH_BASE || DEFAULT_BASE;

/** 页面内公共 helper：可见性以计算样式 + 尺寸判定，不依赖 inline style 字符串 */
const PAGE_HELPERS = `
  const vis = e => { const cs = getComputedStyle(e), r = e.getBoundingClientRect();
    return cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0; };
  const blockingMask = () => Array.from(document.querySelectorAll(S.loadingMask))
    .find(m => !/fade-leave/.test(m.className) && vis(m));
  const stageBtns = () => Array.from(document.querySelectorAll(S.stageBar + ' button'))
    .filter(b => ACTIONS.some(a => (b.innerText || '').includes(a)));
  const isDisabled = b => b.disabled || b.classList.contains('is-disabled');
`;

const wrap = (body, selectors, actions) => `
  (() => {
    const S = ${JSON.stringify(selectors)};
    const ACTIONS = ${JSON.stringify(actions)};
    ${PAGE_HELPERS}
    ${body}
  })()
`;

async function evalJson(client, tabId, body, { selectors = {}, actions = STAGE_ACTIONS } = {}) {
  const expr = wrap(body, { ...SELECTORS, ...selectors }, actions);
  const res = await client.call("eval", { tabId, expr });
  return JSON.parse(clean(res.text));
}

/**
 * 读取用例统计、Story 状态与阶段按钮状态
 */
export async function getStatus(client, tabId, opts = {}) {
  return evalJson(client, tabId, `
    const cards = Array.from(document.querySelectorAll(S.card));
    const count = c => cards.filter(x => x.classList.contains(c)).length;
    const st = document.querySelector(S.storyStatus);
    const btn = stageBtns()[0];
    return {
      total: cards.length,
      passed: count('passed'), pending: count('pending'), failed: count('failed'),
      storyStatus: st ? st.innerText.trim() : null,
      stageBtn: btn ? { text: btn.innerText.trim(), disabled: isDisabled(btn) } : null,
      blockingMask: !!blockingMask()
    };
  `, opts);
}

/**
 * 紧凑循环通过全部待执行用例。
 * - 遮罩仅在「非 leave 过渡态且实际可见」时才等待（残留 fade-leave 遮罩不再导致空转）
 * - 停滞熔断：连续 stallLimit 步 passed 数不增长即失败并返回现场，不再空跑到 maxSteps
 */
export async function passAllPending(client, tabId, {
  maxSteps = 200, intervalMs = 380, stallLimit = 10, onProgress = null, selectors = {},
} = {}) {
  const body = `
    const cards = Array.from(document.querySelectorAll(S.card));
    const pendingCards = cards.filter(c => c.classList.contains('pending'));
    const passed = cards.filter(c => c.classList.contains('passed')).length;
    const total = cards.length;
    if (total === 0) return { done: false, action: 'no_cards', total, passed, pending: 0 };
    if (pendingCards.length === 0) return { done: true, total, passed, pending: 0 };
    if (blockingMask()) return { done: false, action: 'wait_mask', total, passed, pending: pendingCards.length };
    const active = document.querySelector(S.cardActive);
    const passBtn = document.querySelector(S.passBtn);
    if (!active || !active.classList.contains('pending') || !passBtn) {
      pendingCards[0].click();
      return { done: false, action: 'select', total, passed, pending: pendingCards.length };
    }
    passBtn.click();
    return { done: false, action: 'pass', total, passed, pending: pendingCards.length };
  `;

  let bestPassed = -1, stalled = 0, last = null;
  for (let step = 1; step <= maxSteps; step++) {
    const data = await evalJson(client, tabId, body, { selectors });
    last = data;
    if (onProgress) onProgress(step, data);

    if (data.done) return { success: true, total: data.total, passed: data.passed, steps: step };
    if (data.action === 'no_cards') return { success: false, reason: "no_cards", last };

    if (data.passed > bestPassed) { bestPassed = data.passed; stalled = 0; }
    else if (++stalled >= stallLimit) return { success: false, reason: "stalled", stalled, last };

    await sleep(data.action === 'wait_mask' ? 200 : data.action === 'select' ? 300 : intervalMs);
  }
  return { success: false, reason: "max_steps_exceeded", last };
}

/**
 * 触发阶段流转并确认弹窗。
 * 动作按钮取 stageBar 内「第一个匹配 STAGE_ACTIONS 的按钮」；确认按钮取弹窗主按钮（结构定位）。
 * Gate 2：弹窗正文必须包含 actionText（缺省取触发按钮的实际文案）才点确认，否则取消并熔断。
 * 调用前提：已获得人机终审授权（Gate 4）。
 */
export async function confirmStageTransition(client, tabId, {
  actionText = null, selectors = {}, actions = STAGE_ACTIONS, settleMs = 600, settlePolls = 6,
} = {}) {
  const before = await getStatus(client, tabId, { selectors, actions });

  const trigger = await evalJson(client, tabId, `
    const want = ${JSON.stringify(actionText)};
    const btn = stageBtns().find(b => !want || b.innerText.includes(want));
    if (!btn) return { clicked: false, reason: 'stage_button_not_found' };
    if (isDisabled(btn)) return { clicked: false, reason: 'stage_button_disabled', text: btn.innerText.trim() };
    btn.click();
    return { clicked: true, text: btn.innerText.trim() };
  `, { selectors, actions });
  if (!trigger.clicked) return { success: false, reason: trigger.reason, detail: trigger };

  const expect = actionText || trigger.text;
  await sleep(settleMs);

  const confirm = await evalJson(client, tabId, `
    const box = Array.from(document.querySelectorAll(S.msgBox)).find(vis);
    if (!box) return { clicked: false, reason: 'modal_not_found' };
    const text = box.innerText.trim();
    const ok = box.querySelector(S.msgBoxConfirm);
    if (!text.includes(${JSON.stringify(expect)})) {
      const cancel = Array.from(box.querySelectorAll('button')).find(b => b !== ok && /取消|cancel/i.test(b.innerText));
      if (cancel) cancel.click();
      return { clicked: false, reason: 'modal_text_mismatch', modalText: text.slice(0, 200) };
    }
    if (!ok) return { clicked: false, reason: 'confirm_btn_not_found', modalText: text.slice(0, 200) };
    ok.click();
    return { clicked: true, text: ok.innerText.trim(), modalText: text.slice(0, 200) };
  `, { selectors, actions });
  if (!confirm.clicked) return { success: false, reason: confirm.reason, detail: confirm };

  // 回读：Story 状态或阶段按钮变化即视为流转生效
  let after = null;
  for (let i = 0; i < settlePolls; i++) {
    await sleep(settleMs);
    after = await getStatus(client, tabId, { selectors, actions });
    const changed = after.storyStatus !== before.storyStatus
      || JSON.stringify(after.stageBtn) !== JSON.stringify(before.stageBtn);
    if (changed) return { success: true, before, after, modal: confirm.modalText };
  }
  return { success: false, reason: "no_state_change_after_confirm", before, after, modal: confirm.modalText };
}

/**
 * 解析目标标签页。输入可为：数字 tabId、`Story-123456`、含 Story 号的完整 URL。
 * 已打开则复用（Gate 1 显式槽位）；未打开则开新页并返回 tabId。
 */
export async function resolveTab(client, target) {
  if (/^\d+$/.test(target)) return parseInt(target, 10);

  const story = (target.match(/Story-\d+/) || [])[0];
  if (!story) throw new Error(`无法从 "${target}" 解析 Story 号或 tabId`);

  const list = await client.call("tabs", { action: "list" });
  const re = new RegExp(`^\\[(\\d+)\\].*case-execution/${story}\\b`, "m");
  const hit = list.text.match(re);
  if (hit) return parseInt(hit[1], 10);

  const url = /^https?:/.test(target)
    ? target
    : `${workbenchBase()}#/test-workbench/case-execution/${story}`;
  const opened = await client.call("tabs", { action: "new", url, label: `test-workbench ${story}` });
  await sleep(2500);
  return opened.tabId;
}

// CLI 执行模式
if (process.argv[1] && process.argv[1].endsWith("test_case_runner.mjs")) {
  const [,, cmd, target, actionText] = process.argv;
  if (!cmd || !target) {
    console.log("用法: node test_case_runner.mjs <status|pass-all|confirm-stage> <tabId|Story-XXXX|URL> [actionText]");
    console.log("示例: node test_case_runner.mjs status Story-288904");
    console.log("      node test_case_runner.mjs pass-all 713198443");
    console.log("      node test_case_runner.mjs confirm-stage Story-288904 冒烟通过   # 需先获得人机终审授权");
    console.log("环境变量: TEST_WORKBENCH_BASE 覆盖工作台根 URL（默认 " + DEFAULT_BASE + "）");
    process.exit(1);
  }

  const client = await getHuashuClient();
  try {
    const tabId = await resolveTab(client, target);
    console.log(`标签页 [${tabId}]`);
    if (cmd === "status") {
      console.log(JSON.stringify(await getStatus(client, tabId), null, 2));
    } else if (cmd === "pass-all") {
      const res = await passAllPending(client, tabId, {
        onProgress: (step, d) => console.log(`Step ${step}: action=${d.action || 'done'}, passed=${d.passed}, pending=${d.pending}/${d.total}`),
      });
      console.log("执行完成:", JSON.stringify(res, null, 2));
      if (!res.success) process.exitCode = 2;
    } else if (cmd === "confirm-stage") {
      const res = await confirmStageTransition(client, tabId, { actionText: actionText || null });
      console.log("阶段流转结果:", JSON.stringify(res, null, 2));
      if (!res.success) process.exitCode = 2;
    } else {
      console.error(`未知命令: ${cmd}`);
      process.exitCode = 1;
    }
  } finally {
    client.close();
  }
}
