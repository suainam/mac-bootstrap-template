# Summary Engine Implementation Report

更新时间：2026-07-10
实施分支：`feature/data-hub-summary-engine`

目录迁移说明：本报告中的源码与测试路径已归一到当前 `data-hub/` 和 `agent-skills/` 目录；历史提交、测试输出和实施结论未改写。

## 基线

- 实施起点：`3c8bc03593e6114e7771e64e8217da2a7c977e49`（`docs(data-hub): plan structured summary engine`）。
- 当前设计与实施提交：`4d48d6a`、`4a0f740`、`257e041`、`3c8bc03`、`b48dd25`。
- 接手时测试基线：`560 passed, 9 skipped`，另有 `26` 个由 worktree layout 引起的失败；该结果来自实施计划交接，本 Task 未重跑全量基线。
- 已知基线门禁：worktree layout 会造成现有路径断言失败；privacy audit 留待最终真实验收统一复核，不在 Task 1 扩展范围。
- 实施期间 `.venv` 是指向主 template 环境的本地 symlink，仅用于执行测试，不进入版本控制。

## Task 1 — Versioned Summary Contracts and Taxonomy

状态：完成；本报告与 `feat(data-hub): add summary contracts` 同批提交。

### 产物

- `summary-output.schema.json`：`summary-v1`，按 Daily、Weekly、Monthly/Quarterly/Yearly 分支校验结构。
- `summary-dimensions.v1.json`：`dimensions-v1`，五类条目级能力维度及 include/exclude/examples。
- `summary-policy.v1.json`：`summary-policy-v1`，固化篇幅、洞察数、证据与高层 supporting item 门槛。
- `summary_contracts.py`：不可变 contract/evidence/document value objects、资产加载与交叉版本检查、schema/taxonomy/policy 校验、canonical JSON 与 input digest。
- `pyproject.toml` / `uv.lock`：新增 `jsonschema>=4.0` 及解析后的传递依赖。

### TDD 证据

RED：

```text
$ .venv/bin/python -m pytest tests/test_summary_contracts.py -q
ERROR tests/test_summary_contracts.py
ModuleNotFoundError: No module named 'summary_contracts'
1 error in 0.10s
exit: 2
```

失败原因符合预期：测试先于生产模块创建，collection 仅因 `summary_contracts` 尚不存在而失败。

GREEN：

```text
$ .venv/bin/python -m pytest tests/test_summary_contracts.py -q
.............                                                            [100%]
13 passed in 0.18s
exit: 0
```

覆盖范围：合法 Daily、非法/重复/超量维度、Daily 洞察数量、evidence group membership、占位内容、Weekly/Higher 必需支持字段、资产版本一致性、冻结 value objects、canonical JSON 与 input digest 稳定性。

### 风险与下一检查点

- Task 1 只定义 contract 边界；EvidencePacket 的确定性分组、实际 source-kind 充足性和 renderer 篇幅计数由后续任务接入 policy。
- `jsonschema` 已写入 lock；其他 worktree/环境需按 lock 同步依赖后才能导入 `summary_contracts`。
- 下一检查点是 Task 2 的 logical summary、immutable revision 与 recovery store；本提交不提前实现其表或持久化逻辑。

## Task 2 — Logical Summaries, Immutable Revisions, and Recovery Store

状态：完成；本报告与 `feat(data-hub): add revisioned summary store` 同批提交。

### 产物

- `schema.sql`：新增 logical summaries、immutable revisions、items、dimensions、evidence groups/sources、item evidence 与跨层 support 表；包含 FK、CHECK 与 unique 约束。
- `schema_migrations.py`：一次性把 legacy `summary_runs` / `summary_run_sources` 转为 legacy revision/evidence，随后在同一 migration transaction 删除旧表。
- `summary_store.py`：提供 deterministic IDs、idempotent staging、revision document load、published lookup、full-file SHA-256、`staged -> file_published -> published` 状态机和 recovery API。
- `db_helper.py`：连接初始化改用 revision schema migration，并允许测试显式传入临时 DB 路径。
- `test_summary_publish_recovery.py`：覆盖 replace 后 DB 未更新、file_published 未 finalize、未知 marker 和文件篡改。
- `test_data_hub.py`：仅补充 `data-hub/scripts` 测试 import path，使计划中的 worktree focused command 可执行；未改变生产行为。

