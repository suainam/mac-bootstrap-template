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

```javascript
// 执行方式: OMP eval browser.open + tab.run("<script>")
const p = await browser.getPage("wiki");
await p.bringToFront();

// 1. 打开目标页面
await p.goto("https://wiki.dslbuy.com/pages/viewpage.action?pageId=122182137");
await p.waitForLoad();

// 2. 提取当前页面元数据 (页面标题、最后修改时间、修改人)
const pageMeta = await p.evaluate(() => {
  const title = document.querySelector('#title-text')?.innerText?.trim() || '';
  const author = document.querySelector('.last-modified a')?.innerText?.trim() || '';
  const date = document.querySelector('.last-modified time')?.innerText?.trim() || '';
  return { title, author, date };
});
console.log("当前 Wiki 页面信息:", JSON.stringify(pageMeta, null, 2));

// 3. 点击进入编辑模式 (或通过键盘触发 'e')
await p.click('#editPageLink');
await p.waitForSelector('#rte-button-publish', { timeout: 10000 });

// 4. 内容安全注入规范
// 注意：Confluence 编辑器多采用 iframe (TinyMCE) 或 Atlassian Content State
const isIframeEditor = await p.evaluate(() => !!document.querySelector('#wysiwygTextarea_ifr'));

if (isIframeEditor) {
  // 进入 iframe 注入更新块 (例如在文档末尾追加修订记录)
  const frame = p.frames().find(f => f.name() === 'wysiwygTextarea_ifr');
  if (frame) {
    await frame.evaluate((changelogHtml) => {
      const body = document.querySelector('#tinymce');
      if (body) {
        body.insertAdjacentHTML('beforeend', changelogHtml);
      }
    }, '<h3>2026-10 策略修订记录</h3><p>已同步禁发仓逻辑与门店三合一池，回刷分区 20261012 完成。</p>');
  }
} else {
  // 现代编辑器：直接定位正文区域
  await p.evaluate((text) => {
    const editor = document.querySelector('.ProseMirror, [contenteditable="true"]');
    if (editor) {
      editor.focus();
      document.execCommand('insertText', false, text);
    }
  }, '\n\n【2026-10 修订记录】：完成禁发仓指标与门店三合一池对齐。\n');
}

// 5. 校验无破坏性格式后，点击保存/发布
await p.click('#rte-button-publish');
await p.waitForLoad();
console.log("Wiki 更新发布完成。");
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
