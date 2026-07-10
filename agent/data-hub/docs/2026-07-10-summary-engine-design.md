# Data Hub Structured Summary Engine Design

日期：2026-07-10  
状态：已批准，待实施  
契约版本：`summary-v1`  
维度版本：`dimensions-v1`

## 1. 背景与问题

现行 `70_Summaries` 生成链已经完成 Daily-first 与周期层级切换，但输出仍不是有效的知识总结：

- Daily 主要枚举检索结果，并留下“待 llm_filter 归纳”等占位内容。
- Weekly 会把上一层 Daily Summary 正文整段嵌入，造成信息重复；文件覆盖虽然幂等，内容表达并不幂等。
- `period_summary.py` 同时承担检索、选择、渲染和 lineage，缺少结构化中间契约。
- `daily-summary.md` 仍输出单行 Markdown 与旧 `#绩效-*` 标签；`weekly-summary.md` 仍面向自由列表输出。
- `chat_review.md` 已能过滤聊天噪声，但没有与周期总结的证据契约对齐。
- lifecycle 已使用 `period_summary.py`，旧 `scripts/daily_summary.py`、旧 stage、skills 和测试仍保留另一条路径。
- 现有 llm_wiki client 使用 search / files / graph / reviews，尚未利用 `/chat` 的引用式深度分析。

本设计建立一个单一、结构化、证据优先的 Summary Engine。目标不是修补旧输出，而是删除双路径，让每个运行时文件都有唯一职责。

## 2. 目标

1. Daily 同时服务工作进展与知识洞察，篇幅 800–1200 中文字。
2. Weekly 是 1200–1800 字的跨日决策复盘，不复制 Daily 正文。
3. 每个原子条目具有类型、结论、价值、证据、置信度与条目级能力维度。
4. 知识洞察严格筛选 2–4 条；没有合格内容时允许为零。
5. SQLite 保存原子条目、维度、来源与 lineage；Markdown 只做人类阅读投影。
6. 使用 llm_wiki Hybrid Search 与 Deep Chat 获得带引用的知识上下文。
7. 生成、校验、存储、渲染边界独立，可单测、可重试、可审计。
8. workflow、schedule、skills 只保留一个正式入口。
9. 连续重跑不增加条目、维度、来源或 lineage，不改变 Markdown 内容。

## 3. 非目标

- 不保留旧 `daily_summary.py` 的运行时兼容入口。
- 不为旧 stage、旧 prompt 输出或旧自由 Markdown 建 facade。
- 不让 llm_wiki 写 data-hub SQLite、`70_Summaries` 或 accepted state。
- 不让 Summary 自动晋升到 `40_Knowledge` 或回流 llm_wiki。
- 不把 `70_Summaries` 作为自己的检索输入。
- 不要求每天强行产生知识洞察或能力维度。
- 不在 private prompt 中复制或覆盖公共行为契约。

## 4. 设计原则

### 4.1 证据先于叙事

每个正文条目必须引用至少一个 source ref。无证据内容不进入 Summary。

### 4.2 结构先于 Markdown

LLM 只返回符合 JSON Schema 的结构化对象。Markdown renderer 不调用 LLM，也不推断内容。

### 4.3 SQLite 是 canonical state

条目、标签、来源、lineage 与生成状态以 SQLite 为准。Markdown 可删除后重建，不承担状态真相。

### 4.4 高层只聚合，不复制

Weekly 读取 Daily 原子条目并生成跨日结论；Monthly 读取 Weekly，以此类推。高层 Markdown 只使用 wikilink 引用低层产物。

### 4.5 没有价值胜过填充内容

没有合格洞察时明确输出“今日无新增高价值洞察”。不得使用“待归纳”“暂无建议”等占位句伪装结果。

### 4.6 不以兼容制造第二架构

调用方迁移完成后删除旧入口、旧 stage 与对应测试。历史文档可保留，但必须明确标记非运行时事实。

## 5. 单一执行链

```text
knowledge-lifecycle-manager/manager.py
  -> knowledge_workflows.py
  -> period_summary.py
     -> summary_evidence.py
        -> local Daily / Git / SQLite records / candidates
        -> llm_wiki search + deep chat
     -> summary_synthesis.py
        -> chat_review.md (upstream chat evidence only)
        -> daily-summary.md | weekly-summary.md
     -> summary_contracts.py
        -> summary-output.schema.json
        -> summary-dimensions.v1.json
     -> summary_store.py
        -> SQLite transaction
     -> summary_renderer.py
        -> atomic Markdown projection
```

