---
name: huashu-jev-automation
description: In-browser automation using huashu-chrome with TypeSafe Jev micro-decisions and group-daily text helpers. Use when automating multi-step web flows with existing login sessions, filling forms, navigating paginated lists, or extracting/acting on DOM ref elements.
---

# huashu-chrome + TypeSafe Jev 浏览器智能交互

在 OMP 或 Codex 等 Agent 环境中，使用 huashu-chrome 控制复用真实登录态的 Chrome，配合 TypeSafe Jev（System One）实现低延迟、低 token 消耗的自动化交互内环。

## 核心主导词 (Leading Words)

- **`【内环微决策 / micro-decision】`**: 针对页面候选元素，由 Jev 一趟 API 调用同时返回操作类别与目标元素 ref，替代大模型长推理。
- **`【感知直通 / direct-dom-ref】`**: 基于 huashu `snapshot` 产出的 `[e1]`, `[e2]` 等 ref 直接执行 `act({"ref": "e..."})`，禁止按 role/name 盲猜定位。
- **`【文本助手 / text-helper】`**: 仅在 `TYPE_TEXT` 时调用小模型生成纯 JSON `{"text": "..."}`，指定 `group/group-daily`。
- **`【确定性门禁 / deterministic-gate】`**: 模型输出绝不直转执行命令；由代码校验元素几何、阻挡遮罩与数据新鲜度；破坏性操作走人机确认。

## 架构职责分工

| 层级 | 承担方 | 职责边界 |
|---|---|---|
| **外环编排** | 主 Agent (Claude/Codex/OMP) | 目标分解、跨页面流程规划、失败重试决策、敏感提交人机确认 |
| **环境感知** | huashu-chrome | `snapshot`, `read_text`, `network`, `eval`（复用现有登录会话） |
| **内环微决策** | TypeSafe Jev | `Choice` 确定动作与元素映射，`Noul` 检验加载状态 |
| **文本生成** | magpie `group/group-daily` | 纯文本填充字段生成，轻量解耦 |
| **底层直写** | 页面原生 JS API | 腾讯企微表格 `SpreadsheetApp`、富文本编辑器原生 API |

## 文本助手（TYPE_TEXT）配置规范

- **选型**：`TEXT_MODEL=group/group-daily`（magpie 网关支持，且严格遵从 `{"text": "..."}` 结构）。
- **禁忌**：**禁止使用 `group/group-fast`**。该模型组底层路由至 Groq，Groq 不支持 `reasoning` 参数，必报 `400 "property 'reasoning' is unsupported"`。
- **参数**：调用请求传 `reasoning: {"effort": "low"}` 或 `{"enabled": False}`（或 `TEXT_MODEL_REASONING=none`）。
- **凭据注入**：OMP `.env` 包含字面 token（如 `$$...:L$$`），请在 Python 中用 `os.environ` 或代码显式注入，**勿用 `uv --env-file`**（uv 会错误展开内部变量）。

## 交互模式与决策范式

### 模式 A: 结构化表单批量填充（首选，极速闭环）

针对已知字段的静态/常规表单（约 3 秒完成 5 字段）：
1. **快照采集**：调用 huashu `snapshot` 拿到编号元素列表（`[e1]`, `[e2]`...）。
2. **一次性 Jev 语义映射**：单个 Jev 请求包含多个 Choice 问题，将所有待填字段名一次性映射为对应的元素 ref（走主备封装 `scripts/typesafe_jev.py`）：
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
3. **批量执行 `act`**：拿到 ref 后连续执行 `act({"do": "type", "ref": ref, "text": val})` 或 `act({"do": "select", "ref": ref, "value": val})`。
4. **校验回读**：通过 `eval` 运行 JS 提取 DOM `value` 或 `read_text` 验证填充结果。

### 模式 B: 投机式扇出动态步进（Speculative Fan-out，复杂探索/巡检）

