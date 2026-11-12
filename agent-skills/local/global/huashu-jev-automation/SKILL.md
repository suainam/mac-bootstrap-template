---
name: huashu-jev-automation
description: In-browser automation using huashu-chrome with TypeSafe Jev micro-decisions. Use when automating multi-step web flows (forms, paginated lists, DOM ref actions), authenticating via enterprise SSO passport forms, executing QA test workbench cases and stage transitions (smoke/system tests), injecting controlled inputs into React/Vue components or uploading files dynamically, automating AI product workbench PRD direct-save & score auditing, or handling mission-critical submissions needing multi-tab safety gates and human-in-the-loop sign-off.
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

### 模式 G: 测试工作台批量执行与阶段流转 *(tight-loop + tail-compensation + stage-gate)*

针对 QA 测试工作台（`next.dslbuy.com` 等用例执行面板）的批量自动化执行、状态推进与阶段门禁流转：

1. **宿主外层紧凑循环 (*tight-loop*)**：由 Node.js 驱动步进循环，每步执行轻量原子同步 eval（单步间隔 300~400ms）。**严禁在 Chrome 内部长循环或 `await sleep`**，避免触发 30s 扩展超时（`TIMEOUT`）。
2. **动效遮罩防护 (*mask-guard*)**：仅当遮罩「非 `fade-leave` 过渡态且计算样式可见」时才等待 200ms；残留的 `.el-loading-fade-leave` 遮罩不阻塞（实测 next.dslbuy.com 会残留，旧版按 `style` 字符串判定会永远空转）。优先触发 `.result-btn.passed-btn.click()`。循环带**停滞熔断**（连续 10 步 passed 不增长即返回 `stalled`）。
3. **末尾失焦主动补偿 (*tail-compensation*)**：若用例详情未自动载入「通过」按钮，主动执行 `pendingCards[0].click()` 显式激活。
4. **动态用例扩增与阶段门禁 (*stage-gate*)**：冒烟通过（P0）后重新获取扩充后的系统用例；阶段流转按钮（「冒烟通过」「完成测试」）及模态弹窗确认遵循 Four-Gate 人机终审。

标准实现在 `scripts/test_case_runner.mjs`：选择器集中在导出的 `SELECTORS` 常量；CLI 目标可传 `tabId` / `Story-XXXXXX` / 完整 URL（已开则复用，未开则新开）；阶段按钮与确认弹窗按结构定位，弹窗正文必须含触发按钮文案才确认（Gate 2）；确认后回读 Story 状态（`.twf-status-tag`，如「验证中」）判定流转生效。详见 `references/interaction-patterns-def.md#模式-g`。

### 模式 H: 企业统一身份认证 SSO 自动登录 *(sso-passport-injection + credential-decoupling + redirect-settle)*

针对内网统一认证中心（如 `sso.dslbuy.com/login` 等 CAS / OAuth2 认证网关）的凭据自动化填充与登录重定向流转：

1. **靶向表单锁定 (*passport-form-target*)**：内网 SSO 页面常将手机验证码（`phone`）与账号密码（`passport`）置于同名 `#p_inP_login` 下。必须通过 `input[name="loginWay"][value="passport"]` 向上 `.closest("form")` 锁定真实账号密码表单。
2. **受控注入与事件派发 (*controlled-setter*)**：账号密码来自 `~/.sso-tech-committee.env`（`chmod 600`，严禁代码硬编码）；通过原型链 setter 注入并依次派发 `input` 与 `change` 冒泡事件，避免前端框架值拦截。
3. **合规风控通行 (*clean-pass*)**：调用表单所属 `.login-content__form-submit` 提交按钮；正常派发原生事件可大概率免除行为拼图滑块，直接获取 TGT 票据并重定向。
4. **重定向轮询判定 (*redirect-settle*)**：提交后在 Node 端以 800ms 间隔轮询 `snapshot`，当页面 URL 不再包含 `sso.dslbuy.com/login` 且成功加载目标业务系统即判定登录成功。

标准实现在 `scripts/sso_login.mjs`。详见 `references/interaction-patterns-def.md#模式-h`。

### 模式 I: AI 产品工作台 PRD 闭环直写与评分审计 *(react-fiber-sync + direct-api-save + score-audit)*

针对企业研发平台 AI 产品设计工作台（`ai-devops.dslbuy.com/#/prototype/Story-XXXXXX`）的 PRD 文档编写、质量检测修复与高分（85+）达标流转：

1. **32 项标准目录与标点敏感性 (*pre-flight-audit*)**：平台解析器强依赖全角括号。如 `### 边界场景（edge_cases）` 误用半角括号会直接判未填扣 10 分；`### 每个功能的详细说明` 下必须包含 `#### N.` 逐一对应功能清单；数据模型中避免出现“示例/依契约”等模糊字样。
2. **React Fiber 探针与状态同步 (*fiber-sync*)**：富文本编辑器（Vditor）修改 DOM 不影响底层状态；从 `.vditor` 向上遍历 Fiber 节点提取 `onSavePrd`，并同步更新 `qiFiber.memoizedProps.setTempPrdContent`。
3. **顶层接口持久化直写 (*direct-api-save*)**：长文档通过聊天流式生成极易发生截断遗漏。直接提取 localStorage 会话 Token，调用原生 `POST /api/product-agent/prd/save` 直写 Markdown 实体。
4. **评分检测与真源对账过滤 (*grounding-filter*)**：通过 `fiber.memoizedProps.onClick()` 触发「重新评分/重新检测」（兼容两文案）并轮询分数；保存后 40~60s 内首次重算常返回缓存旧分，需等待刷新或二次重算（见 `references/score-iteration-loop.md`）；对评审器提出的“增加上传接口/强制全量店退货”等脱离数仓实际的建议坚决按仓库真实事实过滤，在不做范围（Non-Goals）中说明防御，绝不盲目迎合捏造需求。

