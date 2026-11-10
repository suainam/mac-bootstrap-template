import fs from "fs";
import path from "path";
import { getHuashuClient } from "./huashu_driver.mjs";

/**
 * 32 项 PRD 标准必填字段规约（必须使用全角中文括号）
 */
export const REQUIRED_32_FIELDS = [
  // 1. 背景与目标 (6项)
  "业务背景",
  "用户价值",
  "商业价值",
  "量化目标（baseline→target）",
  "目标用户画像",
  "与现有功能关系",
  // 2. 业务流程 (5项)
  "核心业务流程描述",
  "关键节点说明",
  "异常流程处理（业务视角）",
  "业务流程图（Mermaid）",
  "涉及角色/系统",
  // 3. 功能需求 (7项)
  "功能点列表（优先级 P0/P1/P2）",
  "每个功能的详细说明",
  "功能间依赖关系",
  "边界场景（edge_cases）",
  "关联用户故事",
  "不做范围",
  "子需求拆分（含 owner）",
  // 4. 验收与非功能 (4项)
  "功能验收标准（GWT+可观测指标）",
  "性能指标要求",
  "兼容性要求",
  "埋点/数据验证",
  // 5. 系统架构 (5项)
  "系统交互流程图（Mermaid）",
  "关键逻辑说明",
  "数据流转",
  "接口设计（请求/响应结构）",
  "数据模型/表结构",
  // 6. 状态与运维 (5项)
  "状态定义及转换规则",
  "边界条件处理",
  "异常状态处理（系统视角）",
  "降级/回滚方案",
  "监控/告警"
];

/**
 * 本地静态校验 PRD Markdown 是否满足 32 项必填项
 */
export function auditLocalPrdMarkdown(content) {
  const missing = [];
  for (const field of REQUIRED_32_FIELDS) {
    if (!content.includes(field)) {
      missing.push(field);
    }
  }

  // 关键语法与陷阱特征检查
  const warnings = [];
  if (content.includes("边界场景 (edge_cases)")) {
    warnings.push("使用了半角英文括号 '边界场景 (edge_cases)'，平台解析器会判定为未填写，必须修正为 '边界场景（edge_cases）'");
  }
  if (content.includes("### 量化目标\n") || content.includes("## 量化目标\n")) {
    warnings.push("使用了简写 '量化目标'，必须为 '量化目标（baseline→target）'");
  }
  if (content.includes("（示例，实际依契约）") || content.includes("(示例，实际依契约)")) {
    warnings.push("数据模型中包含 '示例/依契约' 模糊字样，易触发平台质量缺陷扣分");
  }

  return {
    total: REQUIRED_32_FIELDS.length,
    matchedCount: REQUIRED_32_FIELDS.length - missing.length,
    missing,
    warnings,
    isCompliant: missing.length === 0 && warnings.length === 0
  };
}

/**
 * 提取页面当前的 PRD 元数据与评分详情
 */
