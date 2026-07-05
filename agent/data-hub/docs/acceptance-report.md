# Agent Data Hub 真实本机验收报告

验收日期：2026-07-05  
入口文档：`template/agent/data-hub/README.md`  
验收范围：真实本机 Data Hub 环境、真实 SQLite 账本、真实 Obsidian vault 的 Data Hub 相关路径、durable workflow 状态和 artifact logs。

## 1. 安全边界

本次验收使用真实本机环境，但报告只记录脱敏摘要、计数、路径形态和结构样例：

- 不写入 `private/` 文件变更。
- 不删除、不重置、不批量清理真实 vault、真实日志或历史产物。
- 不把真实笔记正文、密钥、内部主机名、个人敏感内容写入 public template。
- 真实路径在报告中使用 `$REPO`、`$VAULT`、`$AGENT_DB_PATH`、`$AGENT_RUNS_DIR` 表示。

执行前已备份真实 SQLite DB：

```text
command: template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py backup --date 2026-07-05
backup: $REPO/private/agent/data/backups/agent_history-2026-07-05-131019.db
sha256: 75f47d0ec3db2e269cb3a7e44713cc6cccc134882c0cca392529283f7cad33ee
backup_log: status=completed, count=1
```

## 2. 真实环境依赖

| 项目 | 验收命令 | 本机输出摘要 |
|------|----------|--------------|
| Python | `python3 --version` | `Python 3.13.13` |
| uv | `uv --version` | `uv 0.11.26` |
| template runtime | `template/.venv/bin/python --version` | `Python 3.13.13` |
| SQLite CLI | `sqlite3 --version` | `3.51.0` |
| agy CLI | `command -v agy` | available |
| claude CLI | `command -v claude` | available |
| repo gate | `make check` | 收尾阶段重新执行，见第 9 节 |

实际配置由 `manager.py` 通过 `private/agent/data_hub.runtime.jsonc` 得到：

```text
AGENT_DB_PATH=$REPO/private/agent/data/agent_history.db
AGENT_RUNS_DIR=$REPO/private/agent/data/runs
OBSIDIAN_VAULT_DIR=$VAULT
OBSIDIAN_DAILY_DIR=10_Periodic/Daily
GIT_SEARCH_ROOTS=$HOME/work/config,$HOME/work/projects
```

注意：shell 中显式导出的环境变量优先；env 文件只补默认值。

## 3. 真实 Workflow DAG

`README.md` 的统一入口是：

```bash
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow full_cycle --date YYYY-MM-DD
```

`knowledge_workflows.py` 中的真实 DAG 如下。

| Workflow | Step 顺序 | 规则判定 | 模型判断 |
|----------|-----------|----------|----------|
| `daily_ingest_and_review` | retrieval -> log ingest -> source ingest -> claim extraction -> candidate review | DB upsert、source date attribution、candidate markdown `file_exists` | source/chat 内容分类和 claim 语义提炼 |
| `auto_review_only` | auto review | confidence 阈值把候选置为 `accepted` 或保持 `pending` | 无 |
| `daily_promote_and_summary` | materialize -> daily synthesis | daily note `file_exists`、输出不含 duplicate marker failure、AI summary failure marker | `daily_summary.py` 调用 LLM 生成日报摘要 |
| `materialize_only` | materialize | 同上 materialization success checks | 无 |
| `weekly_hygiene_and_reuse` | hygiene audit -> retrieval | 只读审计孤儿、过期、重复、日期异常 | retrieval packet 的匹配质量受关键词和既有内容影响 |
| `source_adapter_upgrade` | source ingest -> source regression pytest | pytest stdout exists 且 returncode=0 | 无 |
| `full_cycle` | ingest/review -> auto review -> promote/summary | 组合上述规则 | 组合上述模型判断 |

Stage contract 使用 `StageSpec`，durable runner 接收 typed spec 或兼容 dict。成功判定不是只看 returncode；存在 success checks 的 step 必须同时通过：

