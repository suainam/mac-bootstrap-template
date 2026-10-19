/**
 * wecom_sheet_audit.js: 企微/腾讯文档在线表格 (doc.weixin.qq.com/sheet) 结构与合并格审计脚本
 * 
 * 用法:
 *   jev-browser-use --connect http://127.0.0.1:9222 -e "$(cat scripts/wecom_sheet_audit.js)"
 */

async function auditWecomSheet() {
  const pages = await browser.listPages();
  if (pages.length === 0) {
    throw new Error("当前未检测到活动的受控页面靶标，请先使用 browser.newPage() 打开目标文档");
  }
  
  // 匹配第一个活动 sheet 页面
  const target = pages.find(p => p.url.includes("doc.weixin.qq.com/sheet")) || pages[0];
  const p = await browser.getPage(target.id);
  
  const auditData = await p.evaluate(() => {
    const app = window.SpreadsheetApp;
    if (!app || !app.workbook || !app.workbook.activeSheet) {
      return { ready: false, message: "页面未完成 SpreadsheetApp 初始化" };
    }
    
    const workbook = app.workbook;
    const sheet = workbook.activeSheet;
    const e2eTools = app.e2eTools;
    const mergeManager = sheet.mergeManager;
    
    const rowCount = sheet.getRowCount();
    const colCount = sheet.getColCount();
    const merges = mergeManager.mergeList || [];
    
    // 默认扫描前 50 行核心区域
    const scanLimit = Math.min(rowCount, 50);
    const rows = [];
    
    for (let r = 0; r < scanLimit; r++) {
      const cells = {};
      let hasData = false;
      for (let c = 0; c < Math.min(colCount, 26); c++) {
        const val = e2eTools.getCellEditValue(workbook, r, c);
        if (val !== undefined && val !== null && val !== "") {
          cells[String.fromCharCode(65 + c)] = val;
          hasData = true;
        }
      }
      if (hasData) {
        rows.push({ row: r + 1, cells });
      }
    }
    
    return {
      ready: true,
      title: document.title,
      sheetName: sheet.getSheetName(),
      sheetId: workbook.activeSheetId,
      rowCount,
      colCount,
      mergeCount: merges.length,
      merges: merges.map(m => ({
        range: `${String.fromCharCode(65 + m.startColIndex)}${m.startRowIndex + 1}:${String.fromCharCode(65 + m.endColIndex)}${m.endRowIndex + 1}`,
        startRow: m.startRowIndex + 1,
        endRow: m.endRowIndex + 1,
        startCol: String.fromCharCode(65 + m.startColIndex),
        endCol: String.fromCharCode(65 + m.endColIndex)
      })),
      rows
    };
  });
  
  console.log(JSON.stringify(auditData, null, 2));
  return auditData;
}

if (typeof browser !== "undefined") {
  await auditWecomSheet();
}
