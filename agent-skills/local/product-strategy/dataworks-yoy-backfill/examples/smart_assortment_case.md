# 智能组货 YoY 可比店修复实战案例

## 背景

工作流 10002308897（智能组货） YoY 可比店漂移问题：

- **漂移原因**：原始链路按各 `event_date` 独立取 `is_content_vs_store`（`b.stat_date=dd.ly_day_id`），导致前端勾选同店对比时本期(158xx)与去年同期(129xx)门店池相差 2920 店（18% 缺漏），同比虚高。
- **修复方案**：在中间预聚合层（node_10002308898）新增 `vs_cohort` CTE，从昨日快照固定取 `is_content_vs_store_benchmark`，用 `COALESCE(v.is_content_vs_store_benchmark, 0)` 覆盖原字段，后续 grouping sets 与下游 trend/detail 自动继承同店锚定。
- **验证**：同一 `stat_date` 分区同时查 `event_date=stat_date` 与 `event_date=ly_day_id` 且 `is_content_vs_store_cd=1`，门店配对率应达 99.96%+。

## 批量回刷需求

需回刷 **20241120~20260809 共 628 天**：

- **弃用方案**：DataWorks DAG 逐日补数（3min/天 ≈ 32h）
- **采用方案**：MaxCompute SDK 并发 Multi-Table INSERT
  - 单 SQL 纯 CTE 同时写 `dsl_analysis.ads_prov_region_stat_cata_trend_detail_df` 与 `ads_prov_region_stat_cata_detail_df`
  - 无 `dsl_tmp` 临时表锁
  - 按 8 自然季度倒序切片（新→旧）
  - 16 并发
  - 分区存在性预检跳过（断点续传）
  - **实测**：平均 6s/天，全量约 25-30 分钟

## 执行脚本示例

```python
#!/usr/bin/env python3
"""智能组货工作流 YoY 可比店修复批量回刷（628 天）."""

from shared.dataworks_batch_backfill import generate_date_range, run_batch

# 8 个自然季度（倒序：新→旧）
QUARTERS = [
    ("2026 Q3 (0701~0809)", "20260701", "20260809"),
    ("2026 Q2 (0401~0630)", "20260401", "20260630"),
    ("2026 Q1 (0101~0331)", "20260101", "20260331"),
    ("2025 Q4 (1001~1231)", "20251001", "20251231"),
    ("2025 Q3 (0701~0930)", "20250701", "20250930"),
    ("2025 Q2 (0401~0630)", "20250401", "20250630"),
    ("2025 Q1 (0101~0331)", "20250101", "20250331"),
    ("2024 Q4 tail (1120~1231)", "20241120", "20241231"),
]

def build_sql(stat_date: int) -> str:
    """单日纯 CTE Multi-Table INSERT."""
    return f"""
WITH vs_cohort AS (
  SELECT store_code, is_content_vs_store AS is_content_vs_store_benchmark
  FROM dsl_ads.ads_item_content_store_all_stat
  WHERE stat_date = {stat_date - 1}
),
base AS (
  SELECT
    t1.region_man_code,
    t1.store_code,
    COALESCE(v.is_content_vs_store_benchmark, 0) AS is_content_vs_store,
    ...
  FROM dsl_ads.ads_item_3he1_db_1_6_store_item_xiafa_df t1
  LEFT JOIN vs_cohort v ON t1.store_code = v.store_code
  WHERE t1.stat_date = {stat_date}
)
-- Multi-Table INSERT
INSERT OVERWRITE TABLE dsl_analysis.ads_prov_region_stat_cata_trend_detail_df
PARTITION (stat_date = {stat_date})
SELECT ... FROM base WHERE ...;

INSERT OVERWRITE TABLE dsl_analysis.ads_prov_region_stat_cata_detail_df
PARTITION (stat_date = {stat_date})
SELECT ... FROM base WHERE ...;
"""

if __name__ == "__main__":
    for q_name, start, end in QUARTERS:
        print(f"\n{'='*60}\n开始回刷: {q_name}\n{'='*60}")
        result = run_batch(
            quarter_name=q_name,
            start_date=start,
            end_date=end,
            sql_builder=build_sql,
            partition_tables=[
                "ads_prov_region_stat_cata_trend_detail_df",
                "ads_prov_region_stat_cata_detail_df",
            ],
            odps_project="dsl_analysis",
            workers=16,
        )
        print(f"✓ {q_name}: {result}")
```

## 验证结果

ODPS 实查验证：
- 门店配对率 99.96%+（20241120~20260809 所有分区）
- 全仓 pytest 通过：`test_smart_assortment_sql.py`
- 全局索引同步更新

## 沉淀位置

- 脚本：`topics/smart_assortment/03_analysis/scripts/quarter_batch_backfill.py`
- 测试：`topics/smart_assortment/03_analysis/scripts/test_smart_assortment_sql.py`
- 全局索引：`portfolio/topic_index.md`