执行顺序固定：

1. 确定 period 与上一层完整性。
2. 收集确定性证据并去重。
3. 调用 llm_wiki 获取相关页面、关联与引用式分析。
4. 调用 level prompt 生成结构化 JSON。
5. 校验 schema、维度、证据、数量与长度预算。
6. 创建或复用 `staged` revision，在一个 SQLite transaction 内写入候选 items、dimensions、sources 与 lineage；不切换 current revision。
7. 从 staged revision 渲染、校验 Markdown 临时文件。
8. atomic replace 正式文件；frontmatter 写入 `revision_id` 与 `input_digest`。
9. 在第二个 SQLite transaction 内把 revision 标记为 `published`，并切换 logical summary 的 `current_revision_id`。
10. 若进程在步骤 8–9 之间退出，下一次运行根据正式文件中的 `revision_id` 完成恢复；失败时不得让旧 DB revision 与新文件永久分叉。

## 6. 模块职责

### 6.1 `knowledge_workflows.py`

保留：

- 五个 `build_*_summary` workflow 的注册。
- `StageSpec` 构造。
- durable run / resume / retry 接入。

删除：

- `daily_summary_stage()`。
- `materialization_stage()`。
- 仅用于以上旧 stage 的测试。

它不收集证据、不调用 LLM、不渲染 Markdown。

### 6.2 `period_summary.py`

重写为薄 orchestrator：解析 period、检查上一层、串联 evidence/synthesis/contracts/store/renderer。现有检索枚举与 Markdown 拼接逻辑全部移出。

### 6.3 `summary_evidence.py`

职责：

- 收集 period 内的 Daily、Git、SQLite knowledge records、open candidates。
- 调用 llm_wiki Hybrid Search。
- 调用 llm_wiki `/chat`，使用 `mode: deep` 获取引用式分析。
- 统一 source refs，过滤 `70_Summaries/`。
- 按 source identity 与内容 fingerprint 去重。
- 输出 EvidencePacket，不输出 Summary 文案。

### 6.4 `summary_synthesis.py`

职责：

- 根据 level 选择 prompt。
- 注入 EvidencePacket、taxonomy 与 output schema。
- 调用 LLM backend。
- 解析纯 JSON；不接受 fenced Markdown 或混合解释。
- schema 失败时携带错误重试一次。

### 6.5 `summary_contracts.py`

职责：

- 加载并版本检查 JSON Schema 与 taxonomy。
- 加载并版本检查可执行的 evidence sufficiency policy。
- 校验 item type、维度白名单、标签数量、证据、置信度。
- 校验 Daily/Weekly 的条目结构与长度预算。
- 计算规范化 evidence group IDs、input digest 与 revision/item IDs。
- 拒绝占位内容、裸路径与嵌入式低层正文。

### 6.6 `summary_store.py`

保留现有 summary run/lineage 职责；扩展原子条目、维度、来源的 transaction upsert。所有写入由它独占。

### 6.7 `summary_renderer.py`

职责：

- 从已校验对象生成固定 Markdown。
- 生成 Obsidian wikilinks。
- 保证标题、空行、列表、表格、frontmatter 稳定。
- 生成临时文件并 atomic replace。

renderer 不读取原始来源，不调用数据库或 LLM。

### 6.8 `scripts/build_period_summary.py`

保留为 CLI adapter；由 workflow stage 实际调用。只解析参数、调用 orchestrator、打印产物路径。

### 6.9 `scripts/daily_summary.py`

删除。迁移所有 schedule、skills、tests 后不保留兼容 wrapper。

## 7. llm_wiki 集成

扩展 `LlmWikiClient`：

```python
chat(message: str, *, mode: str = "deep") -> dict
```

边界：

- `search`：召回 Wiki 与 Source 证据。
- `read_file`：按需读取高相关页面。
- `graph`：提供关联页面与跨主题连接。
- `reviews`：提供未解决的人类判断项。
- `chat(mode="deep")`：回答聚焦问题，返回引用、用量和工具事件。

data-hub 只读这些结果。Deep Chat 输出作为 evidence analysis，不直接作为最终 Markdown，不直接决定 accepted state 或最终维度。

llm_wiki 不可用时：