- `knowledge-candidate-review`: `$VAULT/60_Inbox/Candidates/YYYY-MM-DD.md` 存在。
- `knowledge-materialization`: `$VAULT/10_Periodic/Daily/YYYY-MM-DD.md` 存在，stdout/stderr 不含 duplicate marker failure。
- `knowledge-daily-weekly-synthesis`: daily note 存在，stdout/stderr 不含 LLM failure markers；该 step `degraded_ok=true`。
- `source-regression-tests`: pytest stdout artifact 存在且进程 returncode 为 0。

## 4. 执行前只读盘点

真实 DB 在备份前已有业务表数据，但 workflow 状态表尚未存在；执行 backup 后 schema 初始化出 durable 状态表。

备份前业务表计数：

| 表 | count |
|----|-------|
| `sessions` | 215 |
| `messages` | 2028 |
| `source_documents` | 4 |
| `document_chunks` | 119 |
| `extracted_items` | 119 |
| `knowledge_candidates` | 7 |

备份后 durable 表状态：

| 表 | count |
|----|-------|
| `workflow_runs` | 0 |
| `workflow_steps` | 0 |
| `artifact_manifest` | 0 |
| `backup_log` | 1 |

真实 source/vault 盘点只记录路径类别和数量：

| vault source 类别 | 文件数 |
|-------------------|--------|
| `$VAULT/50_Sources/Meetings` | 2 |
| `$VAULT/50_Sources/Mindmaps` | 1 |
| `$VAULT/50_Sources/Wiki-Clips` | 1 |

执行前 `manager.py health`：0 failed workflow runs，最近 3 天有 2 条历史 legacy step failure。它们来自旧 `execution_log`，不是本次 durable run。

## 5. 逐步验收记录

目标日期：`2026-07-05`。

### 5.1 Dry-run

验收命令：

```bash
template/.venv/bin/python template/agent/data-hub/knowledge_workflows.py full_cycle 2026-07-05 --dry-run
```

输出摘要：8 个 `StageSpec`，包含 step name、command、produces、retry policy、success checks、`degraded_ok`。该输出用于确认真实 CLI 将执行的 DAG，不写 DB/vault。

同日还对 `daily_ingest_and_review`、`daily_promote_and_summary`、`weekly_hygiene_and_reuse`、`source_adapter_upgrade` 执行了 dry-run，并保存到 `/tmp/data-hub-dryrun-*.json`。

### 5.2 `daily_ingest_and_review`

验收命令：

```bash
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow daily_ingest_and_review --date 2026-07-05 --run-id real_accept_ingest_20260705
```

上游输入：

- `$AGENT_DB_PATH` 中既有 agent sessions/messages、source_documents、chunks、items、candidates。
- `$VAULT/50_Sources/*` 下的 meeting、wiki、xmind source 文件。
- 本机 Claude/Codex/AGY transcript 目录。
- 预检索读取 `$VAULT/10_Periodic`、`$VAULT/40_Knowledge` 和 open candidates。

执行结果：

| Step | 状态 | 产物 |
|------|------|------|
| `knowledge-reuse-retrieval` | completed | `$AGENT_RUNS_DIR/real_accept_ingest_20260705/01-*.stdout.log` |
| `knowledge-source-ingestion:logs` | completed | `sessions/messages` |
| `knowledge-source-ingestion:sources` | completed | `source_documents/document_chunks/extracted_items` |
| `knowledge-claim-extraction` | completed | claim packet stdout |
| `knowledge-candidate-review` | completed | `$VAULT/60_Inbox/Candidates/2026-07-05.md` |

DB 变化：

| 表 | 执行前 | 执行后 |
|----|--------|--------|
| `sessions` | 215 | 223 |
| `messages` | 2028 | 2072 |
| `source_documents` | 4 | 4 |
| `document_chunks` | 119 | 119 |
| `extracted_items` | 119 | 119 |
| `knowledge_candidates` | 7 | 7 |

