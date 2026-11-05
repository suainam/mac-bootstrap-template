import { getHuashuClient } from "./huashu_driver.mjs";

const sleep = ms => new Promise(r => setTimeout(r, ms));

/**
 * 读取当前测试工作台用例执行统计与阶段按钮状态
 */
export async function getStatus(client, tabId) {
  const expr = `
    (() => {
      const cards = Array.from(document.querySelectorAll('.case-card'));
      const stageBtn = Array.from(document.querySelectorAll('button')).find(b => {
        const t = b.innerText.trim();
        return t.includes('冒烟通过') || t.includes('完成测试');
      });
      const stageText = document.querySelector('.story-status, .step-item.active, .status-tag');
      return {
        total: cards.length,
        passed: cards.filter(c => c.classList.contains('passed')).length,
        pending: cards.filter(c => c.classList.contains('pending')).length,
        failed: cards.filter(c => c.classList.contains('failed')).length,
        stage: stageText ? stageText.innerText.trim() : null,
        stageBtn: stageBtn ? {
          text: stageBtn.innerText.trim(),
          disabled: stageBtn.disabled || stageBtn.classList.contains('is-disabled')
        } : null
      };
    })()
  `;
  const res = await client.call("eval", { tabId, expr });
  return JSON.parse(res.text.replace(/（提示：.*?）/gs, "").trim());
}

/**
 * 紧凑循环执行所有待执行用例，处理动效遮罩与尾部补偿
 */
export async function passAllPending(client, tabId, { maxSteps = 100, intervalMs = 380, onProgress = null } = {}) {
  const stepExpr = `
    (() => {
      const cards = Array.from(document.querySelectorAll('.case-card'));
      const pendingCards = cards.filter(c => c.classList.contains('pending'));
      const passedCards = cards.filter(c => c.classList.contains('passed'));
      const total = cards.length;

      if (pendingCards.length === 0) {
        return { done: true, total, passed: passedCards.length, pending: 0 };
      }

      // 遮罩检查（ElementUI 动效渐隐期）
      const mask = document.querySelector('.el-loading-mask:not([style*="display: none"])');
      if (mask) {
        return { done: false, action: 'wait_mask', total, passed: passedCards.length, pending: pendingCards.length };
      }

      const activePending = document.querySelector('.case-card.active.pending');
      const passBtn = document.querySelector('.result-btn.passed-btn');

      // 尾部失焦或未处于 pending 卡片时主动激活
      if (!activePending || !passBtn) {
        pendingCards[0].click();
        return { done: false, action: 'select', total, passed: passedCards.length, pending: pendingCards.length };
      }

      passBtn.click();
      return { done: false, action: 'passed', total, passed: passedCards.length + 1, pending: pendingCards.length - 1 };
    })()
  `;

  for (let step = 1; step <= maxSteps; step++) {
    const res = await client.call("eval", { tabId, expr: stepExpr });
    const cleanText = res.text.replace(/（提示：.*?）/gs, "").trim();
    const data = JSON.parse(cleanText);

    if (onProgress) onProgress(step, data);

    if (data.done || data.pending === 0) {
      return { success: true, total: data.total, passed: data.passed, steps: step };
    }

    const wait = data.action === 'wait_mask' ? 200 : (data.action === 'select' ? 300 : intervalMs);
    await sleep(wait);
  }

  return { success: false, reason: "max_steps_exceeded" };
}

/**
 * 触发阶段流转按钮及弹窗二次确认（严格断言弹窗按钮）
 */
export async function confirmStageTransition(client, tabId, { actionText = "冒烟通过", confirmText = "确认通过" } = {}) {
  // 1. 点击流转触发按钮
  const triggerExpr = `
    (() => {
      const btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.trim().includes(${JSON.stringify(actionText)}));
      if (btn && !btn.disabled && !btn.classList.contains('is-disabled')) {
        btn.click();
        return { clicked: true, text: btn.innerText.trim() };
      }
      return { clicked: false };
    })()
  `;
  const r1 = await client.call("eval", { tabId, expr: triggerExpr });
  const d1 = JSON.parse(r1.text.replace(/（提示：.*?）/gs, "").trim());
  if (!d1.clicked) return { success: false, reason: `action_button_${actionText}_not_clickable` };

  await sleep(600);

  // 2. 点击模态弹窗中的确认按钮
  const confirmExpr = `
    (() => {
      const modal = document.querySelector('.el-dialog__wrapper:not([style*="display: none"]), .el-message-box__wrapper:not([style*="display: none"])');
      if (!modal) return { clicked: false, reason: 'modal_not_found' };
      const btns = Array.from(modal.querySelectorAll('button'));
      const target = btns.find(b => b.innerText.trim().includes(${JSON.stringify(confirmText)}) || b.classList.contains('el-button--primary'));
      if (target) {
        target.click();
        return { clicked: true, text: target.innerText.trim() };
      }
      return { clicked: false, reason: 'confirm_btn_not_found' };
    })()
  `;
  const r2 = await client.call("eval", { tabId, expr: confirmExpr });
  const d2 = JSON.parse(r2.text.replace(/（提示：.*?）/gs, "").trim());
  return { success: d2.clicked, detail: d2 };
}

// CLI 执行模式
if (process.argv[1] && process.argv[1].endsWith("test_case_runner.mjs")) {
  const [,, cmd, rawTabId, opt1, opt2] = process.argv;
  if (!cmd || !rawTabId) {
    console.log("用法: node test_case_runner.mjs <status|pass-all|confirm-stage> <tabId> [actionText] [confirmText]");
    console.log("示例: node test_case_runner.mjs status 713198443");
    console.log("      node test_case_runner.mjs pass-all 713198443");
    console.log("      node test_case_runner.mjs confirm-stage 713198443 冒烟通过 确认通过");
    console.log("      node test_case_runner.mjs confirm-stage 713198443 完成测试 确认完成");
    process.exit(1);
  }

  const tabId = parseInt(rawTabId, 10);
  const client = await getHuashuClient();

  try {
    if (cmd === "status") {
      const status = await getStatus(client, tabId);
      console.log(JSON.stringify(status, null, 2));
    } else if (cmd === "pass-all") {
      console.log(`开始执行标签页 [${tabId}] 待执行用例推进...`);
      const res = await passAllPending(client, tabId, {
        onProgress: (step, d) => console.log(`Step ${step}: action=${d.action || 'done'}, passed=${d.passed}, pending=${d.pending}/${d.total}`)
      });
      console.log("执行完成:", JSON.stringify(res, null, 2));
    } else if (cmd === "confirm-stage") {
      const res = await confirmStageTransition(client, tabId, {
        actionText: opt1 || "冒烟通过",
        confirmText: opt2 || "确认通过"
      });
      console.log("阶段流转结果:", JSON.stringify(res, null, 2));
    } else {
      console.error(`未知命令: ${cmd}`);
      process.exit(1);
    }
  } finally {
    client.close();
  }
}
