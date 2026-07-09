> 历史设计草案。保留演进背景，不作为当前 shared-root / `llm_wiki` 文档模型的权威来源。当前系统边界以 [../../CONTEXT.md](../../CONTEXT.md) 和 [../reference.md](../reference.md) 为准。

你的主流程是对的，缺的不是更多笔记，而是一个**“从对话事件到可复用知识”的晋升层**。

我建议把它设计成：

```text
Agent 对话
  ↓
原始记录层：conversation / turn / tool result
  ↓
SQLite 事件账本：事实、决策、问题、证据、任务、候选洞察
  ↓
知识晋升层：去重、关联、检索、验证、分类
  ├─ 日报摘要
  ├─ 项目记录
  ├─ ADR
  ├─ KCS/SOP
  └─ 原子卡片
  ↓
Obsidian：可读、可编辑、可链接的知识视图
  ↓
Dataview 固定报表 + LLM 复盘叙事
```

核心原则：

> SQLite 是“事件与证据的系统记录”；Obsidian 是“人可阅读和复用的知识产品”；Dataview 是“展示与导航层”。

不要让 SQLite 和 Obsidian 双向争夺同一份内容的编辑权。

---

## 1. 四套方法嵌入位置

### KCS：放在“知识晋升与复用”层

KCS 不应理解为一类笔记，而是一条行为闭环：

```text
先检索 → 工作中捕获 → 复用时校验 → 更新或新建
```

每次你与 Agent 开始一个新任务，系统先从 SQLite + Obsidian 检索相关案例、指标口径、ADR、卡片和 SOP；命中后记录一次 `reuse`。之后 Agent 对话产生的新内容进入候选池，而不是直接变成正式知识。

KCS 强调知识应嵌入工作流中被复用、改进和创建；“复用即审查”尤其适合你的场景。([Consortium for Service Innovation][1])

建议知识状态统一为：

```yaml
status: candidate | wip | validated | deprecated | superseded
```

* `candidate`：Agent 从对话中抽出，但尚未确认。
* `wip`：已有结构，仍在使用和验证。
* `validated`：已被实际复用、验证或人工确认。
* `deprecated`：不再推荐，但保留历史。
* `superseded`：被新版本替代。

---

### PARA：只负责“知识放哪里”，不负责“它是什么”

建议目录：

```text
00 System/
   Daily/
   Reports/
   Templates/

10 Projects/
   商品清理实验/
   数据平台/

20 Areas/
   商品经营分析/
   门店增长/
   数据工程/

30 Resources/
   Cards/
   Methods/
   Metrics/
   Playbooks/
   Decisions/

40 Archives/
```

规则：

* 有明确结束时间的工作放 `Projects`。
* 长期职责或能力域放 `Areas`。
* 可跨项目复用的内容放 `Resources`。
* 结束项目和过时材料放 `Archives`。
* 日报、系统模板、报表放 `System`。

一条“门店实验平行趋势检查方法”不应该永久留在某个项目里；项目结束后，应晋升到 `Resources/Methods/`。

---

### ADR：只记录“真正影响后续选择的决策”

不要把所有讨论都记为 ADR。

触发 ADR 的条件：

```text
存在明确选择
+ 至少一个备选方案
+ 有后续影响、约束或代价
```

例如：

* 采用 DID 而不是直接同比；
* 数据平台先用 DuckDB + Parquet，而不是立即上数仓；
* 商品清理效果以“销售额 + 替代率 + 转化率”作为联合指标；
* Agent 总结只能引用带证据的事实。

ADR 自动生成草稿即可，不能自动变成“已接受”。

```yaml
type: adr
status: proposed | accepted | superseded
decision_date: 2026-07-04
project: "[[商品清理实验]]"
supersedes:
source_refs:
```

ADR 一旦 `accepted`，原则上不应改写；以后方案变化时，新建一条 ADR 并标注替代关系。这样才能保留“当时为什么这样做”。([martinfowler.com][2])

项目内 ADR 放在项目目录；跨项目、长期有效的决策放在 `Resources/Decisions/`。

---

### 卡片：只记录可跨场景复用的“原子结论”

卡片不等于摘要。

一张卡片应只表达一个可复用结论：