规则判定：

- `ingest_logs.py` 增量写入新 transcript message，不重复写入已存在消息。
- `ingest_sources.py` 对 4 个 source documents 产出 119 chunks/items；source 未变化时计数不增加。
- `generate_candidates.py` 对候选做 upsert；2026-07-05 为零候选路径，仍重写 review markdown。
- `knowledge-candidate-review` success check 通过：candidate markdown 存在。

模型判断：

- `claim_extraction.py` 对聊天和 source items 做语义类型/claim 抽取；本报告不记录正文，只记录该 step returncode=0 且 artifact 已落盘。

warning：

- `ingest_logs.py` 捕获到若干 AGY transcript JSON parse error，并继续完成。建议后续把 malformed transcript 统计单独结构化输出，方便排查但不阻断主链路。

候选 markdown 格式：

```markdown
---
type: candidate-review
date: 2026-07-05
status: active
---
# Candidate Review 2026-07-05
## DAILY
- 无
## ADR
- 无
## CARD
```

验收结论：通过。该日期无新增候选是业务输入结果，不是失败。

### 5.3 `auto_review_only`

验收命令：

```bash
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow auto_review_only --date 2026-07-05 --run-id real_accept_auto_20260705
```

上游输入：`knowledge_candidates` 中 target date 的候选。  
下游依赖：`materialize_candidates.py` 只 materialize `accepted` candidates。

规则判定：

- `auto_review.py` 使用固定 confidence 阈值：
  - `daily`: 0.80
  - `card`: 0.80
  - `adr`: 0.85
- 达标候选自动更新为 `status='accepted'`；不达标保持 `pending`。
- 2026-07-05 没有候选，因此无状态变化。

模型判断：无。confidence 来自上游提取/分类，但本 step 本身是规则判定。

验收结论：通过，step completed，exit=0。

### 5.4 `daily_promote_and_summary`

验收命令：

```bash
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow daily_promote_and_summary --date 2026-07-05 --run-id real_accept_promote_20260705
```

上游输入：

- candidate review markdown。
- `knowledge_candidates.status='accepted'`。
- `$VAULT/10_Periodic/Daily/2026-07-05.md`。
- 本机 Git logs 与 agent conversation summary。
- 可用 LLM CLI：`agy` 或 `claude`。

执行结果：

| Step | 状态 | stdout 摘要 |
|------|------|-------------|
| `knowledge-materialization` | completed | `0 reviewed, 0 materialized` |
| `knowledge-daily-weekly-synthesis` | completed | LLM summary written |

规则判定：

- `materialize_candidates.py` 读取 review action，把 `accept/reject/merge/defer` 映射到 canonical status。
- daily materialization 使用 `<!-- knowledge_candidate:<id> -->` marker 防重复。
- ADR/Card materialization 使用 frontmatter `candidate_id` 防重复。
- `daily_summary.py` 只重写 `## AI 总结` section，不重复追加。
- `knowledge-daily-weekly-synthesis` success checks 通过：daily note 存在，stdout/stderr 不含 LLM failure marker。

模型判断：

- `daily_summary.py` 调用 LLM 生成 `## AI 总结`。
- 内容质量验收只做结构和安全检查：存在一个 `## AI 总结` section；输出为中文 bullet summary；未在报告中复制真实正文。
- LLM 输出不可字节级稳定复现，后续回归应验证 section 存在、failure marker 不存在、不会重复追加，而不是固定文本。

日报格式检查：

```text
frontmatter: type=journal, status=active, owner=<redacted>, date=2026-07-05, week, month, quarter, tags
heading: # 2026年07月05日 星期日
required sections observed: ## 今日重点, ## 工作记录, ## AI 总结
AI summary heading count: 1
knowledge_candidate markers: 0
line count after run: 48
```

