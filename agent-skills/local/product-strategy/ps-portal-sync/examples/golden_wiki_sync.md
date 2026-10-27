# Confluence Wiki 知识沉淀与文档更新黄金范例 (Golden Example: Wiki Sync)

本范例展示在 `wiki.dslbuy.com` 中将商品策略业务资产（如《常规经营目录V7.0-策略逻辑》）规范沉淀或同步至目标页面的全流程。

---

## 1. 业务文档准备规范 (Grounded Document Draft)

* **目标空间**: 数智中台部
* **目标页面**: `https://wiki.dslbuy.com/pages/viewpage.action?pageId=122182137`
* **版本标签**: `V7.0.2`
* **内容规范**: 
  - 剔除本地文件相对路径引用（如 `./scripts/export.py`），转换为标准说明文字。
  - 核心 SQL 逻辑采用标准 SQL 代码块包裹。
  - 表格必须具有完整表头与对齐。

---

## 2. 自动化执行脚本
### 方案 A：REST API 秒级直读直写与附件挂载（首选，耗时 < 3s）

Confluence 6.13 自带标准 REST API。只要携带登录态 Cookie 与 `X-Atlassian-Token: nocheck` 请求头，可跳过 TinyMCE 前端富文本编辑器的缓慢加载与 DOM 操作：

```javascript
// 执行方式：huashu-chrome eval，复用现有 Wiki 标签页。
// 规范实现为单一权威：scripts/wiki_sync_helper.js（先把其源码注入页面，再调用 API）。
const c = new ConfluenceWikiClient("128206125");
const p = await c.getPage();                // { title, version, storageHtml }

const oldFrag = "<li>自有品牌优化</li>";
const storageHtml = replaceOnce(p.storageHtml, oldFrag,
  "<li>自有品牌优化（Demand-31939b）…</li>");   // 锚点须恰好命中 1 次，0/多次抛错

await c.updatePage(p.title, storageHtml, p.version, "自动化同步策略口径");  // PUT 发布，version 自动 +1
```

`getPage` / `updatePage` / `replaceOnce` / `viewFileMacro` 均定义于
[`scripts/wiki_sync_helper.js`](../../scripts/wiki_sync_helper.js)（同一目录下），文档不再另抄一份实现。

#### 附件上传与 View-File 宏自动绑定

先上传附件，再在 Storage 正文插入 `view-file` 宏。宏形态取自线上页面 `pageId=128206125` 的 storage 回读（2026-10-27 实测），完整封装见 `scripts/wiki_sync_helper.js`：
- 注意：同名附件已存在时的更新端点（`/child/attachment/{attId}/data`）本站未实测；先 `GET /rest/api/content/{id}/child/attachment` 确认或重命名再传。

```javascript
const fd = new FormData();
fd.append("file", new Blob([fileContentStr], { type: "application/octet-stream" }), fileName);
await fetch(`/rest/api/content/${pageId}/child/attachment`, {
  method: "POST", headers: { "X-Atlassian-Token": "nocheck" }, body: fd
});

// 正文宏（Storage 格式）：
// <ac:structured-macro ac:name="view-file" ac:schema-version="1">
//   <ac:parameter ac:name="name"><ri:attachment ri:filename="demand-31939b-query.sql" /></ac:parameter>
//   <ac:parameter ac:name="height">150</ac:parameter>
// </ac:structured-macro>
```

---

### 方案 B：富文本 TinyMCE DOM 注入（复杂样式/视觉高亮备选）

针对需要给既有表格特定 `<tr>` 标黄底色（`style="background-color: #fffb8f"`）或红字高亮的场景，使用 `huashu-chrome` 操纵 TinyMCE：

```javascript
const ed = window.tinymce?.activeEditor;
const doc = ed.getDoc();
const targetRow = Array.from(doc.querySelectorAll("table")[1].querySelectorAll("tr"))
  .find(tr => tr.innerText.includes("步骤4: 最终剔除"));

// 1. 整行黄底
targetRow.style.backgroundColor = "#fffb8f";
targetRow.querySelectorAll("td").forEach(td => td.style.backgroundColor = "#fffb8f");

// 2. 定点红字插入与宏占位符挂载
targetRow.querySelectorAll("td")[3].insertAdjacentHTML(
  "beforeend",
  `<ul><li><span style="color: red;"><strong>新增策略逻辑</strong>：...</span></li></ul>`
);
```
---

## 2. 页面克隆与新版本创建范例 (Clone & Create New Version Page)

在同级目录下将现有页面完整复制，并升级为新版本（如 V7.0 -> V8.0）：

```javascript
// 执行方式: OMP eval browser.open + tab.run("<script>")
const p = await browser.getPage("wiki");
const f = p.frames()[0];

// 1. 触发 Confluence 原生克隆路由
await f.evaluate(({ sourcePageId, spaceKey }) => {
  window.location.href = `https://wiki.dslbuy.com/pages/copypage.action?idOfPageToCopy=${sourcePageId}&spaceKey=${spaceKey}`;
}, { sourcePageId: '122182137', spaceKey: 'XXSJGLB' });
await new Promise(r => setTimeout(r, 6000));

const copyFrame = p.frames()[0];
// 2. 变更标题为新版本 (如 V8.0) 并同步事件
await copyFrame.evaluate((newTitle) => {
  const titleInput = document.querySelector('#content-title');
  if (titleInput) {
    titleInput.value = newTitle;
    titleInput.dispatchEvent(new Event('input', { bubbles: true }));
    titleInput.dispatchEvent(new Event('change', { bubbles: true }));
    titleInput.dispatchEvent(new Event('blur', { bubbles: true }));
  }
}, '【商品决策系统】目录统一管理-门店常规经营目录（三合一目录）V8.0-策略逻辑');

// 3. 点击发布完成创建
await copyFrame.evaluate(() => {
  const publishBtn = document.querySelector('#rte-button-publish');
  if (publishBtn) publishBtn.click();
});
await new Promise(r => setTimeout(r, 6000));

const newPageUrl = p.frames()[0].url();
console.log("新版本页面创建成功:", newPageUrl);
```
---

## 3. 验收门禁

1. **标题保持不变**：严禁误改已确立的规范标题（如 `【商品决策系统】目录统一管理-门店常规经营目录（三合一目录）V7.0-策略逻辑`）。
2. **格式保真**：表格、代码高亮必须正常渲染，不得遗留破损的 Markdown 转义符（如 `\` 或多余的 HTML 实体）。
3. **版本回溯**：Confluence 具备原生页面历史版本（Page History），修改后需记录更新日志（Version Comment）。