- 本地证据足够：允许生成工作进展；知识洞察可为零，run 标记 `degraded`。
- 本地证据不足：workflow 失败，不写新 Markdown。

## 8. Prompt 整合

目录：

```text
prompts/
├── chat_review.md
├── daily-summary.md
├── weekly-summary.md
├── higher-period-summary.md
├── summary-evidence-research.md
├── summary-output.schema.json
├── summary-dimensions.v1.json
└── summary-policy.v1.json
```

所有 Summary 契约资产使用 `contract_version: summary-v1`。版本不一致时 workflow 失败。

### 8.1 `chat_review.md`

只负责上游聊天证据清洗：

- 保留现有噪声过滤、长期知识判断、直接陈述知识规则。
- 输出 `evidence_refs`。
- 输出最多两个 `dimension_hints`，仅作下游提示。
- 不生成 Daily/Weekly Markdown。
- 不拥有最终维度决定。

### 8.2 `daily-summary.md`

改为 Daily 原子条目生成 prompt：

- 删除旧 `#绩效-*` / `#成长-*` / `#复盘-*` 标签。
- 删除“每条一行 Markdown”输出。
- 同时生成工作进展与知识洞察。
- 知识洞察只保留满足“新信息 + 有证据 + 可复用或影响决策”的 2–4 条；允许零条。
- 输出 JSON，最终 Markdown 由 renderer 生成。

### 8.3 `weekly-summary.md`

保留并强化：同类合并、跨日推进、保守措辞、禁止虚构。调整为：

- 输入 SQLite Daily items，而非 Daily Markdown 全文。
- 输出跨日 outcome/decision/risk/action/insight JSON。
- 使用 `supporting_item_ids` 与 `daily_refs`。
- 不输出或复制 Daily 正文。
- 维度基于周级结论重判，不简单合并 Daily 标签。

### 8.4 `higher-period-summary.md`

Monthly、Quarterly、Yearly 共用一个 higher-period prompt，但使用按 level 判别的 schema：

- Monthly 读取本月已发布 Weekly revisions。
- Quarterly 读取本季已发布 Monthly revisions。
- Yearly 读取本年已发布 Quarterly revisions。
- 只生成跨周期成果、决策演进、风险趋势、能力维度变化与下一周期重点。
- 每个 item 必须带 `supporting_item_ids` 与上一层 wikilinks；不复制上一层正文。

### 8.5 `summary-evidence-research.md`

用于 llm_wiki Deep Chat：

- 只请求带引用的知识发现、矛盾、跨来源关联与缺口。
- 不生成最终 Summary。
- 不决定标签。
- 不输出没有来源的推断。

### 8.6 Prompt 权威来源

Data Hub 行为 prompt、schema、taxonomy 只从 public template 加载。现有 `load_prompt_template()` 的 private 整文件覆盖能力从这条链移除；private runtime 只允许配置 backend、model、token、篇幅等参数。这样避免聊天清洗或 Summary 行为静默偏离公共 validator。

## 9. 结构化输出契约

核心对象：

```json
{
  "contract_version": "summary-v1",
  "taxonomy_version": "dimensions-v1",
  "policy_version": "summary-policy-v1",
  "level": "daily",
  "period": "2026-07-10",
  "headline": "完成 Summary Engine 设计收敛并明确条目级标签契约。",
  "items": [
    {
      "item_type": "decision",
      "title": "统一 Summary 生成入口",
      "conclusion": "Daily 至 Yearly 全部通过 lifecycle manager 调度。",
      "value": "消除旧脚本和现行 workflow 漂移。",
      "dimensions": ["计划组织", "专业知识"],
      "evidence_group_ids": ["evg_781c2c"],
      "confidence": 0.95
    }
  ]
}
```

允许的 `item_type`：

- `outcome`
- `decision`
- `risk`
- `action`
- `insight`

`summary-output.schema.json` 使用 `level` discriminator。Daily、Weekly、Higher Period 分支字段明确：

- Daily item：`item_type`、`title`、`conclusion`、`value`、`dimensions`、`evidence_group_ids`、`confidence`。
- Weekly item：Daily 字段 + 可选 `trend` + 必需 `supporting_item_ids`、`lower_summary_refs`。
- Monthly/Quarterly/Yearly item：Weekly 字段 + 必需 `period_change`；`lower_summary_refs` 必须指向直接上一层。