验收结论：通过。无 2026-07-05 accepted candidates，因此没有新增 ADR/Card，也没有 daily candidate marker。

### 5.5 幂等性重跑：`materialize_only`

验收命令：

```bash
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow materialize_only --date 2026-07-05 --run-id real_accept_materialize_idem_20260705
```

stdout 摘要：

```text
[materialize_candidates] 2026-07-05: 0 reviewed, 0 materialized
```

验收结论：通过。重跑没有重复追加 candidate marker，没有新增 2026-07-05 ADR/Card 文件，daily note 行数保持 48。

### 5.6 `weekly_hygiene_and_reuse`

验收命令：

```bash
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow weekly_hygiene_and_reuse --date 2026-07-05 --run-id real_accept_hygiene_20260705
```

执行结果：

| Step | 状态 | 产物 |
|------|------|------|
| `knowledge-hygiene-audit` | completed | JSON hygiene report stdout |
| `knowledge-reuse-retrieval` | completed | JSON retrieval packet stdout |

hygiene report 脱敏摘要：

```text
orphan_candidates: 0
stale_review_items: 6
duplicate_knowledge_candidates: 0
date_anomalies: 2
broken_materializations: 0
repair_recommendations: 2
```

规则判定：

- 只读审计，不自动修复。
- 检查 pending/deferred stale candidates、duplicate accepted ADR/Card、filename date 与 landing date 差异、materialized path 是否断链。

模型判断：

- retrieval packet 的命中排序依赖关键词与历史内容匹配；本次只验证结构存在和路径均为 vault 相对路径，不公开摘录正文。

验收结论：通过。审计发现为后续运维建议，不阻断 workflow。

### 5.7 `source_adapter_upgrade`

验收命令：

```bash
template/.venv/bin/python template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  run --workflow source_adapter_upgrade --date 2026-07-05 --run-id real_accept_source_upgrade_20260705
```

执行结果：

| Step | 状态 | stdout 摘要 |
|------|------|-------------|
| `knowledge-source-ingestion:sources` | completed | 4 documents, 119 chunks, 119 extracted items |
| `source-regression-tests` | completed | `10 passed in 0.22s` |

规则判定：

- source adapters 能重新处理真实 source 文件，并保持总表计数稳定。
- `source-regression-tests` returncode=0，stdout artifact 存在。

模型判断：无。source adapters 当前以规则和启发式分类为主。

验收结论：通过。

## 6. Durable State 与 Artifact 证据

验收 run 全部 completed：

| run_id | workflow | status |
|--------|----------|--------|
| `real_accept_ingest_20260705` | `daily_ingest_and_review` | completed |
| `real_accept_auto_20260705` | `auto_review_only` | completed |
| `real_accept_promote_20260705` | `daily_promote_and_summary` | completed |
| `real_accept_materialize_idem_20260705` | `materialize_only` | completed |
| `real_accept_hygiene_20260705` | `weekly_hygiene_and_reuse` | completed |
| `real_accept_source_upgrade_20260705` | `source_adapter_upgrade` | completed |

`workflow_steps` 共 13 条，全部 `completed`，`exit_code=0`，`attempt=1`。

artifact manifest 聚合：

| run_id | stdout | stderr |
|--------|--------|--------|
| `real_accept_ingest_20260705` | 5 | 5 |
| `real_accept_auto_20260705` | 1 | 1 |
| `real_accept_promote_20260705` | 2 | 2 |
| `real_accept_materialize_idem_20260705` | 1 | 1 |
| `real_accept_hygiene_20260705` | 2 | 2 |
| `real_accept_source_upgrade_20260705` | 2 | 2 |

实际 artifact 路径形态：

```text
$AGENT_RUNS_DIR/<run_id>/<NN>-<step-name>.stdout.log
$AGENT_RUNS_DIR/<run_id>/<NN>-<step-name>.stderr.log
```

执行后核心 DB 计数：

