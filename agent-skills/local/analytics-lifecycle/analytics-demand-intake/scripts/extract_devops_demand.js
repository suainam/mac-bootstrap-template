/**
 * extract_devops_demand.js: 从 DevOps 需求管理微前端提取原始需求列表与详情 JSON
 *
 * 运行方式 (OMP eval browser with Chromium mode):
 *   在 OMP eval (language="js") 中调用，使用 tab.run 的 Puppeteer page API:
 *
 *   const script = await read("scripts/extract_devops_demand.js");
 *   const tab = await browser.open({ name: "devops", url: "https://devops.dslbuy.com/#/story/list", app: { relay: true } });
 *   const result = await tab.run(script);
 *   console.log(JSON.stringify(result, null, 2));
 *   await tab.close();
 *
 * 或者指定目标需求 ID:
 *   const result = await tab.run(`const targetIds = [28706, 31924]; ${script}`);
 *
 * 注意:
 *   - 需要 OMP relay 扩展加载到真实 Chrome (带登录 cookies)
 *   - tab.run 代码在 Node 环境运行，page 是 Puppeteer Page 对象
 *   - 批量拉取几十条需求时，先获取 AUTH_B64 与行列表，再在宿主环境用 curl
 */

async function captureDevopsAuthAndRows(targetIdsOpt) {
  const f0 = page.frames()[0];

  // 1. 穿透导航至原始需求路由 (避免跨进程直接 goto 导致 RenderFrameHost 崩溃)
  if (!(await page.url()).includes("/story/list")) {
    await f0.evaluate((url) => { window.location.href = url; }, "https://devops.dslbuy.com/#/story/list");
    await new Promise((r) => setTimeout(r, 5000));
  }

  // 2. 定位微前端 iframe (https://pmp.dslbuy.com/...)
  const f1 = page.frames().find((f) => f.url().includes("pmp.dslbuy.com"));
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

  return {
    authB64: Buffer.from(payload.authHeader || "").toString("base64"),
    count: payload.count,
    rows: payload.tableRows,
    details: payload.details
  };
}

// tab.run entry: page is available in scope
return await captureDevopsAuthAndRows(typeof targetIds !== "undefined" ? targetIds : null);