每个 item：

- 必须有 title、conclusion、value、evidence group IDs、confidence。
- 最多两个 dimensions。
- 至少一个 evidence group；每个 group 必须能展开为至少一个 canonical source ref。
- `insight` 必须明确新信息与复用/决策价值。
- 禁止使用“待归纳”“暂无建议”“继续推进”等无对象占位表述。

## 10. 条目级维度 taxonomy v1

维度基于“该条内容通过什么能力创造价值”，不是根据来源、项目名或标题关键词机械匹配。

### 10.1 计划组织

定义：围绕目标拆解、优先级、资源、节奏、流程、风险和交付进行组织。

包含：计划、里程碑、优先级、职责边界、依赖、风险、时间与资源协调。

示例：

- 将 Daily/Weekly 统一纳入 lifecycle manager。
- 明确 template 与 private 的修改边界。
- 为季度项目拆分里程碑与验收条件。

排除：

- 单纯讨论或同步信息，归入沟通协作。
- 单纯技术结论，归入专业知识。

### 10.2 创新

定义：提出、验证或落地新的方法、工具、组合方式或显著改进。

包含：新方案、实验、原型、显著质量/成本改进、跨领域组合。

示例：

- 引入 llm_wiki Deep Chat 做引用式知识分析。
- 用结构化 JSON 中间契约替代自由 Markdown。
- 新增 input digest + immutable revision 实现运行级幂等。

排除：

- 常规修复或重构通常归入专业知识。
- 未验证且未说明价值的想法不打创新标签。

### 10.3 沟通协作

定义：通过信息交换、共识建立、反馈或协同推动多人工作。

包含：需求对齐、方案评审、跨团队协作、反馈闭环、职责澄清。

示例：

- 与使用者确认 Daily 与 Weekly 的内容目标。
- 通过评审确定 Summary 标签契约。
- 协调数据与业务团队统一指标口径。

排除：

- 个人整理计划归入计划组织。
- 没有协作行为的普通文档写作不打标签。

### 10.4 专业知识

定义：形成或应用可验证、可复用的技术、业务或领域知识。

包含：技术原理、业务规则、数据口径、根因分析、架构判断、操作经验。

示例：

- 确认 Weekly 重复来自正文嵌入，而不是文件追加。
- 明确 SQLite 是 canonical state，Markdown 是投影。
- 识别 llm_wiki Hybrid Search 与 Deep Chat 的能力边界。

排除：

- 只记录完成任务而没有方法或结论时不打标签。
- 个人认知变化优先归入学习成长。

### 10.5 学习成长

定义：通过复盘、反馈或实践形成个人/团队能力提升和认知修正。

包含：错误复盘、认知变化、能力短板、行为原则、学习计划。

示例：

- 认识到文件写入幂等不等于信息表达不重复。
- 形成“先结构化证据，再生成叙事”的原则。
- 发现旧测试会固化已废弃行为，后续先验证现行入口。

排除：

- 客观技术知识本身归入专业知识。
- 没有认知变化的普通工作记录不打标签。

### 10.6 冲突规则

- 每条最多一个主维度、一个辅助维度。
- 主维度表示主要价值来源；辅助维度表示促成机制。
- 建立流程：计划组织，可辅以沟通协作。
- 发明并验证新技术方案：创新，可辅以专业知识。
- 解决已知技术问题：专业知识。
- 通过评审形成共识：沟通协作，可辅以计划组织。
- 从失败形成新原则：学习成长，可辅以专业知识。
- 只是完成普通任务：不打维度。

## 11. SQLite 数据模型

### 11.1 `summaries`

```text
summary_id            TEXT PRIMARY KEY
summary_level         TEXT NOT NULL
period_id             TEXT NOT NULL
current_revision_id   TEXT
created_at            TEXT NOT NULL
updated_at            TEXT NOT NULL
UNIQUE(summary_level, period_id)
```

`summary_id` 是 logical summary identity，稳定对应一个 level + period，不等于 workflow run 或 generation attempt。

### 11.2 `summary_revisions`

