整体判断：**方向是对的，而且已经接近可以直接进入第一阶段实现的设计稿。**

你抓住了最关键的边界：

* SQLite 负责可追溯的结构化状态；
* Obsidian 负责可读、可浏览、可人工思考的投影；
* LLM 是能力层，不是新的状态层；
* Legacy Pull 保留，但不继续主导架构；
* `--force` 被定义为重建投影，而不是重跑并污染知识状态。

这比“对话自动写日报 + Obsidian 当数据库”的方案成熟很多。

但我建议在正式写 spec / 开工前，补齐下面几处契约。不补的话，后期最容易出现重复、污染、误覆盖和“到底谁是事实”的混乱。

---

# 总体评价

我会把它定义为：

> **一个以 SQLite 为 canonical workflow/knowledge state、以 Obsidian 为可重建 projection 的知识流水线。**

这个定位非常好。

尤其是这几条很稳：

1. 不让 Obsidian 成为工作流状态源；
2. 不把完整原始材料塞进 SQLite；
3. 不为“未来可能需要”提前拆掉 Legacy Pull；
4. 不把 NotebookLM 绑定成架构核心；
5. 把 idempotency、traceability、`--force` 提前写成契约，而不是以后补。

这意味着你的系统未来即使换 Obsidian、换 LLM、换源数据，也不会推翻底层状态模型。

---

# 一、最需要补的一点：Accepted 和 Candidate 必须明确分层

你文中有一句：

> `knowledge_records` rows for durable accepted knowledge

但 Archive extraction 又会由 LLM 产生结构化记录。

这里有风险：**LLM 抽取结果不能天然算 accepted knowledge。**

否则会出现：

```text
原始材料
→ LLM 抽取
→ 自动写入 knowledge_records
→ 再被日报 / 周报 / 卡片引用
→ 形成“模型总结模型”的闭环污染
```

建议不新增“第二张知识表”，但给 `knowledge_records` 明确生命周期。

```text
captured
  ↓
extracted
  ↓
candidate
  ↓
accepted
  ↓
superseded / deprecated

candidate → rejected
```

推荐字段：

```yaml
lifecycle_state: candidate | accepted | rejected | superseded | deprecated
authority: human | trusted_agent | extractor | migration
confidence: 0.0
reviewed_by:
reviewed_at:
supersedes_id:
source_locator:
```

建议默认规则：

| 来源                       | 默认状态                                  |
| ------------------------ | ------------------------------------- |
| 人工确认的 `knowledge-record` | `accepted`                            |
| 高可信 Agent 显式写入           | `accepted` 或 `candidate`，取决于 Agent 权限 |
| Archive LLM extraction   | `candidate`                           |
| Legacy Pull 回填           | `candidate` 或 `accepted`，取决于历史可信度     |
| 自动生成 ADR/Card 草稿         | `candidate`                           |

正式渲染到 ADR、Card、长期方法论库时，只查询：

```sql
WHERE lifecycle_state = 'accepted'
```

这样“一个 accepted knowledge surface”的设计仍成立，但不会把未经验证的抽取结果混进去。

---

# 二、“一个状态模型”不等于“一个表”

你不需要加新的顶层知识表，但建议明确几个支撑实体。

最小可行模型可以是：

```text
source_artifacts
  原始文件/外部来源的目录指针、hash、逻辑 ID、版本信息

processing_runs
  每次抽取、渲染、LLM 调用的 run_id、prompt、model、时间、结果状态

knowledge_records
  知识对象本身：事实、决策、卡片、候选、方法、指标等

materializations
  某条 record 被渲染到了哪个 Markdown 文件、哪个 block、哪个版本
```

关系大致是：

```text
source_artifact
  → source_revision
  → processing_run
  → knowledge_record
  → materialization
  → Obsidian Markdown
```

这里 `knowledge_records` 仍然是唯一知识主表；其他表只解决：

* 来源在哪里；
* 哪个版本产生了它；
* 哪次 LLM 调用生成；
* 已经渲染到哪里；
* 是否需要重新渲染。