```markdown
---
type: card
status: validated
area: "[[商品经营分析]]"
reuse_count: 3
last_verified: 2026-07-04
source_refs:
---

# 线下门店实验不能只看销售额

## 结论
商品清理实验至少同时观察销售额、替代率、缺货率、客流和转化率。

## 适用条件
- 门店商品结构调整
- 存在明显替代购买
- 无法完全随机分组

## 反例
商品彼此独立、无替代关系时，替代率的重要性下降。

## 证据
- [[商品清理实验-2026Q2]]
- [[ADR-012-采用分层DID]]
```

卡片晋升条件建议设得严格：

* 同类问题至少出现两次；
* 已被其他项目实际复用；
* 有较高业务影响；
* 结论具备适用边界；
* 能关联到证据或数据。

否则，它只应留在日报或项目记录里。

---

## 2. SQLite 不要只存“总结”，要存证据链

建议最小数据模型：

```text
source_turn
  └─ 原始对话片段、角色、时间、内容哈希、来源链接

knowledge_item
  └─ 候选知识、ADR、卡片、SOP、指标口径、项目记录

claim
  └─ 一条可判断真伪的主张

evidence_span
  └─ claim 对应的原始 turn、引用范围、证据类型

relation
  └─ supports / contradicts / refines / supersedes / reused_by

materialization
  └─ 已写入哪个 Obsidian 文件、块 ID、最后同步哈希
```

最重要的是 `claim → evidence_span`。

Agent 说过的话不能天然算事实。建议为证据打类型：

```text
observed_data      数据或查询结果
external_source    外部引用或文档
human_decision     你确认过的决策
human_assertion    你提供的业务事实
agent_inference    Agent 推断
agent_suggestion   Agent 建议
```

只有前四类，才允许支撑 `validated` 卡片、正式 ADR 或周期报告中的事实结论。
`agent_inference` 和 `agent_suggestion` 可以进入候选池，但必须明确标注为推断或建议。

这会避免知识库逐步被 Agent 自己生成的内容循环污染。

---

## 3. 每次 Agent 对话后的流水线

```text
1. 保存原始对话
2. LLM 结构化抽取
3. 检索已有知识
4. 去重、链接、判断是否复用
5. 生成日报增量
6. 生成“待晋升队列”
7. 按规则创建 ADR / 卡片 / SOP 草稿
```

结构化抽取不要直接让模型写 Markdown，先要求 JSON：

```json
{
  "facts": [],
  "decisions": [],
  "questions": [],
  "open_loops": [],
  "insight_candidates": [],
  "reusable_assets": [],
  "risks": [],
  "source_refs": [],
  "promotion_suggestions": []
}
```

其中每条内容必须包含：

```json
{
  "title": "采用分层 DID 评估商品清理效果",
  "type": "decision",
  "confidence": 0.86,
  "evidence_turn_ids": ["conv_20260704_t18", "conv_20260704_t26"],
  "project_candidates": ["商品清理实验"],
  "suggested_destination": "adr"
}
```

然后再根据规则决定是否写入 Obsidian。

---

## 4. 日报只作为“当天工作记忆”，不要承载长期知识

日报推荐固定分区：

```markdown
---
type: daily
date: 2026-07-04
projects:
  - "[[商品清理实验]]"
areas:
  - "[[商品经营分析]]"
---

# 2026-07-04

## 今日工作

## 自动沉淀
<!-- KM:START -->
- 完成：
- 新发现：
- 已复用知识：
- ADR 候选：
- 卡片候选：
- 待验证：
- 未闭环问题：
<!-- KM:END -->

## 人工补充

## 明日推进
```

自动化脚本只更新 `KM:START` 到 `KM:END` 之间的区域，避免覆盖你的人工内容。

日报里的每一条应尽量链接到正式对象：

```markdown
- 已复用：[[线下门店实验不能只看销售额]]
- 新建 ADR 候选：[[ADR-012-采用分层DID]]
- 待验证：[[商品清理实验-平行趋势检查]]
```

---

## 5. 周、月、季、年报：Dataview 出“事实骨架”，Agent 写“复盘叙事”

Dataview 可以从 Markdown 的 YAML frontmatter 和 inline fields 建立索引，因此适合作为固定格式报表的展示层。([GitHub][3])