```text
revision_id           TEXT PRIMARY KEY
summary_id            TEXT NOT NULL REFERENCES summaries(summary_id)
input_digest          TEXT NOT NULL
contract_version      TEXT NOT NULL
taxonomy_version      TEXT NOT NULL
policy_version        TEXT NOT NULL
publish_status        TEXT NOT NULL  -- staged | file_published | published | failed
quality_status        TEXT NOT NULL  -- complete | degraded
artifact_path         TEXT NOT NULL
artifact_hash         TEXT
metadata_json         TEXT NOT NULL
created_at            TEXT NOT NULL
published_at          TEXT
UNIQUE(summary_id, input_digest)
```

`revision_id` 是可审计生成版本；workflow run/attempt 通过 metadata 或现有 run tables 引用它，不覆盖 logical identity。

### 11.3 `summary_items`

```text
item_id               TEXT PRIMARY KEY
revision_id           TEXT NOT NULL REFERENCES summary_revisions(revision_id)
section_key           TEXT NOT NULL
ordinal               INTEGER NOT NULL
item_type             TEXT NOT NULL
title                 TEXT NOT NULL
conclusion            TEXT NOT NULL
value                  TEXT NOT NULL
trend                  TEXT
period_change          TEXT
confidence             REAL NOT NULL
UNIQUE(revision_id, section_key, ordinal)
```

item identity 只在 immutable revision 内稳定。新输入产生新 revision；不尝试用 LLM 文案构造跨 revision 主键。

### 11.4 `summary_item_dimensions`

```text
item_id              TEXT NOT NULL
dimension            TEXT NOT NULL
position             INTEGER NOT NULL
taxonomy_version     TEXT NOT NULL
PRIMARY KEY(item_id, dimension)
CHECK(position IN (1, 2))
```

`position=1` 是主维度，`position=2` 是辅助维度。

### 11.5 `summary_evidence_groups` 与来源

```text
summary_evidence_groups
- evidence_group_id
- revision_id
- evidence_kind
- normalized_payload_json
- PRIMARY KEY(revision_id, evidence_group_id)

summary_evidence_sources
- revision_id
- evidence_group_id
- source_kind
- source_ref
- source_claim_id
- PRIMARY KEY(revision_id, evidence_group_id, source_ref, source_claim_id)
```

`evidence_group_id` 完全由代码根据规范化 source refs、claim IDs 与 period 计算，不由 LLM 生成。

### 11.6 item 与证据关系

```text
summary_item_evidence
- item_id
- evidence_group_id
- PRIMARY KEY(item_id, evidence_group_id)
```

### 11.7 高层支持关系

```text
summary_item_support
- item_id
- supporting_item_id
- PRIMARY KEY(item_id, supporting_item_id)
```

Weekly/Monthly 等高层 item 通过该表引用上一层 item，不复制正文。

## 12. 幂等与更新语义

每次 run 先构造规范化 EvidencePacket。`input_digest` 完全由代码计算：

```text
hash(
  level + period
  + canonical EvidencePacket JSON
  + prompt hash
  + schema hash
  + taxonomy hash
  + policy hash
  + backend kind + model
)
```

规则：

- 当前 published revision 的 `input_digest` 相同：直接返回现有 artifact，不再次调用 LLM。
- 相同 logical summary + input digest 只存在一个 revision。
- LLM 只能引用代码生成的 evidence group IDs；无法制造 identity。
- item 按 validator 的固定 section order 与 deterministic sort 分配 ordinal，ID 为 `hash(revision_id + section_key + ordinal)`。
- 新输入产生新 immutable revision；旧 revision 保留审计，不混入新 revision 的当前投影。
- 相同输入连续运行两次：revision、items、dimensions、sources 行数与 Markdown hash 完全不变。

### 12.1 可恢复发布协议

1. DB 写 staged revision 与完整候选 rows；logical summary 仍指向旧 current revision。
2. renderer 从 staged revision 生成并校验 temp artifact。
3. atomic replace 正式文件；文件 frontmatter 包含 `revision_id`、`input_digest`、`artifact_hash`。
4. DB 把 revision 改为 `file_published`，核对正式文件 hash。
5. DB transaction 把 revision 改为 `published` 并切换 `current_revision_id`。

恢复规则：

- staged + 无正式文件 revision marker：重新渲染/发布。
- staged/file_published + 正式文件 marker/hash 匹配：完成 DB finalize。
- 正式文件 marker 指向未知 revision：拒绝覆盖并报错。
- published revision 与正式文件 hash 不符：健康检查失败，使用 DB payload 重建投影。

测试必须覆盖 DB staged 后文件失败、文件 replace 后 finalize 失败两个 crash window。