### TDD 证据

RED：

```text
$ .venv/bin/python -m pytest tests/test_summary_store.py tests/test_summary_publish_recovery.py -q
ImportError: cannot import name 'ensure_summary_revision_schema'
ImportError: cannot import name 'SummaryStoreError'
2 errors in 0.18s
exit: 2
```

失败原因符合预期：revision migration 和 store/recovery API 在测试创建时尚不存在。

首次计划命令发现测试基础设施问题：

```text
$ .venv/bin/python -m pytest tests/test_summary_store.py tests/test_summary_publish_recovery.py tests/test_data_hub.py -q
ModuleNotFoundError: No module named 'ingest_logs'
1 error in 0.23s
exit: 2
```

根因是 `test_data_hub.py` 只加入 data-hub 根目录，但被测 legacy helper 位于 `scripts/`；按 Task 2 review 要求，仅修正测试 `sys.path` 后重跑 exact command。

GREEN：

```text
$ .venv/bin/python -m pytest tests/test_summary_store.py tests/test_summary_publish_recovery.py tests/test_data_hub.py -q
..................                                                       [100%]
18 passed in 1.00s
exit: 0
```

### 迁移与恢复证据

- 同一 `level + period` 两次 ensure 只产生一个 logical summary。
- 同一 `summary_id + input_digest` 两次 stage 只产生一个 revision，第二次不同 payload 不覆盖已存 document。
- legacy completed run 转为 `contract_version=legacy`、`publish_status=published` revision；source row 转为 evidence group/source；旧两表删除。
- migration 重跑后 revision 数仍为 1，证明一次迁移幂等。
- `current_revision_id` 在 staged 阶段保持空，仅 full-file hash 校验通过并 finalize 后切换。
- replace 后 DB 仍 staged 时，可从 artifact marker + full-file SHA-256 恢复；file_published 文件被篡改时拒绝 finalize。

### 风险与下一检查点

- Task 2 只提供 Task 5 所需 recovery API，不实现 renderer 或 atomic replace。
- legacy artifact 没有可追溯的历史 full-file hash，因此迁移 revision 的 `artifact_hash` 保持空；新 revision 强制使用完整文件 SHA-256。
- `source_ingest_store` 暂通过旧函数名桥接到新 migration，避免本 Task 扩展调用方修改；删除旧 runtime 路径与命名由计划中的统一调用链迁移任务完成。
- `tests/test_period_summary.py` 仍编码旧 `summary_runs` 表行为，需随 period orchestrator 重写任务迁移，不能作为新 store 契约继续保留。

## Task 3 — Cited Evidence Collection and llm_wiki Deep Research

状态：完成；待与本 Task 的代码一起提交。

### 产物

- `llm_wiki_client.py`：新增 `chat(message, mode="deep")`，调用项目级 `/chat` API；该接口只返回上下文证据，Data Hub 不把选择和渲染职责让渡给 llm_wiki。
- `summary_evidence.py`：把本地 Daily/ADR/Card、未解决 candidate 与 llm_wiki citations 标准化为确定性的 evidence groups；group ID 由规范化 payload/source refs 哈希而来，不依赖模型生成身份。
- `summary-evidence-research.md`：明确 Deep Chat 只能提供可追溯资料，`70_Summaries/` 永远不能作为 primary evidence。
- `test_llm_wiki_client.py` / `test_summary_evidence.py`：覆盖请求 contract、确定性、摘要反向引用过滤与不可用时的 degraded 语义。

