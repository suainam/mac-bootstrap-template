---
name: analytics-demand-analysis
description: Profile analytics data, verify warehouse schemas and lineage, audit priority masking, and lock metrics, grain and comparison baselines.
---

# 阶段二：需求分析

## 进入阶段

读取 [共享契约](../analytics-demand-analysis/references/ANALYSIS_CONFIRMATION_CONTRACT.md)：继承已确认范围与稳定资产身份，按六栏交付，技术事实自行查证，只确认新增业务选择。按当前任务进入本阶段，复用已有上游产物。

## 执行步骤

### 1. 读取专题基线

先读专题 README、00_context、已有 SQL/脚本与历史交付，复用已验证公式、字段映射与口径。按 [画像清单](references/profiling_checklist.md) 制定本次查证项。

完成标准：列出复用资产、权威来源和本次差异。

### 2. 查证表、分区与血缘

使用 `scripts/dmp_mcp_client.py` 查表结构，`scripts/dataworks_lineage.py` 追踪源头；命令参数以工具帮助为准。实测每张依赖表的存在性、有效业务分区、主键和关联基数。维表或编码语义不明时读 [维表治理](references/DIM_DICTIONARY_GOVERNANCE.md)。资产编码基数很低仅是型号编码疑点，须核对字段定义和实例样本后决定去重键。

涉及综合原因或模型优先级时读 [掩盖排查](references/MULTI_MODEL_MASKING_AUDIT.md)；季节性穿透可参考 [SQL 样例](examples/01_pure_premature_seasonal_audit.sql)，按本次快照与 NULL 契约替换历史常量。

完成标准：全部依赖表、键、分区和未匹配处置有证据；相关生产节点版本与顺位可追溯。

### 3. 复现事实并锁定口径

只读复现需求中的数字与假设，记录差异。锁定指标公式、业务理由、NULL/零/负值语义，固化行数、主键数、数量金额及适用实体数。比较前对齐日期、范围与指标；不能对齐时披露限制。

比例同时报告分子、分母、百分点差及每实体数量；合并比例用 `SUM(分子)/SUM(分母)`。候选量、最终建议量与全量明细量分开。只有比例和标准化绝对量均支持时才称构成相近。

新店效益：分别画像活动期、考核期和日常期，对照店使用同一日期闭区间。配置变更：保存线上完整配置快照，查证组织仓库映射、重叠规则、排除顺序、共享约束及新增/停用差异。

完成标准：每个指标有公式、范围、基线与来源；每项业务前提已复现或明确证据不足。

### 4. 确认并交接口径

按 [假设日志](references/analysis_assumptions_log.md) 记录新增业务选择；按 [锁定卡模板](templates/caliber_lock_template.md) 输出事实核验、指标理由、适用的纵横向比较与阶段三指引。版本/来源/预测分解时读 [八格参考](references/EIGHT_CELL_AUDIT_REFERENCE.md)。

完成标准：技术事项已查证，口径确认可追溯；依赖未决业务选择的部分明确标为阻断，其余继续交付。

## 阶段验收

按共享契约 §2 的本阶段门槛逐项附证据，并执行 §2.0 产物审查。适用门禁全部通过、阻断为零才宣布完成；未验证项如实列明。中文业务正文按 `humanizer-zh` 润色，保留数字、口径与证据。