## 13. Markdown 投影

### 13.1 Daily

篇幅：800–1200 中文字。

```markdown
---
type: summary
summary_level: daily
period: 2026-07-10
status: draft
generated_by: data-hub
indexing: excluded
promotion_status: not_reviewed
contract_version: summary-v1
taxonomy_version: dimensions-v1
---

# 2026-07-10 Daily Summary

## 今日结论

2–3 句最重要产出、变化与判断。

## 工作进展

### 统一 Summary 生成入口

- **类型**：决定
- **维度**：`计划组织` `专业知识`
- **结论**：Daily 至 Yearly 全部通过 lifecycle manager 调度。
- **价值**：消除旧脚本与现行 workflow 漂移。
- **证据**：[[相关 ADR]]、`commit:abc123`

## 风险与下一步

- [ ] 明确动作、责任或触发条件。

## 知识洞察

### 高层总结不能复制低层正文

- **类型**：洞察
- **维度**：`学习成长` `计划组织`
- **新信息**：Weekly 应聚合跨日变化，不复制 Daily 正文。
- **价值**：同样适用于 Monthly、Quarterly、Yearly。
- **证据**：[[10_Periodic/Daily/2026-07-10|原始日报]]、`record:rec_123`
- **置信度**：高

## 来源

- [[10_Periodic/Daily/2026-07-10|原始日报]]
```

无合格洞察：

```markdown
> 今日无新增高价值洞察。
```

### 13.2 Weekly

篇幅：1200–1800 中文字。

固定结构：

```text
本周结论
关键成果
决策与变化
跨日趋势
未解风险
下周重点
知识演进
本周能力维度
Daily 索引
```

Daily 索引示例：

```markdown
- [[70_Summaries/Daily/2026-07-06|07-06]]
- [[70_Summaries/Daily/2026-07-07|07-07]]
```

禁止出现 `### 70_Summaries/Daily/...` 后跟 Daily 正文的嵌入结构。

## 14. 失败策略

- llm_wiki 不可用、本地证据足够：生成受限 Summary，run=`degraded`，知识洞察可为零。
- llm_wiki 不可用、本地证据不足：失败，不覆盖旧产物。
- LLM 返回非 JSON 或 schema 错误：带校验错误重试一次；再次失败则 workflow 失败。
- 非白名单维度、超过两个维度、无合法 evidence group IDs：拒绝 item，不静默改写标签。
- 所有 item 被拒绝：workflow 失败；不得生成占位 Summary。
- 上一层缺失：先补齐，不直接生成高层 Summary。
- Markdown validator 失败：不 atomic replace，保留上一版。

### 14.1 可执行的证据充足策略

`summary-policy.v1.json` 固定以下门槛：

- 合格 work evidence group：至少包含一个有正文的原始 Daily、Git commit、confirmed knowledge record 或 accepted candidate source。
- Daily 可生成门槛：至少一个合格 work evidence group。
- Daily knowledge insight 门槛：至少两个独立 canonical source refs，且来自至少两个 source kinds；或一个本地 source + 一个 llm_wiki Deep Chat citation。
- Weekly 门槛：所需工作日的已发布 Daily revisions 完整，且至少两个 supporting Daily items。
- Monthly/Quarterly/Yearly 门槛：直接上一层 required revisions 完整，且至少两个 supporting items；部署日起截断规则继续生效。
- 不满足整份 Summary 门槛：失败；只是不满足 insight 门槛：允许零洞察。

### 14.2 degraded 状态传播

- revision 保存 `quality_status=degraded` 与 warning codes。
- CLI 输出固定 marker：`SUMMARY_STATUS=degraded`。
- `knowledge_workflows.py` 的 Summary stage 设置 `degraded_ok=True`，并用 success check 将该 marker 映射为 `WorkflowRunner` 的 degraded step/run。
- `summary_runs`/revision、`workflow_steps`、`workflow_runs` 三层状态必须通过测试保持一致。
- degraded 不是静默成功；status/health 输出必须展示缺失的 evidence provider。

## 15. 定时调度契约

launchd 每日触发三个入口：

| 时间 | 入口 | 日历行为 |
|---|---|---|
| 09:00 | `daily_morning.sh` | 仅中国工作日；含调休周末，不含法定节假日 |
| 17:30 | `daily_reminder.sh` | 仅中国工作日；含调休周末，不含法定节假日 |
| 18:00 | `run-daily-evening.sh` | 每个自然日触发，具体 workflow 由 `summary_calendar.py` 决定 |

