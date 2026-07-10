# Summary Engine Implementation Report

更新时间：2026-07-10
实施分支：`feature/data-hub-summary-engine`

## 基线

- 实施起点：`3c8bc03593e6114e7771e64e8217da2a7c977e49`（`docs(data-hub): plan structured summary engine`）。
- 当前设计链提交：`4d48d6a`、`4a0f740`、`257e041`、`3c8bc03`。
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

## 最终验收预留

- isolated DB/vault 的 Daily、Weekly、Monthly、Quarterly、Yearly 产物。
- 两次相同输入的 revision/row count 与 Markdown hash 对照。
- staged/file-published crash-window 恢复证据。
- 09:00、17:30、18:00 launchd plist 与中国工作日/节假日/调休/周期边界试跑。
- focused pytest、全量 pytest、`make check`、`make privacy-audit` 与真实 llm_wiki 引用证据。