export async function dumpPrdStatus(client, tabId) {
  const expr = `(async () => {
    const text = document.body.innerText;
    
    // 提取评分区块
    let score = null;
    let structureScore = null;
    let qualityScore = null;
    let version = "unknown";
    
    const vMatch = text.match(/V\\d+ 版本/);
    if (vMatch) version = vMatch[0];

    const allLines = text.split("\\n").map(l => l.trim()).filter(Boolean);
    const scoreIdx = allLines.indexOf("综合评分");
    if (scoreIdx > 0) {
      score = allLines[scoreIdx - 1] || null;
    }
    const structIdx = allLines.indexOf("结构分");
    if (structIdx !== -1) {
      structureScore = allLines[structIdx + 1] || null;
    }
    const qualIdx = allLines.indexOf("质量分");
    if (qualIdx !== -1) {
      qualityScore = allLines[qualIdx + 1] || null;
    }

    // 提取 32 字段填写状态
    const all = Array.from(document.querySelectorAll("*")).filter(el => {
      const t = el.innerText || "";
      return t === "必填" || t === "选填";
    });
    const fields = all.map(el => {
      const parent = el.parentElement;
      return parent ? parent.innerText.replace(/\\n/g, " | ") : "";
    });

    // 提取修改建议
    const sugIdx = text.indexOf("修改建议：");
    let suggestions = "";
    if (sugIdx !== -1) {
      const endIdx = text.indexOf("1. 需求背景与价值", sugIdx);
      suggestions = text.slice(sugIdx, endIdx !== -1 ? endIdx : sugIdx + 3000);
    }

    // 提取 prdId 与 storyCode
    let prdId = null;
    let storyCode = null;
    const el = document.querySelector(".vditor") || document.body;
    for (const k of Object.keys(el)) {
      if (k.startsWith("__reactFiber")) {
        let fiber = el[k];
        while (fiber) {
          if (fiber.memoizedProps?.prdInfo) {
            prdId = fiber.memoizedProps.prdInfo.prdId;
            storyCode = fiber.memoizedProps.prdInfo.storyCode;
            break;
          }
          if (fiber.memoizedState) {
            let s = fiber.memoizedState;
            while (s) {
              if (s.memoizedState?.current?.prdId) {
                prdId = s.memoizedState.current.prdId;
                storyCode = s.memoizedState.current.storyCode;
                break;
              }
              s = s.next;
            }
          }
          fiber = fiber.return;
        }
      }
    }

    return {
      version,
      score,
      structureScore,
      qualityScore,
      prdId,
      storyCode,
      unfilledFields: fields.filter(f => !f.includes("已填写")),
      suggestionsSnippet: suggestions.slice(0, 1000)
    };
  })()`;

  const res = await client.call("eval", { expr, tabId });
  return JSON.parse(res.text.split("\n\n（提示：")[0].trim());
}

/**
 * 直写 PRD 内容到后端存储并同步 Fiber 状态
 */
export async function directSavePrd(client, tabId, markdownContent, options = {}) {
  const expr = `(async () => {
    // 1. 查找 Fiber 中的 prdId 和 user
    let prdId = null;
    let currentVersion = 1;
    let qiFiber = null;

    const el = document.querySelector(".vditor") || document.body;
    for (const k of Object.keys(el)) {
      if (k.startsWith("__reactFiber")) {
        let fiber = el[k];
        while (fiber) {
          if (fiber.memoizedProps?.onSavePrd) qiFiber = fiber;
          if (fiber.memoizedState) {
            let s = fiber.memoizedState;
            while (s) {
              if (s.memoizedState?.current?.prdId) {
                prdId = s.memoizedState.current.prdId;
                currentVersion = s.memoizedState.current.version || 1;
              }
              s = s.next;
            }
          }
          fiber = fiber.return;
        }
      }
    }

    if (!prdId) {
      return { ok: false, error: "未找到 PRD 实体 ID，请确认当前处于原型设计工作台" };
    }

    // 2. 提取认证 Token
    const token = localStorage.getItem("Agent-Token") || "";
    const devopsToken = localStorage.getItem("Devops-Platform-Token") || "";
    const username = localStorage.getItem("username") || localStorage.getItem("user") || "unknown";

    const headers = {
      "Content-Type": "application/json",
      "Authorization": "Bearer " + token,
      "Agent-Token": token,
      "Devops-Platform-Token": devopsToken
    };

    // 3. 原生调用持久化保存接口
    const savePayload = {
      prd_id: String(prdId),
      content: ${JSON.stringify(markdownContent)},
      created_by: username,
      version: currentVersion + 1
    };

    const saveRes = await fetch("/api/product-agent/prd/save", {
      method: "POST",
      headers,
      body: JSON.stringify(savePayload)
    }).then(r => r.json()).catch(e => ({ error: e.message }));

    // 4. 同步 React 临时状态 (防止前端未刷新时状态回退)
    if (qiFiber && typeof qiFiber.memoizedProps?.setTempPrdContent === "function") {
      qiFiber.memoizedProps.setTempPrdContent(${JSON.stringify(markdownContent)});
    }

    return { ok: true, prdId, saveRes };
  })()`;

  const res = await client.call("eval", { expr, tabId });
  return JSON.parse(res.text.split("\n\n（提示：")[0].trim());
}

/**
 * 触发重新检测并轮询直到评分出炉
 */
