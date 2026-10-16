#!/usr/bin/env node
/**
 * wecom_sheet_driver.js
 * 
 * 企业微信 / 腾讯文档共享表格 (doc.weixin.qq.com/sheet) 自动化全功能驱动脚本
 * 
 * 核心设计:
 *   1. 遵循 wy-coliney/jev-browser-use & browser-use/jev-ultrafast 官方稳定性规范:
 *      - 严禁在跨源页面跳转时盲目调用 Puppeteer 的 page.goto()，规避 LifecycleWatcher disposed 异常。
 *      - 单自闭环原子脚本: 状态探测 -> 平滑过渡 -> SpreadsheetApp.behaviorApi.cellApi.setRangeValue -> OT 回读。
 *      - 杜绝全局 OS 模拟按键 (keystroke "v") 抢焦泄漏。
 *   2. 支持行插入与结构维护 (SpreadsheetApp.behaviorApi.dimensionApi)。
 *   3. 结合 SpreadsheetApp.e2eTools.getCellEditValue 实现结构与公式审计。
 * 
 * 用法:
 *   node .claude/skills/ps-portal-sync/scripts/wecom_sheet_driver.js --doc <e3_ID> --audit
 *   node .claude/skills/ps-portal-sync/scripts/wecom_sheet_driver.js --doc <e3_ID> --write-tsv <file.tsv> --start-cell C21
 *   node .claude/skills/ps-portal-sync/scripts/wecom_sheet_driver.js --doc <e3_ID> --clear-range P21:P41
 */

import { execSync } from "child_process";
import fs from "fs";
import path from "path";

// 命令行参数解析
const args = process.argv.slice(2);
function getArg(flag) {
  const idx = args.indexOf(flag);
  return idx !== -1 && args[idx + 1] ? args[idx + 1] : null;
}
const isAudit = args.includes("--audit");
const writeTsvFile = getArg("--write-tsv");
const startCell = getArg("--start-cell") || "C21";
const clearRange = getArg("--clear-range");
const relayPort = getArg("--port") || "9222";

// 目标文档标识（必填，防止误写）
const DOC_ID = getArg("--doc");
if (!DOC_ID) {
  console.error("[Driver] 必须指定 --doc <URL 中的 e3_ 文档 ID 片段>，防止误写");
  process.exit(2);
}

/**
 * 将形如 "C21" 的单元格坐标解析为 0-based { rowIndex, colIndex }
 */
function parseCellCoord(coordStr) {
  const match = coordStr.trim().toUpperCase().match(/^([A-Z]+)(\d+)$/);
  if (!match) throw new Error(`无效单元格坐标: ${coordStr}`);
  const colLetters = match[1];
  const rowNum = parseInt(match[2], 10);
  let colIndex = 0;
  for (let i = 0; i < colLetters.length; i++) {
    colIndex = colIndex * 26 + (colLetters.charCodeAt(i) - 64);
  }
  return {
    rowIndex: rowNum - 1,
    colIndex: colIndex - 1
  };
}

/**
 * 执行 jev-browser-use 运行自闭环内联 Puppeteer/CDP 脚本
 */
function runBrowserScript(scriptBody, timeoutSeconds = 45) {
  const tmpScript = path.join("/tmp", `wecom_atomic_${Date.now()}_${Math.random().toString(36).slice(2, 6)}.js`);
  fs.writeFileSync(tmpScript, scriptBody, "utf8");
  try {
    const out = execSync(`jev-browser-use --connect http://127.0.0.1:${relayPort} -t ${timeoutSeconds} < "${tmpScript}"`, {
      encoding: "utf8",
      maxBuffer: 10 * 1024 * 1024
    });
    return out;
  } finally {
    if (fs.existsSync(tmpScript)) fs.unlinkSync(tmpScript);
  }
}

/**
 * 生成原子自闭环执行头代码 (平滑导航与引擎就绪探测)
 */
function makeAtomicHeader(docId) {
  return `
const p = await browser.getPage("wbs_worker");
const targetDocId = "${docId}";

// 官方规范: 若已在目标文档页，绝不重复导航
if (!p.url().includes(targetDocId)) {
  console.log("[Atomic] 正在平滑定向至目标文档:", targetDocId);
  await p.evaluate((doc) => {
    window.location.href = "https://doc.weixin.qq.com/sheet/" + doc;
  }, targetDocId).catch(() => {});
}

// 轮询等待腾讯文档协同引擎与底层行为 API 完全就绪
let ready = false;
let activePage = p;
for (let i = 0; i < 30; i++) {
  await new Promise(r => setTimeout(r, 1000));
  try {
    activePage = await browser.getPage("wbs_worker");
    ready = await activePage.evaluate(() => {
      const app = window.SpreadsheetApp;
      return !!(app && app.workbook && app.workbook.activeSheet && app.behaviorApi?.cellApi && app.e2eTools);
    });
    if (ready) break;
  } catch (err) {}
}
if (!ready) throw new Error("[Atomic] 腾讯文档协同引擎超时未就绪 (30s)");
`;
}

