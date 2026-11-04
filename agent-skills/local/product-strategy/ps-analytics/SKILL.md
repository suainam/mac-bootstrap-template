---
name: ps-analytics
description: 旧数据分析入口；内容已归入 analytics 生命周期五阶段。
disable-model-invocation: true
---

# 已迁移

按当前任务读取对应阶段；已有确认与产物直接继承。

- [analytics-demand-intake](../../analytics-lifecycle/analytics-demand-intake/SKILL.md)
- [analytics-demand-analysis](../../analytics-lifecycle/analytics-demand-analysis/SKILL.md)
- [analytics-data-solution](../../analytics-lifecycle/analytics-data-solution/SKILL.md)
- [analytics-data-execution](../../analytics-lifecycle/analytics-data-execution/SKILL.md)
- [analytics-result-delivery](../../analytics-lifecycle/analytics-result-delivery/SKILL.md)

旧脚本与样例保留兼容路径；新任务使用下列阶段资产。旧样例中的具体表、日期、NULL 默认值与输出路径须按本次口径替换，质量契约优先。

| 旧资产 | 权威归属 | 核对结果 |
|---|---|---|
| `references/MULTI_MODEL_MASKING_AUDIT.md` | [analytics-demand-analysis/references/MULTI_MODEL_MASKING_AUDIT.md](../../analytics-lifecycle/analytics-demand-analysis/references/MULTI_MODEL_MASKING_AUDIT.md) | 采用阶段现有版本（质量契约优先） |
| `references/ODPS_OPTIMIZATION_RULES.md` | [analytics-data-solution/references/ODPS_OPTIMIZATION_RULES.md](../../analytics-lifecycle/analytics-data-solution/references/ODPS_OPTIMIZATION_RULES.md) | 采用阶段现有版本（质量契约优先） |
| `references/BATCH_ROLLOUT_REGRESSION_SOP.md` | [analytics-data-solution/references/BATCH_ROLLOUT_REGRESSION_SOP.md](../../analytics-lifecycle/analytics-data-solution/references/BATCH_ROLLOUT_REGRESSION_SOP.md) | 已有同内容 |
| `references/DATA_QUALITY_CHECKLIST.md` | [analytics-data-execution/references/DATA_QUALITY_CHECKLIST.md](../../analytics-lifecycle/analytics-data-execution/references/DATA_QUALITY_CHECKLIST.md) | 采用阶段现有版本（质量契约优先） |
| `references/SQL_DIFF_DIAGNOSIS_GUIDE.md` | [analytics-data-execution/references/SQL_DIFF_DIAGNOSIS_GUIDE.md](../../analytics-lifecycle/analytics-data-execution/references/SQL_DIFF_DIAGNOSIS_GUIDE.md) | 迁入 |
| `references/CIRCULAR_SEASON_PARSER.md` | [analytics-result-delivery/references/CIRCULAR_SEASON_PARSER.md](../../analytics-lifecycle/analytics-result-delivery/references/CIRCULAR_SEASON_PARSER.md) | 迁入 |
| `scripts/odps_quick_probe.py` | [analytics-data-execution/scripts/odps_quick_probe.py](../../analytics-lifecycle/analytics-data-execution/scripts/odps_quick_probe.py) | 已有同内容 |
| `scripts/format_circular_months.py` | [analytics-result-delivery/scripts/format_circular_months.py](../../analytics-lifecycle/analytics-result-delivery/scripts/format_circular_months.py) | 迁入 |
| `scripts/test_analytics_skill.py` | [analytics-result-delivery/scripts/test_analytics_skill.py](../../analytics-lifecycle/analytics-result-delivery/scripts/test_analytics_skill.py) | 迁入 |
| `examples/01_pure_premature_seasonal_audit.sql` | [analytics-demand-analysis/examples/01_pure_premature_seasonal_audit.sql](../../analytics-lifecycle/analytics-demand-analysis/examples/01_pure_premature_seasonal_audit.sql) | 迁入 |
| `examples/02_export_excel_with_dedup.py` | [analytics-result-delivery/examples/02_export_excel_with_dedup.py](../../analytics-lifecycle/analytics-result-delivery/examples/02_export_excel_with_dedup.py) | 迁入 |