| 表 | count |
|----|-------|
| `sessions` | 223 |
| `messages` | 2072 |
| `source_documents` | 4 |
| `document_chunks` | 119 |
| `extracted_items` | 119 |
| `knowledge_candidates` | 7 |
| `workflow_runs` | 6 |
| `workflow_steps` | 13 |
| `artifact_manifest` | 26 |
| `backup_log` | 1 |

`manager.py status --date 2026-07-05` 显示本次 6 个 real_accept run 全部 completed；`manager.py candidates --date 2026-07-05` 显示 `No candidates found for 2026-07-05`。

## 7. 产物格式验收

| 产物 | 路径形态 | 格式检查 | 结论 |
|------|----------|----------|------|
| Candidate review | `$VAULT/60_Inbox/Candidates/2026-07-05.md` | YAML frontmatter + `# Candidate Review` + `## DAILY/ADR/CARD` | 通过 |
| Daily note | `$VAULT/10_Periodic/Daily/2026-07-05.md` | YAML frontmatter + daily heading + one `## AI 总结` | 通过 |
| ADR/Card materialization | `$VAULT/40_Knowledge/ADR/*.md` / `Cards/*.md` | 本日期无 accepted candidates，未新增 2026-07-05 文件 | 通过 |
| Retrieval packet | stdout artifact JSON | keys 包含 task goal、keywords、matched daily/ADR/cards、open loops | 通过 |
| Hygiene report | stdout artifact JSON | keys 包含 stale/orphan/duplicate/date anomaly/broken materialization | 通过 |
| Workflow logs | `$AGENT_RUNS_DIR/<run_id>/*.log` | stdout/stderr 均登记到 `artifact_manifest` | 通过 |
| Backup log | `backup_log` | status completed + sha256/content hash | 通过 |

## 8. 规则判定 vs 模型判断边界

规则判定：

- workflow DAG、step order、commands、produces、success checks。
- DB schema、SQLite upsert、source 未变化时跳过或重建同一 document 的 chunks/items。
- `auto_review.py` confidence 阈值和 status 映射。
- `candidate_review_io.py` 中 `review_action` 的 markdown 读写格式。
- `materialize_candidates.py` 的 status 映射、daily marker、ADR/Card frontmatter marker。
- `daily_summary.py` 的 section replacement，不重复追加 `## AI 总结`。
- durable runner 的 `completed/failed/degraded` 判定和 resume/retry 状态表。
- hygiene audit 的 stale/orphan/duplicate/date anomaly/broken path 检测。

模型判断：

- source item 类型、标题、摘要、confidence 的语义质量。
- chat claim extraction 的 claim 类型和证据选择。
- `daily_summary.py` 的 LLM 摘要内容、措辞和标签。
- retrieval packet 中匹配结果的业务相关性。

验收建议：规则判定适合自动化测试和精确断言；模型判断只做结构、失败标记、安全边界、人工抽样质量评估，不做字节级固定输出断言。

## 9. 收尾测试

Data Hub 相关 pytest：

```bash
template/.venv/bin/python -m pytest \
  template/tests/test_data_hub.py \
  template/tests/test_data_hub_sources.py \
  template/tests/test_candidate_review.py \
  template/tests/test_materialization.py \
  template/tests/test_phase4_weekly_summary.py \
  template/tests/test_daily_summary_runtime.py \
  template/tests/test_ingest_logs_runtime.py \
  template/tests/test_claim_extraction.py \
  template/tests/test_auto_review.py \
  template/tests/test_hygiene_audit.py \
  template/tests/test_daily_workflows.py \
  template/tests/test_workflow_contracts.py \
  -q
```

输出摘要：

```text
115 passed in 1.63s
```

完整仓库门禁：

```bash
make check
```

输出摘要：

```text
parent privacy-audit: ok
privacy-audit: ok (public files, values suppressed)
Doctor passed.
353 passed, 9 skipped, 1 warning in 32.78s
coverage: 82.08% (required 80.0%)
```

