我认为这是一个**有条件通过、可以进入实现前最后收口**的计划。

相比上一版，它已经把架构、代码边界、测试、文档、隐私和分支收尾都拆到了可执行粒度；尤其是把 `run_id` 排除出幂等键、把 `--force` 限制为投影重建、保留 Legacy Pull 但降级为 backfill，这些判断是对的。

但我建议先修正以下几个 **P0 问题**，再开工。

## 1. `status` 与 `lifecycle_state` 会形成双真相源

现在同时有：

```text
status
lifecycle_state
```

而渲染查询又要求两者都是 `accepted`。这会造成状态漂移：某段旧代码只更新 `status`，新代码只更新 `lifecycle_state`，记录就可能永久不可渲染。

建议明确：

```text
lifecycle_state = 唯一业务状态真相
status = 兼容旧接口的映射字段，逐步废弃
```

至少补一条迁移与测试规则：

```text
status='accepted'  <=> lifecycle_state='accepted'
status='rejected'  <=> lifecycle_state='rejected'
```

更好的做法是新代码只读写 `lifecycle_state`，旧 `status` 仅在兼容层同步。

---

## 2. `input_fingerprint`、`state_watermark` 不应放在 `knowledge_records`

它们本质是**投影 / render 的属性**，不是知识本身的属性。

目前计划一边强调：

> Render 不得修改 semantic knowledge state

一边又把 render fingerprint、watermark 加到 `knowledge_records`，模型上会混淆边界。

建议拆开：

```text
knowledge_records
  semantic_revision / content_hash
  lifecycle_state
  authority
  provenance

processing_runs
  extraction input fingerprint
  prompt/model/backend

materializations
  projection input fingerprint
  state watermark
  template version
  rendered_at
```

其中 `record_revision` 也需要有明确生成规则。建议使用“稳定语义字段的 SHA-256”，而不是只依赖 `updated_at`。

---

## 3. `materializations` 的唯一键存在 SQLite 的 NULL 陷阱

当前约束：

```sql
UNIQUE(record_id, projection_type, target_path, block_id, template_version)
```

但 `block_id` 允许 `NULL`。SQLite 中多个 `NULL` 不会互相冲突，因此同一投影可能重复插入多条 materialization。

建议改成：

```sql
block_id TEXT NOT NULL DEFAULT ''
```

代码中也统一：

```python
block_id = block_id or ""
```

另外，`target_path` 不适合作为核心身份的一部分。文件移动、目录调整、vault 改名后，会产生新的 materialization，而不是更新原记录。

建议增加稳定的逻辑键：

```text
projection_key =
  record_id + projection_type + logical_target + block_id + template_version
```

例如：

```text
kr_001|daily_item|2026-07-06|content|daily-v2
kr_001|card|knowledge-card|content|card-v2
```

`target_path` 只是这个 projection 当前落在哪里，可更新，不应决定身份。

---

## 4. 现有 `--force` 设计还不能真正“重建投影”

Task 2 的代码只替换：

```text
<!-- generated:start ... -->
...
<!-- generated:end -->
```

这能保住 `## Human Notes`，很好；但它不会更新：

* frontmatter 中的 title、tags、trace、source、revision；
* note 类型、日期、投影版本；
* 已变化的路径或生成元数据。

所以它现在是“重写正文内容块”，还不是你定义中的：

> rebuild this projection from current SQLite state

建议把每类内容所有权写死：

```text
系统拥有：
- 受控 frontmatter keys
- generated blocks
- 自动索引、dashboard

人工拥有：
- Human Notes
- 人工自定义段落
- 未受控 frontmatter keys
```

实现上不要整份覆盖。应当：

1. 解析 frontmatter；
2. 仅 patch 系统拥有的 key；
3. 替换所有指定 generated blocks；
4. 原样保留人工 key 和人工正文。

并补两个测试：

```text
force 后 title/tags/trace 更新
force 后 Human Notes 与非托管 frontmatter 保留
```

---

## 5. Task 2 创建了 ledger helper，但没有真正接入 note/daily materialization

计划中 `materialization_store.py` 定义了 `upsert_materialization(...)`，但给 `materialize_note_candidate(...)` 的改造片段只导入，没有调用。

目前真正写 ledger 的只有 Task 3 的 summary index。这样 ADR、Card、Daily 的 trace ledger 仍然是不完整的。

建议明确职责之一：

```text
materialize_daily_candidate
materialize_note_candidate
render_summary_index
daily/weekly synthesis

每一种 projection 成功写入后
都必须 upsert materialization
```

