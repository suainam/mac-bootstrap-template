---
name: franchise-store-sankey-analysis
description: 用户要 franchise-store 目录内/目录外流转分析、两期 Sankey 图、或基于新数据块重生成汇报页时使用。
---

# 加盟店桑基图分析

用于加盟店目录分析及相邻两期流转分析的可复用 Sankey HTML / SVG 与汇报 HTML。

## 快速开始

1. 先决定这次跑哪条分支。
分支 A：只做数据分析 / 口径解释。
分支 B：只做 Sankey SVG / HTML。
分支 C：输出完整汇报页。
完成标准： 你已经知道这次需要哪些产物，因此只加载该分支需要的 references。

2. 先锁定最新数据块。
尤其当源文件同时混有旧例子和新的 `现在的数据如下` 区块时，必须先认定哪个区块是当前真值。
完成标准： 你知道当前数据块是哪一段，也知道总结果是正还是负。

3. 只有需要用户可见文案时才读 wording。
当用户要汇报文案、桑基图解释、结论措辞时，打开 [references/WORDING_TEMPLATES.md](references/WORDING_TEMPLATES.md)。
完成标准： 你能复用批准参考文案的结构和节奏，而不是临时发明新说法。

4. 只有输入口径或 bridge 逻辑不清时才读数据合同。
当指标映射、bridge 公式、正负号处理不清时，打开 [references/DATA_INPUT_CONTRACT.md](references/DATA_INPUT_CONTRACT.md) 和 [REFERENCE.md](REFERENCE.md)。
完成标准： 页面里每个可见指标都有来源、有含义、有正负方向。

5. 画图前先建 ledger。
凡是输出图，尤其是带用户可见财务数字的图，都要打开 [references/SANKEY_QA_CHECKLIST.md](references/SANKEY_QA_CHECKLIST.md)。
完成标准： 每个节点总额、每条 flow 数值、每个 bridge 公式都先闭环，再谈 SVG 完成。

6. 画图前先锁视觉合同。
凡是新建或修改 Sankey SVG / HTML，都要打开 [references/SANKEY_STYLE_CONTRACT.md](references/SANKEY_STYLE_CONTRACT.md)。
完成标准： 图遵守批准参考图的双列布局、标签位置、标签词表、单位策略、浏览器适配规则。

7. 只有需要 HTML 时才复用骨架。
做 graph/report HTML 时，打开 [templates/report_shell.html](templates/report_shell.html)、[templates/report_style.css](templates/report_style.css)、[templates/graph_style.css](templates/graph_style.css)。
完成标准： 汇报页 section 顺序稳定，graph/report 样式一致。

8. 结束前跑最终总闸门。
凡是输出 graph/report，都要核对数字一致、文案一致、section 顺序一致、标签词表一致、SVG 文本无碰撞。
完成标准： 最新数据块已锁定、正负号无误、ledger 已闭环、graph/report 数字一致、`汰换` 和 `%` 用词一致、标签词表对齐最近批准参考图、SVG 通过碰撞检查和浏览器检查。

## 硬约束

- Two-layer Sankey only unless the user asks otherwise
- Prefer `汰换`; avoid `损耗`
- Prefer `%`; avoid `pct`
- Explain `存量盘` first, then positive structure actions, then `汰换`, then the net result
- If total result is negative, do not reuse old positive-conclusion wording
- Labels belong beside the relevant node/flow endpoint, not on top of Sankey bands, unless the user explicitly asks for inline labels
- 对 franchise-store 图，flow label 必须继承最近批准参考图的业务词表；如果参考图用 `稳定目录内`、`稳定目录外`、`目录外转目录内`、`目录内转目录外`，就不要静默缩成 `稳定内`、`稳定外`、`外转内`、`内转外`
- Never ship a graph from visual judgment alone; run a numeric ledger and a text-collision check first
- Preserve the stable visual contract; do not invent a new Sankey style while fixing labels or data

## 参考索引

- Metric defaults and formulas: [REFERENCE.md](REFERENCE.md)
- Input contract: [references/DATA_INPUT_CONTRACT.md](references/DATA_INPUT_CONTRACT.md)
- Example wording: [references/WORDING_TEMPLATES.md](references/WORDING_TEMPLATES.md)
- Example source section from `data_0617.md`: [references/REFERENCE_DATA_EXAMPLE.md](references/REFERENCE_DATA_EXAMPLE.md)
- Sankey QA checklist: [references/SANKEY_QA_CHECKLIST.md](references/SANKEY_QA_CHECKLIST.md)
- Sankey style contract: [references/SANKEY_STYLE_CONTRACT.md](references/SANKEY_STYLE_CONTRACT.md)
- Report shell: [templates/report_shell.html](templates/report_shell.html)
- Report CSS: [templates/report_style.css](templates/report_style.css)
- Graph CSS: [templates/graph_style.css](templates/graph_style.css)
