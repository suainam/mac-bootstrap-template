---
name: huashu-jev-automation
description: 用 huashu-chrome 驱动已登录 Chrome，配 TypeSafe Jev 做内环微决策。用于多步网页流程自动化、企业 SSO 账号密码登录、QA 测试工作台用例批量执行与阶段流转、Vue/React 受控表单注入与文件上传、跨域 iframe 的 REST 直写与附件透传、AI 产品工作台 PRD 直写与评分审计、以及需要多标签槽位隔离与人机终审的高风险提交。
---

# huashu-jev-automation

外环由主 Agent 编排，环境感知交给 huashu-chrome（复用已登录会话），元素与动作判定交给 Jev，字段文本交给 magpie，能直写底层 API 就不模拟点击。分层职责见 `references/architecture.md`。

## 连接与槽位

```js
import { getHuashuClient } from "<skill>/scripts/huashu_driver.mjs";
const client = await getHuashuClient();
await client.call("tabs", { action: "list" });          // 唤醒休眠的 Service Worker
await client.call("eval", { expr }, { tabId });         // tabId 是第三参
```

`tabId` 必须放在 `call` 的第三参选项里。写进 params 会报「还没有受控标签页——先 tabs(action:"new") 开一个」。

用 omp 的 `browser.open({ app: { relay: true } })` 会命中操作边界 `Operation boundary: browser`，只有 operator 能放行，无绕过路径。一律走 BridgeClient。

## 前置条件

| 依赖 | 要求 | 缺失表现 |
|---|---|---|
| huashu-chrome 扩展 | 启用，网站访问权限设为「在所有网站上」 | `Cannot access contents of the page. Extension manifest must request permission` |
| Chrome 登录态 | 目标站点已 SSO 登录，连接现有实例 | 页面跳到登录页 |
| Python ≥ 3.9 | 仅标准库，`scripts/typesafe_jev.py` 可直接 import | `ModuleNotFoundError: typesafe_jev` |
| Jev API key | `TYPESAFE_JEV_TOKEN`（主）、`TYPESAFE_JEV_TOKEN1`（备），缺一自动回退 | 401；路由见 `references/key-routing.md` |
| magpie 网关 | 仅 TYPE_TEXT 需要；`TEXT_MODEL=group/group-daily` | `group/group-fast` 路由 Groq，不支持 `reasoning`，HTTP 400 |

自检：`python -c "import typesafe_jev"`、`echo $TYPESAFE_JEV_TOKEN`、扩展权限、目标站登录态。

## 模式选择

| 模式 | 触发场景 | 展开位置 |
|---|---|---|
| A 结构化表单批量填充 | 字段已知的静态表单 | 本文 |
| B 投机式扇出动态步进 | 分页巡检、多级菜单、流转路径未知 | 本文 |
| C Canvas/纯视觉定位 | 无 DOM 的 canvas、图表、扫描件 | 本文 + `references/canvas-mode-notes.md` |
| D 受控表单与文件注入 | Vue3/React/Element UI 受控输入、动态 `input[type=file]` | `references/interaction-patterns-def.md#模式-d` |
| E 多标签槽位与 Four-Gate | 有真实业务副作用的操作 | `references/interaction-patterns-def.md#模式-e` |
| F 顶层 REST 直写与附件透传 | 跨域 iframe 报权限、需复用会话 Cookie | `references/interaction-patterns-def.md#模式-f` |
| G 测试工作台批量执行与阶段流转 | QA 用例面板、冒烟与系统测试流转 | `references/interaction-patterns-def.md#模式-g` |
| H SSO 账号密码登录 | 内网统一认证网关 | `references/interaction-patterns-def.md#模式-h` |
| I PRD 直写与评分审计 | AI 产品工作台 PRD 达标 | `references/interaction-patterns-def.md#模式-i` |

### 模式 A：结构化表单批量填充

一次 Jev 请求映射全部字段到 ref，再批量 `act`：

```python
from typesafe_jev import send_jev
resp, key = send_jev(
    questions={
        "store_code_ref": {"type": "choice", "instructions": "门店编码输入框 ref",
                           "criteria": {"e1": "门店编码", "e2": "日期", "none": "未找到"}},
    }
)
```

`act({"do": "type", "ref": ref, "text": val})` 或 `act({"do": "select", "ref": ref, "value": val})`。回读 DOM `value` 或 `read_text` 校验。

### 模式 B：投机式扇出动态步进

一趟请求同时决定「操作类别」与「目标候选」：