非阻断 warning：

```text
tests/test_daily_workflows.py::test_durable_workflow_retry_failed_resumes_from_failed_step
ResourceWarning: unclosed database in sqlite3.Connection
```

该 warning 来自测试过程中的 sqlite connection 资源释放提示；`make check` exit code 为 0。

## 10. 发现与后续建议

本次验收结论：

- README 描述的真实入口可用；标准 workflow registry 与 manager CLI 对齐。
- 真实 DB 备份成功，备份可通过 `backup_log` 和 sha256 校验。
- 真实本机 6 个核心 workflow 均 completed，13 个 step 全部 exit=0。
- durable state、artifact logs、candidate markdown、daily note、hygiene report、retrieval packet 均符合预期格式。
- 2026-07-05 是零候选路径，验证了 no-op candidate/materialization 的幂等性。

剩余风险：

- `manager.py health` 仍报告 2 条历史 legacy failure，来源于旧 `execution_log`，不影响本次 durable run，但容易造成运维噪音。
- AGY transcript 中存在可跳过的 JSON parse error；建议后续把 parse failure 做结构化汇总，避免 stdout 噪音。
- 本次没有真实 accepted candidate，因此未在真实环境新增 2026-07-05 ADR/Card；ADR/Card 格式仍依赖既有测试和历史产物覆盖。
- LLM 摘要内容不可稳定复现；后续升级应维持结构性验收，不应用固定正文做回归。

后续迭代建议：

- 给 `ingest_logs.py` 增加 malformed transcript summary，例如 `parsed=N skipped=M`，并把具体文件路径留在 artifact，不写入 public 报告。
- 给 `manager.py health` 增加 legacy failure 与 durable failure 的分区显示或静默阈值。
- 增加一个公开 fixture 的 accepted ADR/Card materialization smoke test，补足真实零候选日期无法覆盖的路径。
- 在 README 中把“真实验收”和“隔离验收”的适用场景分开：新机器优先跑隔离验收；维护机器升级前先备份 DB 后跑真实验收。

## 11. Follow-up 修复验收

日期：2026-07-05  
分支：`data-hub-real-acceptance-fixes`

### 11.1 零候选路径解释

本次真实日期 `2026-07-05` 没有新增 ADR/Card 是正常结果：

- `daily_ingest_and_review` 产出的 candidate review 为零候选，`manager.py candidates --date 2026-07-05` 显示 `No candidates found`。
- `auto_review_only` 没有候选可提升为 `accepted`。
- `materialize_candidates.py` 只 materialize `status='accepted'` 的候选，因此 `0 reviewed, 0 materialized` 是正确 no-op。
- `$VAULT/10_Periodic/Daily/2026-07-05.md` 已存在，`daily_summary.py` 只重写 `## AI 总结`，不会另建第二份 daily note。

需要专门覆盖 ADR/Card 新增路径时，应使用隔离 fixture 或选择有 accepted candidates 的日期，避免为了验收强行改写真实知识库。

### 11.2 标签契约优化

标签格式从 slash 层级改为 hyphen 层级：

```text
推荐：#绩效-计划组织 #成长-新贡献 #复盘-做得好
禁止：#绩效 #成长 #复盘
兼容清理：#绩效/计划组织 -> #绩效-计划组织
```

原因：

- `#绩效-计划组织` 保留父子语义，但在 Obsidian/Dataview/搜索里是单个稳定标签。
- `#绩效/计划组织` 会触发 Obsidian 层级标签 UI，适合导航，但不如扁平标签便于按完整维度聚合。
- `daily_summary.py` 增加 `sanitize_summary_tags()`，会删除粗标签、规范化旧 slash 标签，并去掉 LLM 偶发生成的反引号包裹。

真实日报结构检查：