`scripts/prd_workbench.mjs` 的评分死锁与迭代闭环详见 `references/score-iteration-loop.md`。

## 工具脚本

`scripts/prd_workbench.mjs` 支持 `dump`（返回 versionMeta/editMode）、`save`（返回 module_id，取自 file_path）、`fetch --path <OSS url>`（回读持久化 md）、`score`（触发重新评分并轮询至稳定）；`audit` 仅为格式参考，非平台真实评分（评分以 `recalculate` 接口为准）。
`scripts/huashu_driver.mjs`（Node.js 驱动，`tabId` 槽位保护，含 `callTopFetch`/`uploadAttachmentToPage`）、`scripts/prd_workbench.mjs`（AI 产品工作台 PRD 静态审计、直写保存与评分轮询）、`scripts/sso_login.mjs`（企业 SSO 账号密码自动登录与重定向判定）、`scripts/test_case_runner.mjs`（测试工作台用例批量推进与阶段流转确认）、`scripts/form_injector.mjs`（受控注入与单实例断言）、`scripts/typesafe_jev.py`（双 key 回退客户端）。主备 key 路由详情见 `references/key-routing.md`。

## 避坑指南

1. **Host Permission 报错 / iframe 穿透**：`eval` 默认 `allFrames: true` 触发拦截。修复：① `chrome://extensions` 设权限「所有网站」；② 降级为 `client.call("fetch", { url, init }, { tabId })`（模式 F）。
2. **Canvas / 虚拟渲染页面**：数据读写优先用宿主内部 API（`SpreadsheetApp`，见 `wecom-sheet-internal-api`）；工具栏/弹窗交互走 snapshot + Jev。
3. **下拉选择 (Select) 定位失败**：原生 `<select>` 用 ref 定位：`act({"do": "select", "ref": "eX", "value": "..."})`，勿按名称盲猜点击。
4. **确定性路由**：固定规则（URL 域名、状态码、需求编号前缀）直接在代码中分支，不转入 Jev。
5. **企业门户路由**：`*.dslbuy.com` / `assortment.dslyy.com` / `doc.weixin.qq.com/sheet` → 读 `skill://ps-portal-sync`；Wiki 走 REST（`wiki-rest-first`）。
6. **扩展休眠探活**：操作前先 `client.call("tabs", { action: "list" })` 唤醒休眠的 Service Worker。
7. **工作台大循环超时**：批量推进用例时，禁止在单个 `eval` 中写长循环与 `await Promise`；由 Node.js 外层以 300ms 节流轮询驱动原子 `eval`。
8. **动态阶段用例扩增**：冒烟流转（P0）通过后，底层通常局部增量注入系统测试用例（如 26 变 49 条），操作间需刷新卡片与操作按钮状态。
9. **SSO 同 ID 多表单陷阱**：`sso.dslbuy.com` 手机验证码与密码登录使用相同表单 ID（`p_inP_login`）；严禁直接用 `#p_inP_login` 或首个表单选择器，必须以 `input[name="loginWay"][value="passport"]` 锚定。
10. **SSO 凭据隔离与权限**：凭据文件由 `private/sso-tech-committee.env` 管理并软链接至 `~/.sso-tech-committee.env`，文件权限强制保持 `600`（通过 `harden-secret-permissions.sh` 校验）。
11. **PRD 32 项标题全角标点敏感**：`ai-devops` 原型工作台对字段正则极其严格，`边界场景（edge_cases）` 与 `量化目标（baseline→target）` 严禁写成英文半角括号，否则会被判定为“未填写”直接扣 10 分。
12. **评审器建议过度迎合与业务失真**：通用 LLM 评审建议常机械套用 Web 系统规范，对离线数仓/算法类需求提出“补充上传接口/回写状态”等违背实际的建议。必须坚持以仓库代码与调研文档为 SSOT，在 Non-Goals 中申明边界，严禁为提分虚构业务逻辑。
13. **连接浏览器必须用 huashu BridgeClient，勿用 omp `browser.open(relay)`**：在 Eval 里驱动本技能时，直接 `import { getHuashuClient } from "<skill>/scripts/huashu_driver.mjs"` 建 `client`，走扩展通道（`client.call("tabs"/"snapshot"/"eval"/"fetch", params, { tabId })`）连已登录 Chrome。**严禁改用 omp 的 `browser.open({app:{relay:true}})`**——那走宿主 relay 会命中操作边界 `Operation boundary: browser`，且只能由 operator 执行 `/operation-boundary allow browser` 放行、无绕过路径，会浪费多轮。正确顺序：先 `client.call("tabs", {action:"list"})` 定位已开的 `tabId`（避免盲目新建标签），再在该 `tabId` 上执行 snapshot/eval。Eval 报 `(el.value ?? el.innerText ?? "").trim is not a function` 属扩展 rpc 解析异常，换 `eval` 或缩小选择器重试，不要换驱动方式。
14. **ai-devops 需求拆解**：目标是 `ai-devops.dslbuy.com/#/demand/decompose/<id>`，或用户要“拆 Story/拆分/AI拆解/重新拆解/挂工时”时，遵循 `skill://story-decompose-ai-devops`（含四必填选择器交互：产品线/子系统/到期日/人员四岗）。

架构职责分工见 `references/architecture.md`。