### 验证

```text
$ .venv/bin/python -m pytest tests/test_llm_wiki_client.py tests/test_summary_evidence.py -q
....                                                                     [100%]
4 passed in 0.12s
exit: 0
```

### 风险与下一检查点

- Deep Chat 的网络、认证与具体引用质量属于运行时条件；采集器将异常显式降级为 `quality_status=degraded`，后续编排层必须把它写入摘要状态，不能静默伪造完整性。
- Task 3 只产出 evidence packet，不生成 JSON 摘要或 Markdown；筛选、篇幅和洞察证据门槛由 Task 4/5 执行。

## Task 4 — Contract-First Synthesis

状态：完成；待与本 Task 的代码一起提交。

### 产物

- 重写 Daily/Weekly prompt，并新增 `higher-period-summary.md`；三者都注入 schema、taxonomy、policy 和 evidence packet，只允许 JSON 输出。
- `summary_synthesis.py`：按 level 选 prompt、调用统一 backend、解析 JSON、按 contract/evidence group 校验；首次失败附带校验错误重试一次，第二次失败显式报错。
- `chat_review.md`：候选抽取增加可控维度 hint 与 evidence refs，但不把 suggestion 升格为 accepted knowledge。
- `test_summary_synthesis.py`：覆盖五层 prompt 路由及 invalid JSON 的单次 repair retry。

### 验证

```text
$ .venv/bin/python -m pytest tests/test_summary_synthesis.py tests/test_candidate_review.py tests/test_llm_filter.py -q
................................................                         [100%]
48 passed in 0.74s
exit: 0
```

### 风险与下一检查点

- `summary_synthesis` 是纯结构化生成层，不做 Markdown 字符计数、文件写入或 SQLite 状态转换；这些由 renderer/publisher 完成。
- 真实 backend 可接受 `BackendRequest` 或最小 `generate(prompt)` fake；生产路径由编排层选择已配置 backend，避免在 contract 层绑定私有模型配置。

## Task 5 — Deterministic Markdown Projection

状态：完成；待与本 Task 的代码一起提交。

- `summary_renderer.py` 只投影结构化 document：frontmatter 保留 revision/input digest，正文明确分出“工作进展”和“知识洞察”，每个条目内联能力维度标签与 evidence group ID。
- 没有合格 insight 时固定写“今日无新增高价值洞察。”；renderer 不读来源、不访问数据库、不调用 LLM。
- 验证：`.venv/bin/python -m pytest tests/test_summary_renderer.py tests/test_summary_publish_recovery.py -q` → `6 passed in 0.27s`。

## Task 8（完成）— 定时自动化

- 已把 launchd evening 从 18:30 校正至 18:00，并把 17:30 从裸 `osascript` 改为 `daily_reminder.sh`，让提醒也受 `chinese_calendar` 工作日门禁控制。
- `daily_morning.sh` 同样使用 `summary_calendar.should_run_scheduled_event()`，因此普通周末、法定节假日跳过，调休工作日执行；晚间调度仍每天触发。
- `planned_workflows()` 查询 SQLite current lower revision，只在边界覆盖不足时补入 lower workflow；非工作日边界不制造 Daily，执行顺序固定为 Daily → Weekly → Monthly → Quarterly → Yearly。

## Task 6/7（完成）— Revision Orchestration 与旧路径清理

- `summary_inputs.py` 已改为只查询 SQLite 的 published lower revisions，禁止读取下层 Markdown 正文；`period_summary.py` 改为 coverage-aware revision orchestrator，并使用 staged → file_published → published 状态机。
- `scripts/daily_summary.py`、旧 lifecycle stage 及其 runtime skill caller 已移除；workflow 统一经 `build_<level>_summary`，并识别 `SUMMARY_STATUS=degraded`。
- 定向回归：period/input/CLI `5 passed`；workflow degraded/lifecycle `27 passed`；隔离 Daily build 走完 evidence → JSON contract → SQLite revision → atomic artifact publish，`3 passed`。