```text
ai_summary_sections: 1
ai_summary_lines: 8
hyphen_tags: #复盘-做得好, #成长-新贡献, #绩效-专业知识, #绩效-计划组织
broad_tags: []
slash_tags: []
backticked_tags: []
```

### 11.3 AGY transcript 解析修复

修复前：单行坏 JSON 会触发 `Error parsing AGY file ...`，真实验收报告中记录为 warning。  
修复后：`ingest_agy()` 改为行级容错，跳过坏 JSON 行，继续保留同一 transcript 内的有效 `USER_INPUT`。

真实运行输出摘要：

```text
Ingesting AGY logs...
[ingest_agy] skipped 8 malformed AGY json lines
  -> 29 new messages
Ingestion complete. Total messages in DB: 2103
```

标准 manager durable run 复核：

```text
run_id: real_accept_fix_ingest_20260705
workflow: daily_ingest_and_review
step: knowledge-source-ingestion:logs
artifact: $AGENT_RUNS_DIR/real_accept_fix_ingest_20260705/02-knowledge-source-ingestion_logs.stdout.log
summary: [ingest_agy] skipped 9 malformed AGY json lines; -> 2 new messages; Total messages in DB: 2105
legacy error marker: absent
```

结论：AGY warning 已从文件级 error 降为结构化汇总，主链路不再输出 `Error parsing AGY file`。

### 11.4 目录整理

`data-hub/` 根目录保留一线入口：

- 可执行 workflow/scripts：`ingest_*.py`、`generate_candidates.py`、`materialize_candidates.py`、`daily_summary.py`、`knowledge_workflows.py` 等。
- 一线文档：`README.md`、`ops.md`、`reference.md`、`troubleshooting.md`。
- 契约/配置：`schema.sql`、`data_hub.runtime.jsonc.example`。

支持材料移动到 `docs/`：

- `docs/acceptance-report.md`
- `docs/cron-setup.md`
- `docs/upgrade-plan.md`
- `docs/archive/phase-5-6-summary.md`

## 12. Chat Candidates 接入验收

日期：2026-07-05  
策略：聊天记录只做候选准入，全部保持 `pending`，`auto_review.py` 不自动 accepted。

2026-07-05 复核修正：前一轮把 user prompts 当作 chat candidates，实际审核价值低；现行规则改为只从 agent/assistant 回复中提炼候选，用户提问只作为 `background_prompt` 辅助人工审核。

### 12.1 实现规则

- `ingest_logs.py` 会落库 user 和 assistant 两类可见消息；Claude 只取 `text`，Codex 只取 user/assistant/`agent_message`，AGY 只取 `USER_INPUT` 和有 `content` 的 `PLANNER_RESPONSE`。
- `generate_candidates.py` 同时读取外部材料 extracted items 和 assistant response claims。
- chat response 使用 `source_type='chat_response'`、`parser_version='chat-answer-v2'` 的合成 `source_documents/extracted_items` 投影，保持现有 schema 和外键结构。
- 旧 `source_type='chat_message'`、`parser_version='chat-claim-v1'` 用户提问投影会在重建 chat candidates 前清理。
- `decision -> adr`，`action/open_loop -> daily`，`risk/insight_candidate -> card`。
- 纯提问、状态回复、工具/思考日志不进入 candidates，避免把过程噪音写入长期知识。
- `auto_review.py` 遇到 `metadata_json.source_kind in ('chat_response', 'chat_message')` 时计入 `skipped`，不改 status。

### 12.2 隔离 smoke test

临时 DB 只放 user prompts + assistant replies，不放 `50_Sources`：

```text
template/.venv/bin/python -m pytest \
  template/tests/test_ingest_logs_runtime.py \
  template/tests/test_candidate_review.py \
  template/tests/test_auto_review.py \
  template/tests/test_claim_extraction.py

55 passed in 0.66s

template/.venv/bin/python -m pytest template/tests \
  -k 'data_hub or workflow or candidate or claim or ingest_logs or auto_review or materialize or daily_summary or backup or source'

118 passed, 1 skipped, 252 deselected in 1.58s
```

