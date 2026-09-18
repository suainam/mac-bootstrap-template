# YoY 可比店同店漂移修复与并发回刷契约

## 一、YoY 可比店漂移机制与根因

1. **漂移根因**:
   - 智能组货原始链路中，可比店标记 `is_content_vs_store` 随历史各 `event_date` 动态独立取值（`b.stat_date = dd.ly_day_id`）。
   - 导致前端勾选 `is_content_vs_store_cd = 1` 时，本期（如 15,800+ 店）与去年同期（12,900+ 店）门店池出现数千家不对齐（缺漏率高达 18%），同比被虚高失真。
2. **最小侵入修复范式**:
   - 在预聚合节点（如 `node_10002308898`）新增 `vs_cohort` CTE：
     ```sql
     vs_cohort as (
         select store_code, is_content_vs_store as is_content_vs_store_benchmark
         from dsl_ads.ads_item_content_store_all_stat
         where stat_date = ${yyyyMMdd-1d}
     )
     ```
   - 使用 `COALESCE(v.is_content_vs_store_benchmark, 0)` 覆盖原动态字段；
   - 下游 grouping sets 与趋势明细表自动继承锚定，无需重构整条数仓 DAG。

---

## 二、并发回刷核心契约（性能与防爆仓）

1. **反模式警示**:
   - 严禁用 DataWorks 界面 DAG 逐日串行补数（约 3min/天，600 多天需耗费 30+ 小时，易中断）。
   - 严禁用单条 SQL 跨多日动态分区（`PARTITION (stat_date) ... WHERE stat_date IN (...)` 极易引发 N×N 笛卡尔积导致集群 OOM）。
2. **标准回刷架构**:
   - **纯 CTE Multi-Table INSERT**: 单条 SQL 同时写入所有目标表，杜绝中间临时表锁与重算。
   - **单日单任务 + 线程池并发**: 16 并发，平均 ~6s/天，全量 628 天压缩至 25~30 分钟内完成。
   - **自然季度切片 + 倒序执行**: 按季度新 $\rightarrow$ 旧倒序推进，优先产出最新业务数据。
   - **分区存在性预检 (断点续传)**:
     - 每次执行前通过 MaxCompute SDK 读取目标表的已有 `partitions`；
     - 若当前日期分区已存在且完整，秒级跳过，支持随时无损断点续跑。

---

## 三、对抗性验收门禁

回刷完成后必须通过以下检验：
1. **配对率检验**:
   对同一 `stat_date` 分区同时查询 `event_date = stat_date` 与 `event_date = ly_day_id` 且 `is_content_vs_store_cd = 1`，门店两两配对率必须 $\ge 99.96\%$。
2. **分区分派断言**:
   每个目标表的分区总数和日期连续性必须 100% 覆盖回刷区间，且各分区行数无空跑或突降。
