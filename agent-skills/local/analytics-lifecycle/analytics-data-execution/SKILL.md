---
name: analytics-data-execution
description: Run analytics queries, local models, ingestion, partition backfills or configuration changes; reconcile outputs and verify materialized assets.
---

# 阶段四：数据分析执行

## 进入阶段

读取 [共享契约](../analytics-demand-analysis/references/ANALYSIS_CONFIRMATION_CONTRACT.md)：继承已确认范围与稳定资产身份，按六栏交付，技术事实自行查证，只确认新增业务选择。按当前任务进入本阶段，复用已有上游产物。

## 执行步骤

### 1. 锁定环境、资产与执行分支

读取 [质量契约](references/DATA_QUALITY_CHECKLIST.md)。复用项目 `shared.config`、`shared.odps_connector` 与数据湖设施，从项目约定凭据源加载秘密。轻量 PyODPS 查询可用 `uv run --with pyodps --no-project`；计算项目使用已授权配置，中间表仅写开发临时库、携带专题标识并约定清理。

完成标准：输入快照、稳定目标路径、写入范围、门禁及恢复方式明确。

### 2. 执行选定分支

- 查询：按锁定粒度提取；仅店品分析且需穿透对账时输出店品明细和门店汇总两层。元数据探查可用 `scripts/odps_quick_probe.py`，先核对其分区选择是否适用本次业务日期。
- 本地模型：运行阶段三已验证的专题脚本，复用因果求解器、效益测算与基准核验入口。
- 本地入仓：读 [入仓流程](../../product-strategy/odps-table-ingest/SKILL.md)。
- 历史回刷：读 [回刷流程](../../product-strategy/dataworks-yoy-backfill/SKILL.md)，分区并发与跳过策略按该流程执行。
- 配置治理：读 [规则维护](../../product-strategy/ps-reduction-scope-config-maintenance/SKILL.md)。复核阶段二快照和阶段三差异，在开发库预演；按已有授权写入后回读主键、行数与未改规则，分别记录落库、代码、调度及结果状态、实例 ID 和业务分区。

完成标准：实际执行有命令、退出码及输出记录，失败定位到具体阶段。

### 3. 核验数据

运行 `scripts/audit_execution_sanity.py` 或对应内嵌断言；目录动作追加 `scripts/audit_action_reason_parity.py`。按方案核对行数、键、金额、集合、比率、NULL、来源与保护规则，记录不适用项理由。技术门禁和业务合理性分开记录。

- 用本期名单回溯历史：读 [回溯五问](references/cohort_backtrace_five_questions.md)。
- 版本/来源/预测分解：读 [八格门禁](../analytics-demand-analysis/references/EIGHT_CELL_AUDIT_REFERENCE.md)。
- 分批推广或重构：读 [三段回归](../analytics-data-solution/references/BATCH_ROLLOUT_REGRESSION_SOP.md)。
- SQL 空结果或异常：读 [差异诊断](references/SQL_DIFF_DIAGNOSIS_GUIDE.md)，先 diff，再用单键切片定位断点。
- 物理空间：按已确认密度阈值检查漏登、折叠与重复累计；异常先排查来源。

按大区/品类回查底层样本（通常 10–20 条，不足时全查），记录源分区与差异。配置结果额外核验范围、版本、容量、共享额度和历史量级；零结果先核对日期门禁与映射。

完成标准：适用断言全部通过，抽样差异已解释；测试收集、实际测试和生产查询明确区分。

### 4. 物化与回读

按质量契约先验证临时产物，再同名原子替换数据湖实体并核对仓库软链接；运行项目边界检查。质检报告记录实际大小、更新时间、解析结果、断言证据和业务解释。

完成标准：物理文件可解析且属于本次运行，软链接指向正确，报告与文件一致。产物存在本身不证明本次重跑。

## 阶段验收

按共享契约 §2 的本阶段门槛逐项附证据，并执行 §2.0 产物审查。适用门禁全部通过、阻断为零才宣布完成；未验证项如实列明。中文业务正文按 `humanizer-zh` 润色，保留数字、口径与证据。