```python
resp, key = send_jev(
    state={"goal": "...", "history": [], "page": "<snapshot 元素树>"},
    questions={
        "operation": {"type": "choice", "instructions": "下一步执行哪个操作？",
                      "criteria": {"CLICK": "点击可点元素", "TYPE_TEXT": "向输入框输入",
                                   "SELECT": "下拉选择", "SCROLL_DOWN": "向下滚动继续查找",
                                   "WAIT": "仍在加载", "DONE": "全部目标已满足（需验证）",
                                   "BLOCKED": "无可用交互推进"}},
        "click_target": {"type": "choice", "instructions": "若 CLICK，选目标 ref",
                         "criteria": {"e5": "查询按钮", "": "非点击"}},
    }
)
```

### 模式 C：Canvas/纯视觉定位

截图交给 Jev 的 Box 问题，返回归一化包围盒（`left/right/top/bottom` ∈ [0,1]）换算坐标点击。

启用条件：Jev 1.14+；请求带 `TypeSafe-Danger-Zone-Images: true`；图像须被 state/instructions/criteria 引用。Box 无「未找到」语义，先加 Noul 判存在再问 Box。

```python
resp, key = send_jev(
    questions={
        "target_visible": {"type": "noul", "instructions": "Is the target button visible in `shot`?"},
        "target_box": {"type": "box", "instructions": "the submit button in `shot`"},
    },
    state={"shot": "s"},
    images={"s": ("shot.png", png_bytes, "image/png")},
)
```

模型返回的框仍要按确定性门禁校验再转 `act` 坐标。站点对合成事件免疫时改用底层 API 直写。

## 工具脚本

命令与参数以脚本自身为真源，先跑 `--help`。

| 脚本 | 职责 |
|---|---|
| `scripts/huashu_driver.mjs` | 连接驱动；`callTopFetch`（顶层 fetch 穿透）、`uploadAttachmentToPage`（附件直传） |
| `scripts/prd_workbench.mjs` | PRD 静态审计、直写保存、评分轮询；`audit` 仅为格式参考，真实评分以 `recalculate` 接口为准 |
| `scripts/sso_login.mjs` | SSO 账号密码登录与重定向判定 |
| `scripts/test_case_runner.mjs` | 测试工作台用例推进与阶段流转确认；选择器集中在 `SELECTORS` |
| `scripts/form_injector.mjs` | 受控注入与单实例断言 |
| `scripts/typesafe_jev.py` | 双 key 回退的 Jev 客户端 |

## 排障

| 症状 | 处理 |
|---|---|
| `Cannot access contents of the page` | 扩展权限设「所有网站」；仍失败则改 `client.call("fetch", { url, init }, { tabId })` 走顶层（模式 F） |
| `snapshot` 报 `(el.value ?? el.innerText ?? "").trim is not a function` | 复杂页的扩展解析异常，改用 `eval` 取结构化字段，或 `read_text scope:"page"` |
| 原生 `<select>` 定位失败 | 用 ref 走 `act({"do":"select","ref":"eX","value":"..."})`，不按名称盲猜点击 |
| 自定义下拉/日期格点击无效 | 派发完整序列：`pointerdown → mousedown → pointerup → mouseup → click` |
| `TIMEOUT` / 扩展 32s 未响应 | 页面内不写长循环与 `await sleep`；由 Node 外层以 300–400ms 节流驱动原子 `eval` |
| 冒烟流转后用例数变化 | 阶段流转会增量注入用例（如 26 变 49），重新读卡片数与按钮态 |
| Canvas / 虚拟渲染 | 数据读写优先宿主内部 API（`SpreadsheetApp`，见 `skill://wecom-sheet-internal-api`）；工具栏交互走 snapshot + Jev |

固定规则（URL 域名、状态码、需求编号前缀）直接在代码里分支，不转 Jev。

## 路由

| 目标 | 去处 |
|---|---|
| `*.dslbuy.com` / `assortment.dslyy.com` / `doc.weixin.qq.com/sheet` | `skill://ps-portal-sync`；Wiki 走 REST |
| `ai-devops.dslbuy.com/#/demand/decompose/<id>`，或「拆 Story / 拆分 / 重新拆解 / 挂工时」 | `skill://story-decompose-ai-devops`（四必填：产品线/子系统/到期日/人员四岗） |
| 全栈单规范化改造、PRD 85+、Task 三栏、积分申报 | `skill://full-stack-story-standardization` |
