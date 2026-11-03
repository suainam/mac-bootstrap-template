---
name: huashu-jev-automation
description: In-browser automation using huashu-chrome with TypeSafe Jev micro-decisions. Use when automating multi-step web flows (forms, paginated lists, DOM ref actions), injecting controlled inputs into React/Vue components or uploading files dynamically, or handling mission-critical submissions needing multi-tab safety gates and human-in-the-loop sign-off.
---

## 环境依赖

运行本技能需要以下环境，缺一不可：

1. **huashu-chrome 扩展**：已安装并启用，网站访问权限设为**「在所有网站上」**（`chrome://extensions` → huashu-chrome → 详细信息 → 网站访问权限）。否则对未授权域名报 `Cannot access contents of the page. Extension manifest must request permission`。
2. **复用登录态的 Chrome**：目标站点须已完成 SSO 登录；主 Agent 通过 CDP/调试端口连接，不要另开无登录态的实例。
3. **Python ≥ 3.9**（仅标准库）：`scripts/typesafe_jev.py` 只用 stdlib；将其所在目录放入 `sys.path` 后 `from typesafe_jev import send_jev`。
4. **Jev API key**：`TYPESAFE_JEV_TOKEN`（主）与 `TYPESAFE_JEV_TOKEN1`（备）；缺一时自动回退（详见 `references/key-routing.md`）。
5. **magpie 文本网关（仅 TYPE_TEXT 需要）**：用 `TEXT_MODEL=group/group-daily`；`group/group-fast` 底层路由 Groq，不支持 `reasoning` → HTTP 400。OMP `.env` 含字面 token，用 `os.environ` 注入，**勿用 `uv --env-file`**。

**快速自检**：`python -c "import typesafe_jev"` 可导入；`echo $TYPESAFE_JEV_TOKEN` 非空；huashu-chrome 权限「所有网站」；目标站已登录。

## 交互模式

### 模式 A: 结构化表单批量填充 *(micro-decision + direct-dom-ref)*

针对已知字段的静态/常规表单（约 3 秒完成 5 字段）：

1. **快照采集**：调用 huashu `snapshot` 拿到编号元素列表（`[e1]`, `[e2]`...）。
2. **一次性 Jev 语义映射**（*micro-decision*）：单个 Jev 请求同时映射所有字段 → ref：
   ```python
   from typesafe_jev import send_jev
   resp, key = send_jev(
       questions={
           "store_code_ref": {"type": "choice", "instructions": "门店编码输入框 ref",
                              "criteria": {"e1": "门店编码", "e2": "日期", "none": "未找到"}},
           "region_select_ref": {"type": "choice", "instructions": "所属大区下拉框 ref",
                                 "criteria": {"e3": "所属大区", "none": "未找到"}},
       }
   )
   ```
3. **批量执行 `act`**（*direct-dom-ref*）：`act({"do": "type", "ref": ref, "text": val})` 或 `act({"do": "select", "ref": ref, "value": val})`。
4. **校验回读**：`eval` 提取 DOM `value` 或 `read_text` 验证填充结果。

### 模式 B: 投机式扇出动态步进 *(speculative fan-out)*

针对分页巡检、多级菜单或未知流转路径。一趟 Jev 请求同时决定「操作类别」与「目标候选」：

```python
resp, key = send_jev(
    state={"goal": "...", "history": [], "page": "<snapshot 元素树>"},
    questions={
        "operation": {
            "type": "choice",
            "instructions": "下一步执行哪个操作？",
            "criteria": {
                "CLICK": "点击可点元素",
                "TYPE_TEXT": "向输入框输入内容",
                "SELECT": "下拉选择",
                "SCROLL_DOWN": "向下滚动继续查找",
                "WAIT": "结果仍在加载或控件暂时不可交互",
                "DONE": "全部预期目标已满足（需验证）",
                "BLOCKED": "无可用交互推进",
            },
        },
        "click_target": {"type": "choice", "instructions": "若操作为 CLICK，选择目标 ref",
                          "criteria": {"e5": "查询按钮", "": "非点击"}},
        "type_target": {"type": "choice", "instructions": "若操作为 TYPE_TEXT，选择目标 ref",
                        "criteria": {"e2": "关键字输入框", "": "非输入"}},
    },
)
```