针对分页巡检、多级菜单或未知流转路径：
一趟 Jev 请求同时决定「操作类别」与「各操作对应的候选目标」：
```python
from typesafe_jev import send_jev
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

### 模式 C: Canvas/纯视觉定位（Image + Box，Jev 1.14）

针对无 DOM 的 canvas/大渲染页面（企微表格、图表、扫描件）：把 huashu `screenshot` 截图当作图像资产发给 Jev，用 Box 问题定位目标，返回归一化包围盒（`left/right/top/bottom` ∈ [0,1]），再换算成页面/屏幕坐标执行点击。

启用注意项：
- **仅 Jev 1.14+** 支持 Box 问题；Jev 1.13 与 1.14 均接受图像输入。
- 每个含图像/Box 的请求必须携带 header `TypeSafe-Danger-Zone-Images: true`（默认关闭）。
- **非生产级（Dreamer-ready）**：格式与精度随版本变动，上线前需自测阈值。
- 图像资源必须全部被引用（state/instructions/criteria 中的字符串引用），未引用返回 400；重复引用会重复计费与放大请求体。
- 三请求体上限 32 MiB；base64 会膨胀约 1/3，优先 multipart 上传。
- Box 总是返回一个框（无"未找到"语义）：先加 Noul 判定目标是否存在，再按低 confidence 对框做 padding 或裁剪重问。

典型调用（Python 封装自动组装 multipart 与 danger zone header）：
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

注意事项（与模式 A/B 一致）：模型返回的是视觉框，仍需代码按确定性门禁转成 huashu `act` 坐标并复核；合成事件免疫站点（`isTrusted` 恒 false）即使定位正确也可能点击无效，优先底层 API/直写。

实测要点（2026-10-27 企微 sheet canvas）：
- 原尺寸 2560×1267 截图被拒（`Invalid image dimensions`）；缩至宽 1280（1280×633）后成功。截图先 `sips --resampleWidth 1280` 再上传。
- `model: "jev-latest"` 实际解析为 `jev-1.14.0`；一次请求带 `Noul`+`Box` 返回 `noul: 0.99`、box `left 0.02/right 0.96/top 0.11/bottom 0.99`（confidence 0.62）——与"网格占画布大部分"吻合，坐标换算可直供 huashu `act` x/y 点击。
- 计费：图像按 input token 计，与文本同价（$0.042/Mtok，output 免费）；实测 1280×633 一张 ≈ 2420 tokens ≈ $0.0001/次。同一图每被引用一次重复计一次，共享图放 `state` 一次。压缩文件字节不省 token——省 token 靠像素数（长边≤1568，短边≥280）。
- 格式仅收 PNG/JPEG（WebP/HEIC/GIF 被拒），JPEG 用标准 baseline。勿转 WebP。

## 主备 key 调用（仿 OMP judge 路由）

直连 `api.typesafe.ai/v1/systemone` 时，用本技能自带客户端 `scripts/typesafe_jev.py`，实现主备双 key + 失败回退：

- 主 key：`TYPESAFE_JEV_TOKEN`（= `TYPESAFE_API_KEY`，108 字符）。
- 备用 key：`TYPESAFE_JEV_TOKEN1`（107 字符）。
- 顺序：先主后备；前一候选失败（HTTP/网络/解析）才用下一候选，非轮换。
- 可选第三跳：`openrouter_fallback=True` 落到 `OPENROUTER_API_KEY`（对应 OMP `openrouter-judge/~typesafe/jev-latest`）。

```python
from typesafe_jev import send_jev
resp, key = send_jev(
    questions={"grid_visible": {"type": "noul", "instructions": "…"}},
    state={"shot": "S1"},
    model="jev-latest",
    images={"S1": ("shot.png", png_bytes, "image/png")},
)
# key == "primary" | "fallback" | "openrouter"
```

返回 `key` 标签供记录；任何 key 都返回 `jev-1.14.0`（`jev-latest` 别名）。两把 key 均已实测可用（2026-10-27）。

## 企业内部站点避坑指南 (Traps & Gotchas)

1. **Host Permission 报错**：
   - 现象：`Cannot access contents of the page. Extension manifest must request permission...`。
   - 修复：访问 `chrome://extensions` -> `huashu-chrome` 详细信息 -> 网站访问权限 -> 调整为“在所有网站上”。
2. **Canvas / 虚拟渲染页面**：
   - 现象：腾讯文档/企微在线表格在 DOM 树中只有 `<canvas>`，无普通表格标签，点击/输入事件可能失效。
   - 修复：数据读写优先使用宿主内部 API（如 `SpreadsheetApp`，参见 `wecom-sheet-internal-api` 技能）；外围工具栏与弹窗交互仍走 huashu `snapshot` + Jev。
3. **下拉选择 (Select) 定位失败**：
   - 原生 `<select>` 标签应直接用 ref 定位：`act({"do": "select", "ref": "eX", "value": "..."})`。避免使用按名称猜测点击选项的模糊模式。
4. **确定性路由**：
   - 凡有固定规则（如需求编号前缀、URL 域名分流、固定状态码）直接在 Python/Bash 代码中分支，禁止转入 Jev 模型浪费时间。