18:00 scheduler 规则：

- Daily：中国工作日。
- Weekly：工作日且次日为非工作日；覆盖周五和节前最后工作日。
- Monthly：自然月最后一天，即使是周末/节假日。
- Quarterly：自然季度最后一天。
- Yearly：自然年最后一天。
- 同一天可顺序运行多个 workflow，必须先低层后高层。
- `chinese_calendar` 是唯一工作日/节假日权威；不得回退为简单 Mon–Fri 后仍声称支持节假日。

调度变更同步更新：launchd installer、cron 文档、ops、troubleshooting、测试。真实验收检查生成 plist 与 `launchctl print` 的 Hour/Minute，并分别试跑普通工作日、周末、法定节假日、调休工作日、节前最后工作日、月/季/年边界。

## 16. 文件保留、重写与删除清单

原则：每个运行时文件只有一个现行职责；不存在“先留着兼容”的第二路径。

| 文件 | 动作 | 唯一职责 |
|---|---|---|
| `knowledge_workflows.py` | 保留并收窄 | workflow registry + durable adapter |
| `period_summary.py` | 重写 | Summary Engine orchestrator |
| `summary_evidence.py` | 新增 | evidence collection + llm_wiki context |
| `summary_synthesis.py` | 新增 | prompt invocation + JSON parsing |
| `summary_contracts.py` | 新增 | schema/taxonomy/value validation |
| `summary_renderer.py` | 新增 | deterministic Markdown projection |
| `summary_store.py` | 扩展 | summary/item/dimension/source persistence |
| `llm_wiki_client.py` | 扩展 | read-only search/file/graph/review/chat API |
| `scripts/build_period_summary.py` | 保留 | CLI adapter |
| `scripts/daily_summary.py` | 删除 | 旧双路径，不保留 wrapper |
| `prompts/chat_review.md` | 重写契约 | upstream chat evidence filter |
| `prompts/daily-summary.md` | 重写契约 | Daily structured synthesis |
| `prompts/weekly-summary.md` | 重写契约 | Weekly structured synthesis |
| `prompts/higher-period-summary.md` | 新增 | Monthly/Quarterly/Yearly structured synthesis |
| `prompts/summary-evidence-research.md` | 新增 | llm_wiki deep evidence analysis |
| `prompts/summary-output.schema.json` | 新增 | machine output contract |
| `prompts/summary-dimensions.v1.json` | 新增 | canonical dimension taxonomy |
| `prompts/summary-policy.v1.json` | 新增 | evidence sufficiency and length policy |
| `summary_calendar.py` | 保留 | 中国工作日与周期 trigger 判定 |
| `scripts/run_summary_schedule.py` | 保留 | 18:00 多层 workflow 顺序调度 |
| `daily_morning.sh` | 保留并修正 | 09:00 工作日 Daily 创建 |
| `daily_reminder.sh` | 新增 | 17:30 工作日提醒门禁 |
| `run-daily-evening.sh` | 保留 | 18:00 scheduler shell adapter |
| `launchd/install_obsidian_jobs.sh` | 修改 | 安装 09:00/17:30/18:00 三个任务 |

必须同步迁移：

- `knowledge-daily-weekly-synthesis` skill。
- `knowledge-source-ingestion` 中调用旧 Daily synthesis 的 full-cycle 脚本。
- schedule / run scripts。
- 所有引用旧 `daily_summary.py` 或旧 stage 的测试与文档。

迁移完成门槛：运行时目录、skills、schedule 与非 archive 测试中不再引用旧入口。archive 文档只保留历史说明，不能被任何运行脚本导入或执行。

## 17. 测试设计

### 17.1 Contract tests

- JSON Schema 接受合法 Daily/Weekly/Monthly/Quarterly/Yearly。
- 拒绝非法 item type、缺 evidence、非法 confidence。
- taxonomy 五类分别覆盖正例、反例、边界例。
- 每条最多两个维度；位置 1/2 稳定。
- prompt/schema/taxonomy contract version 一致。
- 相同 input digest 直接复用 published revision，不再次调用 LLM。
- evidence sufficiency policy 覆盖足够、不足、零洞察边界。

### 17.2 Synthesis tests