但不要让 Agent 直接读取一堆日报再自由总结。正确做法是：

```text
SQLite 聚合事实
      +
Dataview 汇总链接与状态
      ↓
生成 Review Packet
      ↓
Agent 撰写复盘
```

每个周期都生成一个机器可读的 `review_packet.json`，内容包括：

```text
- 完成项目与关键产出
- 新建 / 复用 / 更新 / 失效知识数
- ADR 数量与状态变化
- 高频问题与重复返工
- 未闭环问题
- 证据充分度
- 复用次数最高的卡片或 SOP
- 过期、低质量、冲突知识
```

Agent 的复盘输出固定分成：

```text
1. 已发生的事实
2. 主要成果与证据
3. 有效决策与无效决策
4. 重复摩擦与根因
5. 新形成的可复用知识
6. 仍不确定的假设
7. 下周期最重要的三个行动
```

并强制要求：

```text
事实 / 推断 / 建议分开写；
每个关键结论附知识条目或来源引用；
证据不足时明确写“无法判断”。
```

---

## 6. 最关键的 KCS 指标

周期复盘不要只看“写了多少笔记”，应看：

```text
reuse_count             被实际复用次数
reuse_to_update_rate    每次复用后被修订的比例
stale_ratio             超过验证周期未确认的知识比例
duplicate_rate          新建内容与旧内容重复比例
candidate_to_validated  候选知识晋升率
open_loop_age           未闭环问题的滞留时间
```

最有价值的指标是：

> 某条知识是否让你少重复做一次分析、少走一次弯路、少解释一次背景。

KCS 的重点不是积累内容，而是让已有知识在工作中被找到、被使用、被校正。([Consortium for Service Innovation][4])

---

## 7. 建议的最小落地版本

先只实现五件事：

1. 对话原文和 turn ID 写入 SQLite。
2. LLM 输出受 JSON Schema 约束的结构化抽取。
3. 每天自动更新日报的“自动沉淀”区块。
4. 对 `decision`、`reusable insight`、`open loop` 建立候选队列。
5. 周报从 SQLite 生成 Review Packet，再让 Agent 写复盘。

卡片自动晋升、向量检索、复杂知识图谱都可以后置。起步阶段用 SQLite 全文检索、标题、别名、标签和 Obsidian 链接，通常已经足够。

这套设计的本质是：

> 对话是原料；SQLite 是可追溯账本；日报是工作记忆；ADR 是决策记忆；卡片和 SOP 是长期能力；周期复盘负责让知识系统反过来改进你的工作方式。

[1]: https://library.serviceinnovation.org/KCS/KCS_v6/KCS_v6_Practices_Guide/030?utm_source=chatgpt.com "Section 2 The KCS Practices"
[2]: https://martinfowler.com/bliki/ArchitectureDecisionRecord.html?utm_source=chatgpt.com "Architecture Decision Record"
[3]: https://github.com/blacksmithgu/obsidian-dataview?utm_source=chatgpt.com "GitHub - blacksmithgu/obsidian-dataview: A data index and ..."
[4]: https://library.serviceinnovation.org/KCS/Knowledge-Centered_Success_Practices_Guide/402-Purpose_Behind_the_Practices?utm_source=chatgpt.com "The Purpose Behind the Practices"

**可以自动化，而且目录不需要频繁变化。**
真正需要人工的部分，应压缩到“确认高价值知识是否晋升”这一关，而不是每天整理文件。

建议把流程分成三层：

```text
全自动：采集、抽取、归类建议、写日报、生成周月季年报数据包
半自动：生成 ADR / 卡片 / SOP 草稿，等待确认
人工：确认真正重要的决策、方法论、长期结论
```

Obsidian 的 Markdown 本地文件适合当知识展示与编辑层；Dataview 可以基于 YAML/inline metadata 建索引、筛选、聚合，所以不需要频繁靠移动目录来组织内容。([黑匠工坊][1])

---

# 1. 自动化比例怎么划分

