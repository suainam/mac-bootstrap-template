# Element-UI 与企业中台 DOM 交互规范

本文档为 `ps-portal-sync` 涉及的企业四大门户系统（HPM 绩效、DevOps 研发效能、商品决策、Wiki）提供统一的 DOM 定位器、事件派发规范与交互协议。

---

## 1. 核心底座契约：`v-model-sync`

所有基于 Vue/Element-UI 的输入框，直接修改 `input.value` **不会触发 Vue 内部响应式状态更新**。必须在赋值后触发 `input` 与 `change` 事件：

```javascript
// 规范的 Vue 输入框赋值范式
function setVueInputValue(el, value) {
  if (!el) return;
  el.value = value;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}
```

---

## 2. 统一组件定位器矩阵

| 交互场景 | 目标组件 | 核心定位器 (Selector) | 操作协议 |
| :--- | :--- | :--- | :--- |
| **表单文本输入** | `el-input` | `.el-form-item input.el-input__inner` 或 `textarea.el-textarea__inner` | 聚焦 → 设置 `.value` → 派发 `input`/`change` |
| **下拉选择** | `el-select` | 触发器：`.el-select .el-input__inner`<br>选项池：`document.querySelectorAll('.el-select-dropdown__item:not([style*="display: none"])')` | 点击触发器 → 等待下拉浮层（挂载在 `document.body`）→ 点击目标文本选项 |
| **表格数据提取** | `el-table` | 表头：`.el-table__header-wrapper th .cell`<br>行节点：`.el-table__body-wrapper tr.el-table__row`<br>单元格：`td.el-table__cell .cell` | 提取表头列表 → 遍历行节点提取单元格纯文本 → 组装为字典数组 |
| **表格行内操作** | `el-table` 操作列 | 行内按钮：`tr.el-table__row button.el-button` 或 `a` | 匹配行特征（如需求ID）→ 定位该行内的具体按钮点击 |
| **分页切换** | `el-pagination` | 下一页：`.el-pagination .btn-next`<br>页码：`.el-pagination .el-pager li.number` | 检查 `btn-next` 是否包含 `.disabled` 类名，未禁用时方可点击 |
| **常规弹窗** | `el-dialog` | 容器：`.el-dialog__wrapper:not([style*="display: none"]) .el-dialog`<br>确认按钮：`.el-dialog__footer button.el-button--primary` | 唤起后等待动画（200~300ms）→ 填写表单 → 点击确认按钮 |
| **只读悬浮输入** | `el-popover` | 触发点：行内只读 `textarea, input[readonly]`<br>悬浮层：`document.querySelectorAll('.el-popper.el-popover:not([style*="display: none"])')` | 点击只读框唤出 → 定位最后一个可见 popover 内的 `textarea` → 派发事件 → 点击【确认】 |
| **标签页切换** | `el-tabs` | 标签头：`.el-tabs__header .el-tabs__item#tab-<name>`<br>内容区：`.el-tabs__content #pane-<name>` | 点击目标标签头 → 等待 300ms 确认 active 类名切换完成 |

---

## 3. 四大门户特异性 DOM 说明

### A. DevOps 效能平台 (`devops.dslbuy.com`)
1. **需求列表定位** (`/#/story/list`):
   - 支持通过 Query 参数直接定位：`/#/story/list?id=<STORY_ID>`。
   - 过滤输入框通常带 `placeholder="请输入需求名称/ID"`。
2. **工时日历表单** (`/#/timeWise/timeSheet`):
   - 包含工作日列与任务行。
   - 工时单元格通常使用内嵌输入框或点击后激活可编辑态的数字输入器（`.el-input-number`）。

### B. HPM 绩效系统 (`xzapp.dslbuy.com/hpm`)
1. **定性指标行索引 (3.1 ~ 3.6)**：
   - 对应责任书表格（`#tab-detail`）中固定行索引 6 至 11。
   - 下拉框选择目标档位（如 `1档(系数：1)`）。
   - 文本录入必须遵守 `popover-gate`（点击唤起悬浮窗录入）。
2. **员工自评 Tab**：
   - 标签选择器：`#tab-selfEvaluation`。
   - 包含“复盘和总结”与“待提升点”两组独立 `textarea`。

### C. 商品决策平台 (`assortment.dslyy.com`)
1. **运营看板** (`/#/operation/board`):
   - 顶部包含级联省区/门店类型选择器（`.el-cascader`）。
   - 核心指标卡片：`.card-item, .metric-box` 内部提取数字与同比环比文本。