结构性断言：

```text
user questions do not generate chat candidates
assistant status-only replies do not generate chat candidates
metadata_json.source_kind == chat_response
metadata_json.response_role == assistant
metadata_json.background_prompt records the previous user prompt
legacy chat_message/chat-claim-v1 projection is removed during rebuild
auto_review skipped chat_response candidates
```

### 12.3 前一轮真实本机验收发现

执行前备份：

```text
backup: $REPO/private/agent/data/backups/agent_history-2026-07-05-161119.db
sha256: 844de86e6dba012f2e31f93af4797ab9c1775be18ac6b83d6f1face15b8dc0a0
```

标准 manager run：

```text
real_accept_chat_candidates_20260705  daily_ingest_and_review  completed
real_accept_chat_auto_20260705        auto_review_only          completed
```

输出摘要：

```text
[generate_candidates] 2026-07-05: 12 upserted, 12 candidates
[auto_review] 2026-07-05: accepted=0, pending=0, skipped=12
```

DB 结构性结果：

```text
chat_message|adr|pending|3
chat_message|card|pending|6
chat_message|daily|pending|3
source_documents source_type=chat_message: 7
```

Candidate markdown 结构：

```text
candidate_file_exists: True
candidate_file_lines: 418
chat_source_mentions: 12
message_trace_mentions: 12
sections: DAILY=1, ADR=1, CARD=1
```

结论：这轮证明了 chat-derived knowledge 可以进入人工 review 且不会自动落地，但也暴露出 question-based 提炼质量不足。因此已在本轮改为 answer-based 提炼；后续真实重跑应期望 `chat_response/chat-answer-v2` 取代上述 `chat_message/chat-claim-v1` 结果。

### 12.4 Answer-based 真实本机复验

执行前备份：

```text
backup: $REPO/private/agent/data/backups/agent_history-2026-07-05-162924.db
sha256: 4fb84e7277e2e7917b754137d09c0fa97bde66d260f32deb828b4a0c391288d1
```

最终复验 run：

```text
real_accept_chat_response_candidates_v3_20260705  daily_ingest_and_review  completed
real_accept_chat_response_auto_v3_20260705        auto_review_only          completed
```

输出摘要：

```text
[generate_candidates] 2026-07-05: 101 upserted, 101 candidates
[auto_review] 2026-07-05: accepted=0, pending=0, skipped=101
```

DB 结构性结果：

```text
chat_response|adr|pending|64
chat_response|card|pending|8
chat_response|daily|pending|29
source_docs|chat_response|chat-answer-v2|6
role_meta|101
background_meta|101
```

Candidate markdown 结构：

```text
candidate_file_exists: True
candidate_file_lines: 2499
source_chat_response_lines: 101
source_chat_message_lines: 0
message_trace_mentions: 101
background_lines: 101
```

Claim artifact 结构性核对：

```text
source_type_chat_message_mentions: 0
source_type_chat_response_mentions: 0
source_kind_chat_response_mentions: 128
background_prompt_mentions: 128
```

结论：现行 chat candidates 已改为从 assistant replies 提炼，用户提问只作为 background；旧 `chat_message/chat-claim-v1` 投影不再出现在 candidate markdown，也不会被 source claim/candidate iterator 二次处理。所有 chat-derived candidates 仍保持 pending，并在 auto-review 中 skipped。

最终测试门禁：

```text
Data Hub subset: 120 passed, 1 skipped, 252 deselected in 1.82s
make check: 364 passed, 9 skipped, 1 warning in 32.96s
coverage: 81.99% >= 80%
warning: tests/test_lifecycle_manager_cli.py::test_main_delegates_status_command reports an unclosed sqlite3 ResourceWarning; non-blocking and unrelated to chat response extraction.
```