| 环节                |  是否自动化 | 建议                      |
| ----------------- | -----: | ----------------------- |
| Agent 对话入库 SQLite |   100% | 每个 turn 保留 ID、时间、来源、哈希  |
| 对话结构化抽取           |   100% | 抽取事实、决策、问题、待办、候选洞察      |
| 相似知识检索与去重         |    80% | 自动找相似卡片、ADR、项目记录        |
| 写入日报自动区块          |   100% | 只写指定标记区域，不碰人工内容         |
| 周/月/季/年事实汇总       |   100% | SQLite 聚合 + Dataview 查询 |
| 复盘初稿              |   100% | LLM 根据 Review Packet 输出 |
| ADR 草稿            |    90% | 自动生成，但不自动 `accepted`    |
| 卡片草稿              |    90% | 自动生成，但不自动 `validated`   |
| SOP / Playbook    |    70% | 自动起草，通常需要你改一次           |
| 正式知识晋升            | 不建议全自动 | 你只需“确认 / 退回 / 合并 / 忽略”  |

最重要的边界：

> Agent 可以自动“发现候选知识”，但不应自动把自己的推断升级为长期事实。

否则几个月后，知识库容易被“模型总结模型”的二手内容污染。

---

# 2. 目录结构应该稳定，不要按日报频繁搬文件

不要让自动化脚本根据内容不断移动文件。

建议采用：**目录负责大类，Metadata 负责归属、状态和关联。**

```text
00_System/
  Templates/
  Scripts/
  Dashboards/
  Reports/

10_Daily/
  2026/
    2026-07-04.md

20_Projects/
  PRJ-2026-001-商品清理实验/
  PRJ-2026-002-数据分析平台/

30_Areas/
  商品经营分析.md
  门店增长.md
  数据工程.md

40_Knowledge/
  Cards/
  ADR/
  Metrics/
  Methods/
  Playbooks/

50_Inbox/
  Candidates/
  Review-Queue/

90_Archive/
```

目录基本只在这几种情况下变化：

1. 新建项目；
2. 项目结束，整体移入 Archive；
3. 新增一种长期知识类型，例如 `Metrics`、`Methods`；
4. 清理废弃草稿。

日常不会移动文件。真正的归属写在 Frontmatter：

```yaml
---
id: K-20260704-001
type: card
status: candidate
projects:
  - "[[PRJ-2026-001-商品清理实验]]"
areas:
  - "[[商品经营分析]]"
topics:
  - 因果推断
  - 门店实验
source_refs:
  - conv_20260704_018
  - conv_20260704_026
created: 2026-07-04
last_verified:
reuse_count: 0
---
```

这样 Dataview 按 `projects`、`areas`、`type`、`status` 聚合；目录不再承担复杂分类责任。Dataview 本身就是围绕笔记 metadata 建立实时索引和查询的。([黑匠工坊][1])

---

# 3. 关键设计：文件路径不是主键，`id` 才是主键

不要让 SQLite 用 Obsidian 文件路径作为唯一身份。

推荐：

```text
SQLite 主键：knowledge_item.id
Obsidian 主键：YAML 中的 id
文件路径：可变化的展示位置
```

例如：

```text
K-20260704-001
ADR-2026-012
PRJ-2026-001
```

SQLite 里记录：

```text
knowledge_item
- id
- type
- status
- title
- obsidian_path
- content_hash
- created_at
- updated_at
```

即使未来你把：

```text
40_Knowledge/Cards/线下门店实验不能只看销售额.md
```

移动到：

```text
40_Knowledge/Methods/门店实验/线下门店实验不能只看销售额.md
```

SQLite 只更新 `obsidian_path`，知识身份和关联都不受影响。

---

# 4. 建议采用“候选队列”，而不是让 Agent 直接正式落盘

这是减少人工维护的关键。

```text
Agent 对话
  ↓
SQLite 结构化抽取
  ↓
自动去重与相似检索
  ↓
50_Inbox/Candidates/
  ├─ ADR 候选
  ├─ 卡片候选
  ├─ SOP 候选
  └─ 待验证问题
  ↓
你每周集中处理一次
  ├─ 确认 → 移入 40_Knowledge/
  ├─ 合并 → 链接到已有知识
  ├─ 忽略 → 标记 dismissed
  └─ 退回 → 保持 candidate
```

人工操作应是非常轻的“审批”，而不是重新写笔记。

例如每周只处理一张 Dataview 页面：

