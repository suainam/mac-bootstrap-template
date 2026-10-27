/**
 * wiki_sync_helper.js — Confluence 6.x REST 读写（wiki-rest-first）
 *
 * 在已登录的 wiki.dslbuy.com 标签页内运行（huashu-chrome eval / OMP tab.run），
 * 复用页面 Cookie；浏览器端 fetch 自动带 SSO 会话。
 *
 *   const c = new ConfluenceWikiClient("128206125");
 *   const p = await c.getPage();                       // {title, version, storageHtml}
 *   await c.uploadAttachment("x.sql", sqlText);        // 先传附件
 *   const html = replaceOnce(p.storageHtml, oldFrag, newFrag + viewFileMacro("x.sql"));
 *   await c.updatePage(p.title, html, p.version, "说明");
 */

// 线上页面实测的附件宏形态（pageId=128206125 storage 回读）
function viewFileMacro(fileName, height = 150) {
  return `<ac:structured-macro ac:name="view-file" ac:schema-version="1">` +
    `<ac:parameter ac:name="name"><ri:attachment ri:filename="${fileName}" /></ac:parameter>` +
    `<ac:parameter ac:name="height">${height}</ac:parameter></ac:structured-macro>`;
}

// 幂等门禁：旧片段必须恰好命中 1 次，否则抛错（0 次=已改过或锚点失效；>1 次=锚点不唯一）
function replaceOnce(html, oldFrag, newFrag) {
  const n = html.split(oldFrag).length - 1;
  if (n !== 1) throw new Error(`replaceOnce: 锚点命中 ${n} 次，期望 1 次`);
  return html.replace(oldFrag, () => newFrag);
}

class ConfluenceWikiClient {
  constructor(pageId) {
    this.pageId = String(pageId);
    this.token = document.querySelector('meta[name="atlassian-token"]')?.content || "nocheck";
  }

  async getPage() {
    const res = await fetch(`/rest/api/content/${this.pageId}?expand=body.storage,version`, {
      headers: { "X-Atlassian-Token": this.token },
    });
    if (!res.ok) throw new Error(`getPage HTTP ${res.status}`);
    const d = await res.json();
    return { title: d.title, version: d.version.number, storageHtml: d.body.storage.value };
  }

  // currentVersion 必须是刚读到的版本号；他人期间改过则 409，重新 getPage 再合并
  async updatePage(title, storageHtml, currentVersion, message = "") {
    const res = await fetch(`/rest/api/content/${this.pageId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-Atlassian-Token": this.token },
      body: JSON.stringify({
        id: this.pageId,
        type: "page",
        title,
        body: { storage: { value: storageHtml, representation: "storage" } },
        version: { number: currentVersion + 1, message },
      }),
    });
    if (!res.ok) throw new Error(`updatePage HTTP ${res.status}: ${(await res.text()).slice(0, 300)}`);
    return res.json();
  }

  // 同名附件已存在时的更新端点（/child/attachment/{attId}/data）本站未实测；先 GET 附件列表确认再用
  async uploadAttachment(fileName, content, comment = "") {
    const fd = new FormData();
    fd.append("file", new Blob([content], { type: "application/octet-stream" }), fileName);
    if (comment) fd.append("comment", comment);
    const res = await fetch(`/rest/api/content/${this.pageId}/child/attachment`, {
      method: "POST",
      headers: { "X-Atlassian-Token": "nocheck" },
      body: fd,
    });
    if (!res.ok) throw new Error(`uploadAttachment HTTP ${res.status}`);
    return (await res.json()).results?.[0];
  }
}

if (typeof module !== "undefined") module.exports = { ConfluenceWikiClient, viewFileMacro, replaceOnce };