- chat review 过滤纯状态汇报。
- Daily 同时包含工作进展与知识洞察。
- 洞察只能为 0 或 2–4 条。
- Weekly 合并跨日事实，不虚构完成状态。
- Monthly/Quarterly/Yearly 只引用直接上一层 items 与 wikilinks。
- llm_wiki 引用能映射为 source refs。

### 17.3 Persistence tests

- 连跑两次 item 数不增长。
- dimensions、sources、support rows 不重复。
- 相同输入生成相同有效 item IDs。
- 新输入生成 immutable revision，旧 revision 保留审计且不混入当前投影。
- transaction 失败不留下半套数据。
- staged 后文件失败可重试；atomic replace 后 DB finalize 失败可恢复。

### 17.4 Rendering tests

- Golden Daily/Weekly/Higher Period Markdown 快照。
- Daily 800–1200 中文字；Weekly 1200–1800 中文字。
- 标题、空行、列表、表格、wikilinks 合法。
- Weekly 不包含 Daily 正文。
- 相同输入重跑 Markdown hash 不变。
- validator 失败不覆盖旧文件。

### 17.5 Schedule and alignment tests

- launchd 精确安装 09:00、17:30、18:00。
- 09:00/17:30 在普通工作日与调休工作日执行，在周末与法定节假日跳过。
- 18:00 每日触发；Daily/Weekly/Monthly/Quarterly/Yearly 由 calendar 分派。
- 节前最后工作日触发 Weekly；月/季/年末即使非工作日仍触发高层 Summary。
- 多层 workflow 以 Daily -> Weekly -> Monthly -> Quarterly -> Yearly 顺序执行。

- runtime/skills/schedule 不引用 `scripts/daily_summary.py`。
- `knowledge_workflows.py` 不包含旧 stage。
- Summary prompt 不使用旧 `#绩效-*` 标签。
- public Summary prompt 不被 private 文件覆盖。
- README、CONTEXT、ops 与实际 workflow 名称一致。

## 18. 实施与真实验收顺序

1. 先新增 schema、taxonomy、contracts 与测试。
2. 新增 SQLite 表和 idempotent store。
3. 扩展 llm_wiki client 与 evidence collector。
4. 重写三个现有 prompt，新增 higher-period 与 evidence research prompt。
5. 实现 synthesis 与 renderer。
6. 把 `period_summary.py` 收窄为 orchestrator。
7. 迁移 manager、skills、schedule、tests。
8. 删除旧 `scripts/daily_summary.py` 与旧 workflow stage。
9. 更新 README、CONTEXT、ops、reference、troubleshooting 与 skill 文档。
10. 临时 DB/vault 跑 Daily、Weekly、Monthly、Quarterly、Yearly。
11. 运行相关 pytest、`make check`、`make privacy-audit`。
12. 备份现有 2026-07-10 Daily 与 2026-W28 Weekly。
13. 使用真实 llm_wiki API 重生成两份产物。
14. 再次重跑并证明 SQLite 行数与 Markdown hash 不变。
15. 重新安装 launchd jobs，核对 09:00/17:30/18:00，并试跑工作日/周末/节假日/调休/周期边界。

## 19. 验收标准

- Daily 800–1200 中文字，工作进展与知识洞察均有明确篇幅。
- Daily 知识洞察严格为 0 或 2–4 条。
- Weekly 1200–1800 中文字，包含跨日成果、趋势、决定、风险、下周重点与知识演进。
- Weekly 仅以 wikilink 引用 Daily，不包含 Daily 正文副本。
- Monthly/Quarterly/Yearly 只引用直接上一层，不复制正文。
- 每条 item 有明确类型、1–2 个或零个合法维度、证据与置信度。
- 无检索结果枚举、无“待归纳”等填充话术。
- llm_wiki Deep Chat 结果带引用，并被保存为 source refs。
- SQLite 是 item/tag/source canonical state；Markdown 可从 SQLite 重建。
- 相同输入连续运行两次，SQLite 有效行数与 Markdown hash 不变。
- 所有 runtime caller 只走 manager -> workflow -> Summary Engine。
- 旧 `daily_summary.py`、旧 stage 与旧标签体系从现行路径删除。
- 每个新增或保留的运行时文件都有本设计列明的唯一职责。
- 09:00、17:30、18:00 调度与中国工作日、周末、节假日、调休规则均有自动和真实证据。