```dataview
TABLE type, title, confidence, created, source_refs
FROM "50_Inbox/Candidates"
WHERE status = "candidate"
SORT confidence DESC, created DESC
```

Dataview 支持根据字段列出、过滤、排序和分组笔记，因此这种候选队列很适合用它做视图。([黑匠工坊][1])

---

# 5. 日报、周报、月报分别承担什么

## 日报：100% 自动生成

日报只承接“当天的工作记忆”。

```markdown
## 自动沉淀
<!-- AUTO:START -->

### 完成
- …

### 关键发现
- …

### 已复用知识
- [[K-20260618-门店实验指标拆解]]

### ADR 候选
- [[ADR-C-20260704-采用分层DID]]

### 卡片候选
- [[K-C-20260704-销售额不是唯一结果指标]]

### 未闭环问题
- …

<!-- AUTO:END -->
```

脚本只更新 `AUTO:START` 和 `AUTO:END` 之间，不覆盖你的手写内容。

---

## 周报：自动汇总 + Agent 复盘

周报不直接扫描所有日报文本，而是读取 SQLite 聚合的 `review_packet`：

```json
{
  "period": "2026-W27",
  "projects": [],
  "completed_items": [],
  "reused_knowledge": [],
  "new_candidates": [],
  "accepted_adrs": [],
  "open_loops": [],
  "stale_knowledge": [],
  "evidence_coverage": {}
}
```

Agent 再根据该数据包生成：

```text
- 本周事实
- 关键产出
- 有效方法
- 重复摩擦
- 错误或无效决策
- 待验证假设
- 下周优先级
```

这样 Agent 不是“凭感觉复盘”，而是在已有结构化事实之上写叙事。

---

## 月、季、年报：看趋势，而不是重复周报

周期越长，越应该关注：

```text
知识复用率
候选知识晋升率
ADR 后续是否被推翻
高频重复问题
未闭环事项老化
哪些模板、方法、卡片最有价值
哪些知识长期无人复用，应废弃或合并
```

不要让月报变成“把四周日报再总结一遍”。

---

# 6. 人工介入应该控制在三件事

建议你每周只做这三类人工动作：

### ① 确认高影响决策

例如：

* 方法论选择；
* 技术架构选择；
* 指标口径变更；
* 项目方向调整；
* 有成本或风险的业务决策。

这些进入 ADR。

### ② 确认可跨项目复用的洞察

例如：

* “线下门店实验必须拆解替代购买”
* “某类 SQL 查询在 MaxCompute 下容易导致资源失控”
* “某类业务指标不应作为核心判断指标”

这些进入卡片、方法或 SOP。

### ③ 清理异常候选

例如：

* 与已有知识重复；
* 证据不足；
* 只是一次性背景；
* Agent 幻觉或未经确认的判断；
* 已过期的信息。

其他都让系统自动做。

---

# 7. 一个适合你的自动化规则表

```text
decision
  → 自动建 ADR 草稿
  → 只有人工确认后才 accepted

insight_candidate
  → 相似知识命中 < 0.85
  → 且出现次数 >= 2 或业务影响 >= 中
  → 自动建 Card 草稿

reusable_asset
  → SQL / Notebook / 模板 / 指标口径
  → 自动建资源索引页
  → 人工补充使用条件

open_loop
  → 自动加入日报、周报
  → 超过 14 天未关闭则标记 overdue

knowledge_reuse
  → 自动 +1 reuse_count
  → 若距离 last_verified 超过 90 天，提示复核

project_closed
  → 自动生成项目复盘候选
  → 人工确认后移入 Archive
```

---

# 8. 最少人工的成熟形态

最终你每天不需要整理目录，也不需要手工写很多结构化笔记。

你的动作应该变成：

```text
日常：正常和 Agent 工作
每天：看一眼日报自动沉淀
每周：审批候选 ADR / 卡片 / SOP
每月：阅读自动生成的复盘，修正关键判断
项目结束：确认项目复盘和归档
```

也就是：

> 自动化负责捕获、整理、关联和起草；你只负责判断什么值得成为长期知识。

这套方式可以让目录长期稳定，人工维护集中在“高价值判断”上，而不是文件整理上。

[1]: https://blacksmithgu.github.io/obsidian-dataview/?utm_source=chatgpt.com "Dataview"