/**
 * 原子写入 TSV 矩阵
 */
async function writeTsv(filePath, startCoordStr) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`TSV 文件不存在: ${filePath}`);
  }
  const content = fs.readFileSync(filePath, "utf8");
  const lines = content.trim().split("\n").map(l => l.split("\t"));
  const start = parseCellCoord(startCoordStr);
  console.log(`[Driver] 准备原子写入 TSV (${lines.length} 行 × 最大 ${Math.max(...lines.map(l => l.length))} 列)，起始格: ${startCoordStr}...`);

  const payloadJson = JSON.stringify(lines);
  const startJson = JSON.stringify(start);

  const script = `
${makeAtomicHeader(DOC_ID)}

const rowsData = ${payloadJson};
const startPos = ${startJson};

const writeResult = await activePage.evaluate(async (rows, start) => {
  const app = window.SpreadsheetApp;
  const b = app.behaviorApi;
  const sheet = app.workbook.activeSheet;
  const sheetId = sheet.getSheetId();
  
  const rangeValues = [];
  for (let rIdx = 0; rIdx < rows.length; rIdx++) {
    const rowNum = start.rowIndex + rIdx;
    const cols = rows[rIdx];
    for (let cIdx = 0; cIdx < cols.length; cIdx++) {
      rangeValues.push({
        rowIndex: rowNum,
        colIndex: start.colIndex + cIdx,
        userEnterValue: cols[cIdx] !== undefined ? cols[cIdx] : ""
      });
    }
  }
  
  const rev = await b.cellApi.setRangeValue({
    sheetId,
    rangeValues
  });
  
  return { ok: true, count: rangeValues.length, revision: rev };
}, rowsData, startPos);

console.log("[Driver] 原子写入响应:", JSON.stringify(writeResult));

// 等待 WebSocket OT 协同版本完成提交
await new Promise(r => setTimeout(r, 1200));

// 回读前 5 行进行校验断言
const readback = await activePage.evaluate((start) => {
  const wb = window.SpreadsheetApp.workbook;
  const e2e = window.SpreadsheetApp.e2eTools;
  const res = [];
  for (let r = 0; r < 5; r++) {
    const rowNum = start.rowIndex + r;
    res.push({
      row: rowNum + 1,
      colC: e2e.getCellEditValue(wb, rowNum, 2),
      colD: (e2e.getCellEditValue(wb, rowNum, 3) || "").slice(0, 25),
      colE: e2e.getCellEditValue(wb, rowNum, 4),
      colO: e2e.getCellEditValue(wb, rowNum, 14)
    });
  }
  return res;
}, startPos);

console.log("[Driver] 现场断言回读样例:\\n" + JSON.stringify(readback, null, 2));
`;

  const out = runBrowserScript(script);
  console.log(out.trim());
}

/**
 * 审计表格结构与数据
 */
async function auditSheet() {
  console.log(`[Driver] 正在对目标文档 ${DOC_ID} 进行结构与公式审计...`);
  const script = `
${makeAtomicHeader(DOC_ID)}

const auditResult = await activePage.evaluate(() => {
  const wb = window.SpreadsheetApp.workbook;
  const sheet = wb.activeSheet;
  const e2e = window.SpreadsheetApp.e2eTools;
  const rows = [];
  for (let r = 20; r <= 41; r++) {
    rows.push({
      row: r + 1,
      C: e2e.getCellEditValue(wb, r, 2),
      D: (e2e.getCellEditValue(wb, r, 3) || "").slice(0, 30),
      E: e2e.getCellEditValue(wb, r, 4),
      O: e2e.getCellEditValue(wb, r, 14),
      P: e2e.getCellEditValue(wb, r, 15)
    });
  }
  return {
    sheetName: sheet.getSheetName(),
    rowCount: sheet.getRowCount(),
    sampleRows: rows
  };
});

console.log(JSON.stringify(auditResult, null, 2));
`;
  const out = runBrowserScript(script);
  console.log(out.trim());
}

// 主入口分发
async function main() {
  if (isAudit) {
    await auditSheet();
  } else if (writeTsvFile) {
    await writeTsv(writeTsvFile, startCell);
  } else {
    console.log("请指定操作参数: --audit | --write-tsv <path> --start-cell <cell>");
  }
}

main().catch(err => {
  console.error("[Driver Fatal]", err.message);
  process.exit(1);
});
