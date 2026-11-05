---
name: analytics-data-solution
description: Design analytics RFCs, SQL and table contracts, checkpoint pipelines, configuration migrations and reconciliation gates.
---

# 阶段三：数据方案

## 进入阶段

读取 [共享契约](../analytics-demand-analysis/references/ANALYSIS_CONFIRMATION_CONTRACT.md)：继承已确认范围与稳定资产身份，按六栏交付，技术事实自行查证，只确认新增业务选择。按当前任务进入本阶段，复用已有上游产物。

## 执行步骤

### 1. 定义目标与分支

从锁定卡列出可验收目标、范围和 Non-Goals。新店效益区分成熟考核轨与筹备备货轨；试点台账只覆盖试点，全国分母使用系统主档并披露差异。

完成标准：每项目标对应输出及验收方式，业务分支明确。

### 2. 设计数据流与字典

复杂关联用 Mermaid 表达输入表、分区、计算层与门禁。字典列出物理字段、类型、中文名、公式、来源与缺失语义。目录增删读 [质量契约](../analytics-data-execution/references/DATA_QUALITY_CHECKLIST.md)：动作计算一次，原因消费动作，展示与判定同源，保护标签与待核验状态独立保留。

完成标准：每个输出字段可追溯到唯一计算节点，关联基数及未匹配处置明确。

### 3. 编写方案与 SQL

按 [RFC 模板](templates/rfc_technical_design_template.md) 与 [SQL 模板](templates/sql_solution_template.sql) 输出。读取 [ODPS 规约](references/ODPS_OPTIMIZATION_RULES.md)；复杂多阶段任务表间用开发库 checkpoint，表内用局部 CTE。库名、快照和版本参数化；增补候选前置核对仓店在营与履约状态。除法显式处理零分母。

配置变更：设计完整列序的新增/保留/停用差异、写入方式、快照恢复及并发基线复核；新增维度同步 DDL、全部配置行、消费 SQL、调用方和示例。业务常量留在专题真源。

完成标准：方案含数据流、字段契约、可审阅差异及恢复办法；SQL 静态扫描 `scripts/odps_sql_linter.py` 为 0 errors，执行可行性另列证据。

### 4. 定义执行门禁

逐目标设计主键、集合/金额守恒、比率范围及 NULL 断言。目录分支追加标记原因互斥、保护不穿透及目录内外守恒；版本/来源/预测分解读 [八格参考](../analytics-demand-analysis/references/EIGHT_CELL_AUDIT_REFERENCE.md)；分批推广或重构读 [三段回归](references/BATCH_ROLLOUT_REGRESSION_SOP.md)。

完成标准：每条门禁有输入、预期值/容差和失败处置，阶段四可直接执行。

## 专题参考

- 新店考核：读 [效益指标](references/domain_blueprints/new_store_benefit_metrics_contract.md) 与 [考核规则](references/domain_blueprints/new_store_assessment_rules_contract.md)，核对实际到店分母并单列履约缺损。
- O2O 同品池：读 [O2O 蓝图](references/domain_blueprints/o2o_store_benefit_reference.md)。
- 加盟店大盘与桑基：读 [市场基准](references/domain_blueprints/franchise_market_baseline_contract.md)。
- 因果评估：读 [因果方案](../../product-strategy/ps-causal-evaluation/SKILL.md)。
- 陈列编码或空间组团：分别读 [编码规约](references/BUSINESS_DISPLAY_CODE_GRAMMAR.md)、[吸附架构](references/CLUSTER_SNAPPING_ARCHITECTURE.md)。

## 阶段验收

按共享契约 §2 的本阶段门槛逐项附证据，并执行 §2.0 产物审查。适用门禁全部通过、阻断为零才宣布完成；未验证项如实列明。中文业务正文按 `humanizer-zh` 润色，保留数字、口径与证据。

专题执行交接：新店读 [新店报告](../../product-strategy/ps-new-store-benefit-report/SKILL.md)，O2O 读 [O2O 报告](../../product-strategy/o2o-store-benefit-report/SKILL.md)，加盟店读 [加盟店报告](../../product-strategy/ps-franchise-store-report/SKILL.md)；配置设计读 [规则维护](../../product-strategy/ps-reduction-scope-config-maintenance/SKILL.md)。业务口径以本阶段蓝图和已确认契约为准。
