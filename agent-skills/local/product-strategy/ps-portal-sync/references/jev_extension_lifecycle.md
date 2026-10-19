# Jev 浏览器扩展靶标生命周期与连接防踩坑 SOP (Jev Extension Lifecycle)

本文档针对 `jev-browser-use` 配合 Chrome 扩展（Relay 模式）进行企业内部系统自动化时，靶标注册、生命周期脱钩、跨域导航崩溃以及多标签泄露等典型故障提供权威诊断与处理准则。

---

## 1. 核心机制：靶标隔离与生命周期绑定

### 1.1 扩展靶标隔离原则 (`extension-target-discipline`)
Jev 浏览器扩展通过 CDP 协议连接本地 Relay 服务（端口 9222）时，**具备严格的靶标安全隔离机制**：
- 扩展只对**通过 CDP 显式发起 `Target.createTarget` 命令创建的新标签**附加 `chrome.debugger`，并向本地 CLI 发送 `Target.targetCreated` 注册事件。
- **用户在 Chrome 中手工打开的原生标签页，扩展绝不会主动附加调试器，也不会向 CLI 暴露**。
- **铁律结论**：
  - `browser.listPages()` 返回空数组 `[]` 或 Relay 状态显示 `targets: 0`，**仅代表当前没有受控的活动自动化靶标，绝不代表用户没有打开页面，更不代表目标站点不支持自动化**！
  - 严禁因为 `listPages()` 为空就向用户断言“页面不存在”或“插件未生效”。

### 1.2 防盲目循环新建 (`no-blind-getpage`)
- `browser.getPage(name)` 的底层实现是 **`get-or-create`**（若存在名为 `name` 的标签则复用，若不存在则调用 `Target.createTarget` 在 Chrome 中新建一个标签并自动加入 `jev-browser-use` 标签组）。
- **严重反模式**：当因网络或跨域导航导致靶标失联时，若在循环逻辑中不断调用 `browser.getPage(name)`，将导致 Chrome 内部疯狂弹出数十个同名或空白重复标签，造成内存耗尽和严重的页面冗余。
- **规约**：
  1. 页面失联后，先通过一次性 `browser.listPages()` 或原生检查确认现状。
  2. 若需开启新页面，必须通过脚本明确调用一次 `browser.newPage()` 获取稳定 handle 并记录 targetId。
  3. 绝对禁止在未捕获成功 handle 的循环重试体内连续调用 `browser.getPage(...)`。

---

## 2. 跨源导航防脱钩规范 (`native-goto-first`)

在处理复杂企业门户（如从 `about:blank` 导航至 `devops.dslbuy.com`、`doc.weixin.qq.com` 等具有强安全沙箱与 SSO 重定向的站点）时：

### 2.1 崩溃根因分析
- 错误写法：`await page.frames()[0].evaluate(url => { location.href = url; }, targetUrl)`。
- 崩溃根因：跨域导航会触发 Chrome 现代架构的 Site Isolation / RenderFrameHost 进程替换。底层主 frame 被直接销毁替换，而 Puppeteer 的 `LifecycleWatcher` 未能通过标准生命周期钩子介入，导致立即抛出：
  `Error: Attempted to use detached Frame` 或 `Navigating frame was detached`，随之 CDP 靶标彻底脱钩。

### 2.2 规范范式
必须统一使用 Puppeteer 原生驱动的导航方法：
```javascript
// ✅ 权威导航范式：由底层 CDP 生命周期监视器平滑追踪 RenderFrameHost 切换
await page.goto(targetUrl, { 
  waitUntil: "domcontentloaded",
  timeout: 30000 
});
```

---

## 3. 优雅清理与单连接隔离纪律

### 3.1 严禁滥用全局 `stop`
- 执行 `jev-browser-use stop` 会**直接杀死整个自动化后台 Daemon 进程并强行关闭其托管的所有浏览器实例**。如果用户正好在同一个 Chrome profile 下处理事务，将造成用户工作现场被直接截断。
- **规范清理协议**：
  ```javascript
  // ✅ 仅关闭当前任务所拥有并记录的特定靶标
  const ownedPages = await browser.listPages();
  for (const p of ownedPages) {
    if (p.name === targetName || p.id === recordedTargetId) {
      await browser.closePage(p.name || p.id);
    }
  }
  ```

### 3.2 Relay 服务与靶标状态解耦
- `nohup` 或持久化服务模式保护的是**本地 9222 端口的 TCP WebSocket 监听进程**，保证其中断后不会被主进程回收。
- 但持久进程**不等于** CDP 内部的靶标会话依然健康。当遇到不可逆的 CDP Session 失效时，最干净的恢复 SOP 为：
  1. 正常断开 CLI 客户端；
  2. 在 Chrome 扩展弹窗中点击一次开关使状态变为 Disconnected，随后重新点击变为 Connected；
  3. 客户端重新发起连接即可秒级恢复通信。