### 模式 C: Canvas/纯视觉定位 *(image-box)*

针对无 DOM 的 canvas/大渲染页面（企微表格、图表、扫描件）：截图发给 Jev 用 Box 问题定位目标，返回归一化包围盒（`left/right/top/bottom` ∈ [0,1]）换算成坐标执行点击。

启用条件：Jev 1.14+；请求携带 `TypeSafe-Danger-Zone-Images: true`；图像须被 state/instructions/criteria 引用。Box 无"未找到"语义，先加 Noul 判定存在再问 Box。

```python
from typesafe_jev import send_jev
with open("canvas1280.png", "rb") as f:
    png_bytes = f.read()
resp, key = send_jev(
    questions={
        "target_visible": {"type": "noul", "instructions": "Is the target button visible in `shot`?"},
        "target_box": {"type": "box", "instructions": "the submit button in `shot`"},
    },
    state={"shot": "s"},
    images={"s": ("shot.png", png_bytes, "image/png")},
)
```

模型返回视觉框，仍需代码按 *deterministic-gate* 校验再转成 `act` 坐标；合成事件免疫站点优先底层 API/直写。实测要点见 `references/canvas-mode-notes.md`。

### 模式 D: Vue/React 受控表单与动态文件注入 *(controlled-setter + dynamic-datatransfer)*

针对现代前端框架（Vue 3 / React / Element UI）和动态 `input[type=file]` 场景。直接赋值 `el.value` 被框架拦截；必须调用原型链原生 setter + 冒泡事件；动态文件注入通过内存 `File` + `DataTransfer`。标准实现在 `scripts/form_injector.mjs`。详见 `references/interaction-patterns-def.md#模式-d`。

### 模式 E: 多标签页并发槽位与 Four-Gate 生产防错 *(explicit-slot + four-gate)*

针对具有真实业务副作用的操作（积分申报、工单提交）。必须实施四重门禁：显式 `tabId` 槽位隔离 → 语义卡片断言 → 单实例防重校验 → 人机终审（不得脚本点击提交）。详见 `references/interaction-patterns-def.md#模式-e`。

### 模式 F: 顶层 REST 直写与附件透传 *(top-fetch-penetration)*

针对 REST/RPC 接口系统（Confluence 6.x、GitLab、Jira）。跨域 iframe 导致 `eval` 报权限时，改用 `client.call("fetch", { url, init }, { tabId })`，仅在顶层 frame 执行原生 fetch，复用会话 Cookie。附件直传通过页面上下文组装 `FormData` POST 上传端点。实现在 `scripts/huashu_driver.mjs`（`callTopFetch` / `uploadAttachmentToPage`）。详见 `references/interaction-patterns-def.md#模式-f`。

## 工具脚本

`scripts/huashu_driver.mjs`（Node.js 驱动，`tabId` 槽位保护，含 `callTopFetch`/`uploadAttachmentToPage`）、`scripts/form_injector.mjs`（受控注入与单实例断言）、`scripts/typesafe_jev.py`（双 key 回退客户端）。主备 key 路由详情见 `references/key-routing.md`。

## 避坑指南

1. **Host Permission 报错 / iframe 穿透**：`eval` 默认 `allFrames: true` 触发拦截。修复：① `chrome://extensions` 设权限「所有网站」；② 降级为 `client.call("fetch", { url, init }, { tabId })`（模式 F）。
2. **Canvas / 虚拟渲染页面**：数据读写优先用宿主内部 API（`SpreadsheetApp`，见 `wecom-sheet-internal-api`）；工具栏/弹窗交互走 snapshot + Jev。
3. **下拉选择 (Select) 定位失败**：原生 `<select>` 用 ref 定位：`act({"do": "select", "ref": "eX", "value": "..."})`，勿按名称盲猜点击。
4. **确定性路由**：固定规则（URL 域名、状态码、需求编号前缀）直接在代码中分支，不转入 Jev。
5. **企业门户路由**：`*.dslbuy.com` / `assortment.dslyy.com` / `doc.weixin.qq.com/sheet` → 读 `skill://ps-portal-sync`；Wiki 走 REST（`wiki-rest-first`）。
6. **扩展休眠探活**：操作前先 `client.call("tabs", { action: "list" })` 唤醒休眠的 Service Worker。

架构职责分工见 `references/architecture.md`。