### D. Confluence Wiki (`wiki.dslbuy.com`)
1. **文档查看态** (`/pages/viewpage.action?pageId=...`):
   - 页面标题：`#title-text a`。
   - 核心正文：`#main-content .wiki-content`。
2. **文档编辑态**:
   - 编辑按钮：`#editPageLink`（快捷键 `e`）。
   - 编辑器核心：通常挂载在 TinyMCE iframe (`#wysiwygTextarea_ifr`) 或现代 Atlassian 编辑器中。
   - 保存按钮：`#rte-button-publish` 或 `button[name="confirm"]`。

---

## 4. DevOps 需求管理微前端穿透与 API 批量提取协议 (`xhr-api-first`)

在 `devops.dslbuy.com/#/story/list` 中，需求列表与详情均挂载在内部微前端 iframe (`https://pmp.dslbuy.com/`)，后端接口由 `https://devops-order.dslbuy.com` 提供：

1. **Frame 穿透定位**：
   ```javascript
   const f0 = page.frames()[0];
   // 异步路由避免 RenderFrameHost 崩溃
   if (!f0.url().includes("/story/list")) {
     await f0.evaluate(url => { window.location.href = url; }, "https://devops.dslbuy.com/#/story/list");
     await sleep(5000);
   }
   const f1 = page.frames().find(f => f.url().includes("pmp.dslbuy.com"));
   ```
2. **拦截 XHR 获取有效 `Authorization` 令牌**：
   `localStorage.user` 中的缓存 token 可能过期，直接重放易报 `401 暂未登录或token已经过期`。标准做法是在 `f1` 内临时 Hook `XMLHttpRequest.prototype.setRequestHeader`，点击首行【查看详情】触发一次真实请求捕获活跃 `Authorization` 头，随后立即点击【关闭】释放抽屉：
   ```javascript
   const authHeader = await f1.evaluate(async () => {
     let h = "";
     const orig = XMLHttpRequest.prototype.setRequestHeader;
     XMLHttpRequest.prototype.setRequestHeader = function(k, v) {
       if (k.toLowerCase() === "authorization") h = v;
       return orig.apply(this, arguments);
     };
     const link = Array.from(document.querySelectorAll(".el-table__body-wrapper tr.el-table__row a, .el-table__body-wrapper tr.el-table__row span"))
       .find(el => el.innerText.trim() === "查看详情");
     if (link) link.click();
     await new Promise(r => setTimeout(r, 600));
     XMLHttpRequest.prototype.setRequestHeader = orig;
     Array.from(document.querySelectorAll(".el-drawer button, .el-overlay button"))
       .filter(b => b.innerText.trim() === "关闭").forEach(b => b.click());
     return h;
   });
   ```
   *注：`jev-browser-use -e` 的沙箱不支持 `require("fs")` 且单行 `console.log` 超过 4KB 会截断，可将 `authHeader` 以 Base64 打印到宿主环境后，用 `curl -s --noproxy '*' -H "Authorization: $AUTH" "https://devops-order.dslbuy.com/demand/manager/detail?demandId=<ID>"` 高速并发拉取完整 JSON。*
3. **核心接口与枚举字典映射**：
   - **详情接口**：`GET https://devops-order.dslbuy.com/demand/manager/detail?demandId=<ID>`
   - **保存视图接口**：`GET https://devops-order.dslbuy.com/userQueryFilter?userId=10093621&namespaceId=10093621&namespace=demand&kind=demand&view=8`
   - **`demandStatus` 状态码**：`3 = 待应答`，`5 = 待排期`，`11 = 排期中`，`6 = 研发中`
   - **`demandValueCategory` 价值分类**：`0 = 增加收入`，`1 = 降低成本`，`2 = 提升效率`，`3 = 管控风险`，`4 = 基础建设`
   - **`reviewResult` 审议结论**：`1 = 不通过`，`2 = 暂缓`，`3 = 待定`，`4 = 通过`
   - **核心返回字段**：`businessLineVo.lineName`（所属模块）、`tags[].tagName`（需求标签）、`valueDescribe`（目标导向/量化收益）、`contentDescribe`（需求原文富文本 HTML）、`jiras[]`（关联 Story 工作项：`workItemCode`、`summary`、`status`、`dev_start`、`dev_end`、`due`、`demandResponsibleName`、`key`）、`files[]`（OSS 附件 `fileName` 与签名 `filePath`）。