---

# 三、Idempotency Identity 要和 Run ID 分开

你已经写了 source identity、processing identity，很好，但建议再明确一条：

> `run_id` 不能参与去重主键。

因为每次执行都会有新 run id；如果它进入 identity，重跑必然重复。

建议拆成四类 identity：

```text
Source identity
  source_family + logical_source_id

Source revision identity
  source_identity + content_hash

Extraction identity
  source_revision + extractor_backend + prompt_version + schema_version

Materialization identity
  record_id + projection_type + target_path + template_version
```

例如：

```text
archive:meeting-notes:2026-07-06-sales-review
revision:sha256(...)
extract:v1:openai:gpt-x:prompt-2026-07-01
render:ADR-2026-012:obsidian-note:template-v3
```

这样：

* 同一份源文件重跑，不会重复抽取；
* 同一条记录重复 render，不会重复写文件；
* prompt 或 schema 更新，可以明确重算；
* 新源文件版本可以保留 provenance，而不是无声覆盖旧结论。

---

# 四、`--force` 语义需要再收紧

你现在的定义总体正确：

> `--force` = rebuild this projection from current SQLite state

但还需要再加一句：

> `--force` 跳过 projection cache / fingerprint，不等于允许无条件覆盖人工内容。

建议把 Markdown 输出分成三类。

| 类型     | 示例                   | `--force` 行为       |
| ------ | -------------------- | ------------------ |
| 全托管页面  | Dashboard、Index、自动目录 | 整页确定性重写            |
| 区块托管页面 | Daily、Weekly、月报      | 只替换 marker 包围的自动区块 |
| 人工参与页面 | ADR、Card、项目复盘        | 只更新受控区块，保留人工区      |

推荐 ADR/Card 模板：

```markdown
---
record_id: ADR-2026-012
projection_version: 3
input_fingerprint: ...
rendered_at: ...
---

# ADR-2026-012

## Generated Context
<!-- generated:start -->
...
<!-- generated:end -->

## Human Notes
<!-- human:start -->
...
<!-- human:end -->

## Decision
<!-- generated:start -->
...
<!-- generated:end -->
```

这样 `--force` 永远只替换 `generated:*` 区域。

否则未来某次你在 ADR 里写了很重要的手工判断，然后执行一次 `--force`，整份内容被覆盖，会非常痛。

---

# 五、当前文档里有两个小矛盾，建议直接改掉

## 1. Render “writes Markdown only”

你写：

> Render reads from SQLite and writes Markdown only.

但后面又允许：

> materialized paths or run logs

这两句严格来说冲突。

建议改为：

```text
Render reads canonical state from SQLite and writes Markdown projections.
It may update render bookkeeping only, such as materialization paths,
input fingerprints, render timestamps, and run logs.
It must not mutate semantic knowledge state, review state, provenance,
or extraction state.
```

这会把“允许的 SQLite 写操作”界定得很清楚。

---

## 2. ADR/Card 是 Output，但自动晋升又 Out of Scope

你写的 Outputs 包含：

```text
Daily notes
ADR notes
Card notes
```

但 Scope 又写：

```text
automatic promotion from archive summary to ADR/Card/Daily
```

不在本阶段。

建议明确：

```text
Render only materializes records that have already been typed and accepted
as daily items, ADRs, cards, or indexes.

Archive extraction may create candidates, but it does not automatically
promote candidates into ADR/Card/Daily in stage one.
```

这样不会让实现者误解为“Archive 一抽取就自动长出 ADR/Card”。

---

# 六、LLM Synthesis 需要有输入指纹，否则“幂等”只是假象

结构化渲染容易做到确定性，但 LLM 总结不是天然确定性的。

即便输入相同，模型也可能每次写出不同文字。

建议为每次 synthesis 建立：

```text
input_fingerprint =
  sorted(record_id + record_revision)
  + prompt_version
  + template_version
  + model_policy
```

规则：