## Post-review Hardening

- EvidencePacket 现行来源包含有正文的原始 Daily、Git commit、accepted knowledge record、accepted candidate 与 llm_wiki citations；pending open loop 只能作为风险上下文，不能满足 Daily work evidence 门槛。
- `resolve_lower_revisions()` 会逐个校验 `lower period ∩ higher period ∩ deployment range` 的 published coverage；缺失时失败，不读取下层 Markdown 正文。
- Daily 使用“今日结论 / 工作进展 / 风险与下一步 / 知识洞察 / 来源”；Weekly 固定输出本周结论、成果、决策、趋势、风险、下周重点、知识演进、能力维度与 Daily wikilink 索引。
- 篇幅校验与 renderer 的 headline/title/conclusion/value/trend/period_change 正文域同源；Daily 800–1200、Weekly 1200–1800 在 publish 前强制检查。
- 五层隔离 E2E 已覆盖 Daily → Weekly → Monthly → Quarterly → Yearly，以及相同 input digest 重跑时 revision count、revision ID 与 Markdown hash 均不变化。

验证：

```text
$ .venv/bin/python -m pytest \
    tests/test_summary_contracts.py tests/test_summary_store.py \
    tests/test_summary_publish_recovery.py tests/test_llm_wiki_client.py \
    tests/test_summary_evidence.py tests/test_summary_synthesis.py \
    tests/test_summary_renderer.py tests/test_summary_inputs.py \
    tests/test_period_summary.py tests/test_build_period_summary_cli.py \
    tests/test_summary_calendar.py tests/test_summary_schedule.py \
    tests/test_daily_workflows.py tests/test_lifecycle_manager_adapters.py \
    tests/test_summary_engine_e2e.py -q
........................................................................ [ 85%]
............                                                             [100%]
86 passed in 1.97s
```

### Final review closure

- Boundary replay 不再只读取 `current_revision_id`：resolver 查询全部 published lower revisions，并优先选择 `coverage_end == required_end` 的 immutable boundary snapshot。
- Renderer 通过 evidence group 映射展示 canonical source refs：vault Markdown 使用 wikilink，`commit:` / `record:` / `candidate:` 使用紧凑代码引用；不再把 `evg_*` 当作用户可读来源。
- Higher item 的 `supporting_item_ids`、`lower_summary_refs` 与 item→revision ref 映射同时校验，模型不能引用无关 Daily/Weekly。
- Weekly `跨日趋势` 只渲染 trend prose，不重复完整 item，篇幅 validator 与实际 narrative 字段保持一一对应。
- 五层 E2E 第二轮逐层重跑；任何 backend 调用都会使测试失败，并对全部 revision IDs、artifact hashes 及 summary 相关表 row counts 做相等检查。
- Higher replay 先读取已发布 higher revision 的 `summary_item_support` lineage；即使同一 lower period 后续发布相同 coverage revision，也继续使用原 boundary snapshot。首次选择则按 exact coverage、最早 published_at 稳定排序。
- 每个 higher item 的 `lower_summary_refs` 必须与 `supporting_item_ids` 推导出的 refs 完全相等，既不能缺失也不能附加无 supporting item 的索引链接。
- 五层 no-body-copy 验收使用每个真实 lower artifact 独有的正文标记，逐层断言所有 higher artifacts 均不包含任何 lower body marker。

## 最终验收预留

- isolated DB/vault 的 Daily、Weekly、Monthly、Quarterly、Yearly 产物。
- 两次相同输入的 revision/row count 与 Markdown hash 对照。
- staged/file-published crash-window 恢复证据。
- 09:00、17:30、18:00 launchd plist 与中国工作日/节假日/调休/周期边界试跑。
- focused pytest、全量 pytest、`make check`、`make privacy-audit` 与真实 llm_wiki 引用证据。
