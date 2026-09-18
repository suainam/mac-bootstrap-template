# 新店 90 天考核期与目录销售占比深度归因指南
(Assessment Period vs. Catalog Sales Playbook)

## 核心认知与口径对齐

1. **宏观供应链宽表口径 (`tmp_ads_item_content_store_summary_df`)**：
   - 字段：`sale_amt_all` 与 `sale_amt_ct` 是固定将近 90 天所有流水除以 **90 天平摊**。
   - 特点：新店在开业活动大促期间（通常为开业首周 6 天）的爆发性销售会被全额计入分子。对于刚开业 20 多天的新店，由于包含了大促暴卖的核心药品，容易算出生效高达 90%+ 的目录内销售占比，且推算的累积销售额远超常规期实际金额。
2. **营运 90 天考核口径 (`analysis_new_store_90d_assessment_df`)**：
   - 契约：开业活动期（如 08.14 ~ 08.19）在营运考核中**完全剔除**，考核自大促结束次日（`s_kh = 08.20`）起算。
   - 特点：只核算常规经营期实际发生的流水（如 19 天约 2.7 万元）。
3. **穿透事实表计算考核期真实目录销售占比**：
   - 依赖表：`dsl_ads.ads_sale_store_item_metrics_sum_di`（过滤 `is_fwl = 'N'`）联合 `dsl_ads.ads_item_store_content_day_stat_sale`（获取目录标记 `is_content_item = 1`）。
   - 结论：剔除大促后，新店在常规考核期内的目录内真实销售占比通常在 **75% ~ 82%** 之间，处于直营大盘健康区间，并非宽表显示的 91%+。