```text
同一 input_fingerprint
  → 默认复用已有 synthesis

输入变化
  → 生成新 synthesis

--force
  → 明确重新生成，并记录新的 generation/run
```

渲染文件中保留：

```yaml
llm_model:
prompt_version:
input_fingerprint:
generation_run_id:
generated_at:
```

这样以后看到某段周报总结，能回答：

* 它依据哪些 record；
* 使用了哪个 prompt；
* 哪个模型生成；
* 为什么它和上周不一样。

---

# 七、建议补一个“渲染快照”概念

否则会出现：

```text
Render 开始
→ SQLite 又写入新 record
→ Daily 用旧数据
→ Dashboard 用新数据
→ 同一次 render 输出不一致
```

建议：

```text
render_state_watermark
```

或者在一个 SQLite read transaction 内完成：

```text
1. 读取当前 state revision / max(updated_at)
2. 所有 projection 基于该 snapshot render
3. materialization 记录 snapshot watermark
```

每个 Markdown frontmatter 里可写：

```yaml
state_watermark: 2026-07-06T14:31:02Z
```

这会让调试和重建容易很多。

---

# 八、隐私与仓库边界要提前写进去

你的路径是：

```text
<workspace>/mac-bootstrap
```

如果这是配置仓库或会进入 Git，必须明确：

```text
- raw archives must be outside tracked template directories
- runtime SQLite must be gitignored
- source manifests must not expose sensitive raw text by default
- generated Obsidian notes must avoid leaking full conversation content
- trace fields should reference IDs / hashes / relative paths where possible
```

尤其是 Agent 对话、会议纪要、企业 wiki，不能因为“可追溯”就把原文和敏感上下文写进 frontmatter。

建议：

```text
SQLite / raw archive：本地 runtime、忽略 Git
Obsidian projection：可选择同步，但按敏感级别分 vault
Repo template：只放代码、模板、schema、测试数据
```

---

# 我建议写进 spec 的核心状态机

```text
Raw Source
  ↓
Source Artifact + Source Revision
  ↓
Extraction Run
  ↓
Knowledge Record (candidate)
  ├─ reject
  ├─ merge into existing record
  └─ accept
        ↓
    Typed Record
    ├─ daily_item
    ├─ ADR
    ├─ card
    ├─ method
    ├─ metric
    └─ source_index
        ↓
    Render Materialization
        ↓
    Obsidian Presentation
```

其中最重要的一条：

> **Render 只渲染“已经被确认类型和状态的记录”；它不承担知识晋升决策。**

---

# 推荐的第一阶段实施顺序

不要先做 Archive 抽取。先把主链打扎实。

```text
1. 固化 SQLite record / source / run / materialization contract
2. 定义 lifecycle_state 与 authority
3. 完成 materialization idempotency + --force
4. 给 Daily / ADR / Card 统一加 trace frontmatter
5. 加 render input fingerprint 和 snapshot watermark
6. 更新 README、operator docs、测试
7. 最后再接 Archive extractor adapter
```

这样你第一阶段就已经拥有一个可靠系统：

```text
live Push
→ SQLite
→ Obsidian
→ Dataview / report
```

Archive、NotebookLM、更多数据源，只是后续接入 Layer 1 的输入适配器。

---

# 最终结论

我会支持这个方案进入 implementation，但建议将它从：

> “SQLite accepted knowledge → Obsidian render”

进一步明确成：

> **“SQLite 维护来源、版本、运行、候选、已接受知识与投影记录；Obsidian 只消费已接受记录的可重建投影。”**

只要补上：

1. `candidate → accepted` 生命周期；
2. render 与人工内容的边界；
3. 去重 identity 与 run identity 分离；
4. LLM synthesis 的输入指纹；
5. 统一的 materialization manifest；
6. Stage 1 中 ADR/Card 的“仅渲染，不自动晋升”规则；

这个架构会非常稳，而且后续扩展 Archive、企业知识源、不同模型后端时不容易推倒重来。