export async function triggerAndPollScore(client, tabId, maxWaitSec = 45) {
  // 点击重新检测按钮
  const clickExpr = `(() => {
    const btn = Array.from(document.querySelectorAll("button")).find(b => b.innerText.trim() === "重新检测");
    if (!btn) return { ok: false, error: "未找到'重新检测'按钮" };
    
    // 优先调用 React onClick 避开 DOM 穿透限制
    const k = Object.keys(btn).find(k => k.startsWith("__reactFiber"));
    let fiber = btn[k];
    while (fiber) {
      if (typeof fiber.memoizedProps?.onClick === "function") {
        fiber.memoizedProps.onClick();
        return { ok: true, method: "fiber.onClick" };
      }
      fiber = fiber.return;
    }
    btn.click();
    return { ok: true, method: "dom.click" };
  })()`;

  const clickRes = await client.call("eval", { expr: clickExpr, tabId });
  const parsedClick = JSON.parse(clickRes.text.split("\n\n（提示：")[0].trim());
  if (!parsedClick.ok) return parsedClick;

  // 轮询评分计算状态
  const start = Date.now();
  while ((Date.now() - start) < maxWaitSec * 1000) {
    await new Promise(r => setTimeout(r, 3000));
    const status = await dumpPrdStatus(client, tabId);
    
    const checkCalculating = `(() => {
      const text = document.body.innerText;
      return text.includes("正在重新检测") || text.includes("正在计算评分") || text.includes("检测中");
    })()`;
    const checkRes = await client.call("eval", { expr: checkCalculating, tabId });
    const isCalculating = JSON.parse(checkRes.text.split("\n\n（提示：")[0].trim());

    if (!isCalculating && status.score) {
      return { ok: true, status };
    }
  }

  return { ok: false, error: "评分检测超时" };
}

// CLI 执行模式
if (process.argv[1] && process.argv[1].endsWith("prd_workbench.mjs")) {
  const [,, cmd, ...args] = process.argv;
  if (!cmd || cmd === "--help" || cmd === "-h") {
    console.log("用法: node prd_workbench.mjs <cmd> [options]");
    console.log("命令:");
    console.log("  audit <file.md>                 静态检查 PRD Markdown 是否符合 32 项标准目录与规约");
    console.log("  dump --tabId <id>               抓取当前页面的 PRD 评分、版本、未填项与修改建议");
    console.log("  save --tabId <id> --file <md>   直写 Markdown 文件至平台存储并同步状态");
    console.log("  score --tabId <id>              触发重新检测并轮询评分结果");
    process.exit(0);
  }

  const getArg = (flag) => {
    const idx = args.indexOf(flag);
    return idx !== -1 && idx + 1 < args.length ? args[idx + 1] : null;
  };

  if (cmd === "audit") {
    const filePath = args[0];
    if (!filePath || !fs.existsSync(filePath)) {
      console.error("请提供有效的 Markdown 文件路径");
      process.exit(1);
    }
    const content = fs.readFileSync(filePath, "utf8");
    const result = auditLocalPrdMarkdown(content);
    console.log(JSON.stringify(result, null, 2));
    process.exit(result.isCompliant ? 0 : 1);
  }

  const tabIdStr = getArg("--tabId");
  const tabId = tabIdStr ? parseInt(tabIdStr, 10) : undefined;
  const client = await getHuashuClient();

  try {
    if (tabId) {
      await client.call("tabs", { action: "select", tabId }).catch(() => {});
    }
    if (cmd === "dump") {
      const status = await dumpPrdStatus(client, tabId);
      console.log(JSON.stringify(status, null, 2));
      process.exit(0);
    } else if (cmd === "save") {
      const filePath = getArg("--file");
      if (!filePath || !fs.existsSync(filePath)) {
        console.error("请通过 --file 提供有效的 Markdown 文件路径");
        process.exit(1);
      }
      const content = fs.readFileSync(filePath, "utf8");
      const saveResult = await directSavePrd(client, tabId, content);
      console.log(JSON.stringify(saveResult, null, 2));
      process.exit(0);
    } else if (cmd === "score") {
      const scoreResult = await triggerAndPollScore(client, tabId);
      console.log(JSON.stringify(scoreResult, null, 2));
      process.exit(0);
    } else {
      console.error(`未知命令: ${cmd}`);
      process.exit(1);
    }
  } catch (e) {
    console.error("执行失败:", e.message || e);
    process.exit(1);
  }
}
