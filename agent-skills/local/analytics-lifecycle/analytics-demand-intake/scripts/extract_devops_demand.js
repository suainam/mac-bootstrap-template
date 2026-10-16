/**
 * extract_devops_demand.js: 从 DevOps 需求管理微前端提取原始需求列表与详情 JSON (xhr-api-first)
 *
 * 支持两种模式:
 *   1. 提取当前筛选视图下全部需求 ID 列表 + 活跃 Authorization Token:
 *      jev-browser-use --connect http://127.0.0.1:9222 -e "$(cat scripts/extract_devops_demand.js)"
 *   2. 指定单个或多个 demandId 直接在浏览器上下文内通过 API 拉取结构化详情:
 *      jev-browser-use --connect http://127.0.0.1:9222 -e "const targetIds = [28706, 31924]; $(cat scripts/extract_devops_demand.js)"
 *
 * 注意:
 *   - jev-browser-use -e 环境不支持 require("fs") 且单行 stdout > 4KB 会截断。
 *   - 批量拉取几十条需求时，先获取 AUTH_B64 与行列表，再在宿主环境用:
 *     curl -s --noproxy '*' -H "Authorization: $AUTH" "https://devops-order.dslbuy.com/demand/manager/detail?demandId=<ID>"
 */

async function captureDevopsAuthAndRows(targetIdsOpt) {
  const p = await browser.getPage("devops");
  const f0 = p.frames()[0];

  // 1. 穿透导航至原始需求路由 (避免跨进程直接 goto 导致 RenderFrameHost 崩溃)
  if (!(await p.url()).includes("/story/list")) {
    await f0.evaluate((url) => { window.location.href = url; }, "https://devops.dslbuy.com/#/story/list");
    await new Promise((r) => setTimeout(r, 5000));
  }

  // 2. 定位微前端 iframe (https://pmp.dslbuy.com/...)
  const f1 = p.frames().find((f) => f.url().includes("pmp.dslbuy.com"));
  if (!f1) throw new Error("未找到 PMP 需求管理微前端 iframe (pmp.dslbuy.com)");

  // 3. 拦截 XHR 请求头获取活跃 Authorization Token，同时读取当前表格行摘要
  const payload = await f1.evaluate(async (ids) => {
    let authHeader = "";
    const origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.setRequestHeader = function (k, v) {
      if (k.toLowerCase() === "authorization") authHeader = v;
      return origSetHeader.apply(this, arguments);
    };

    const rows = Array.from(document.querySelectorAll(".el-table__body-wrapper tr.el-table__row"));
    if (rows.length > 0) {
      const link = Array.from(rows[0].querySelectorAll("a, span, .el-link")).find(
        (el) => el.innerText.trim() === "查看详情"
      );
      if (link) link.click();
      await new Promise((r) => setTimeout(r, 600));
    }
    XMLHttpRequest.prototype.setRequestHeader = origSetHeader;

    // 立即关闭抽屉释放 DOM
    Array.from(document.querySelectorAll(".el-drawer button, .el-overlay button"))
      .filter((b) => b.innerText.trim() === "关闭")
      .forEach((b) => b.click());

    const tableRows = rows.map((tr) => {
      const tds = Array.from(tr.querySelectorAll("td")).map((td) => td.innerText.trim());
      return {
        demandName: tds[0] || "",
        demandCode: tds[1] || "",
        demandId: parseInt((tds[1] || "").replace("Demand-", ""), 10),
        productLine: tds[2] || "",
        module: tds[3] || "",
        score: tds[5] || "",
        projectName: tds[6] || "",
        statusText: tds[7] || "",
        proposer: tds[15] || ""
      };
    });

    if (!Array.isArray(ids) || ids.length === 0) {
      return { authHeader, count: tableRows.length, tableRows };
    }

    const details = [];
    for (const id of ids) {
      const resp = await fetch(
        `https://devops-order.dslbuy.com/demand/manager/detail?demandId=${id}`,
        { headers: { Authorization: authHeader } }
      );
      const json = await resp.json();
      details.push(json.data || {});
    }
    return { authHeader, count: details.length, details };
  }, typeof targetIds !== "undefined" ? targetIds : null);

  console.log("AUTH_B64:" + Buffer.from(payload.authHeader || "").toString("base64") + ":END");
  console.log(JSON.stringify({ count: payload.count, rows: payload.tableRows, details: payload.details }, null, 2));
  return payload;
}

if (typeof browser !== "undefined") {
  await captureDevopsAuthAndRows(typeof targetIds !== "undefined" ? targetIds : null);
}