否则“每个 Obsidian 投影可追溯回 SQLite”的验收标准无法成立。

---

## 6. `state_watermark()` 现在不是真正稳定的 watermark

当前空记录时返回：

```python
datetime.now()
```

这会导致空数据重复 render 时，每次都生成不同 watermark，破坏幂等性。

建议至少改为：

```text
无记录：empty
```

更严谨的做法是：

```text
watermark = 当前读取快照中的 max(record_revision / updated_at)
```

并在一个 SQLite read transaction 内加载所有参与当前 render 的记录。否则“先读 Daily，后读 Index”期间有新数据写入，同一次 render 仍可能出现不同视图不一致。

---

## 7. 旧数据迁移策略和文档默认值冲突

你在 schema migration 中给旧记录默认：

```text
lifecycle_state = accepted
authority = trusted_agent
```

但文档又说：

```text
Legacy Pull backfill = candidate / migration
Archive LLM extraction = candidate / extractor
```

这两者不能同时成立。老库里可能混有 live Push、Legacy Pull、历史候选和人工确认数据。

建议先新增一个 **Task 0：仓库与历史数据审计**：

```text
- 枚举现有 knowledge_records 的来源、status、record_type
- 确认 source_documents / workflow_runs / execution_log 的真实字段
- 制定旧记录映射规则
- 输出 migration dry-run 报告
```

然后再决定：

```text
可信 live Push → accepted / trusted_agent
无法识别来源 → candidate / migration
历史 Pull 且已人工确认 → accepted / migration
```

没有这个 Task 0，schema 和测试写得再细，也可能是基于假设实现。

---

## 8. Daily / Weekly LLM synthesis 仍缺少真正的实现与测试闭环

计划要求 daily/weekly LLM synthesis 是 Render 能力，但 Task 3 目前主要覆盖：

```text
summary index
fingerprint
watermark
materialization ledger
```

没有真正覆盖：

* Daily synthesis 的输入包；
* Weekly synthesis 的输入包；
* prompt/backend/model/version；
* 同 fingerprint 是否复用旧生成；
* `--force` 是否明确重新生成；
* LLM 输出是否只写入受控区块；
* 生成失败时是否保留旧投影。

建议把它单列成一个任务，而不是只写在 README 中。

---

## 9. 隐私约束目前主要是文档，不是工程约束

计划写明 runtime SQLite、raw archives、run artifacts 不应提交，这很好；但实现任务中没有明确：

```text
.gitignore
git check-ignore 测试
敏感路径拦截
trace 路径脱敏
source manifest 最小化
```

建议增加至少三项：

```text
1. runtime/, archives/, *.sqlite, manifests/private/ 写入 .gitignore
2. CI / make check 校验敏感运行目录未被 Git 跟踪
3. Obsidian trace 默认只写 record id、hash、相对逻辑引用，不写原始绝对路径或敏感正文
```

---

## 10. 子模块提交命令需要修正

前面 Task 1–4 的提交命令是：

```bash
git add template/...
git commit ...
```

但你后面明确 `template` 是子模块，并在 Task 5 才进入 `template` 目录提交。这样前面那些 commit 命令在父仓库里不会提交子模块内部文件。

建议统一成：

```bash
git -C template add ...
git -C template commit -m "..."
```

父仓库只在最后提交：

```bash
git add template docs/superpowers/...
git commit ...
```

否则执行者很容易在 Task 1 就走错 Git 边界。

---

## 我建议的执行顺序

```text
Task 0：现状审计、旧数据映射、真实接口确认
Task 1：状态模型与迁移策略
Task 2：Projection key、ledger、managed ownership
Task 3：Daily / Weekly / Index 的统一 render contract
Task 4：LLM synthesis fingerprint、缓存、force、失败恢复
Task 5：文档、隐私与 Git 边界
Task 6：全量测试、迁移 dry-run、子模块收尾
```

## 最终判断

这个 plan 的优点是：**不是概念设计，而是已经有实施路径、测试路径和交付路径。**

但我不会建议按原文直接执行。先修掉这六个核心问题：

1. `status` 与 `lifecycle_state` 的单一真相；
2. fingerprint / watermark 的正确归属；
3. NULL 唯一键与路径身份问题；
4. `--force` 的 frontmatter 与人工内容边界；
5. 所有 projection 都必须写 materialization ledger；
6. 历史数据迁移与隐私控制必须落到代码、测试和 Git 规则。

这些补齐后，这份计划会从“很好的 implementation plan”升级为“能长期维护、不容易积累隐性技术债的实施方案”。
