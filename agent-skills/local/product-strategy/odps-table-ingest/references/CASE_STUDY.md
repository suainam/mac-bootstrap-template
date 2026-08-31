# ODPS 表导入典型实战案例 (Case Studies)

---

## 案例 1：退货剩余库存全量导入（全量直接导入模式）

### 1. 业务背景与源数据
- **源文件**：`<topic_dir>/01_source_data/退货剩余清单-260825.xlsx`
- **文件状态**：带有 `%TSD-Header-###%` 加密头，macOS 下通过 Python/openpyxl 透明读取明文。
- **本地物化**：导出为 `02_working_data/退货剩余清单-260825_Sheet1_20260826.csv`，源文件 SHA-256 保持不变。
- **源数据画像**：
  - 总行数：39,289 行（无空行）
  - 覆盖范围：533 家门店、1,218 个商品
  - 核心指标：批号库存数量合计 `82,467`，批号库存金额合计 `3,204,540.08` 元
  - 主键唯一性：`store_code + item_code + lot` 39,289 唯一无重复

### 2. 线上探查与字段对齐
- **目标表**：`<project>.analysis_reduction_store_unsalable_high_inventory_returns_df`
- **目标分区**：`stat_date=20260826`
- **对齐映射**：
  - `store_code` (STRING 10位补零) ← `门店编码`
  - `item_code` (BIGINT) ← `商品编码`
  - `lot` (STRING) ← `批号`
  - `st_qty` (DOUBLE) ← `批号库存数量`
  - `store_item_lot_merge` (STRING) ← `店品批`
  - `st_amt` (DOUBLE) ← `批号库存金额`

### 3. 事后 ODPS 聚合 SQL 举证
```sql
SELECT
    COUNT(1) AS row_cnt,
    SUM(st_qty) AS sum_qty,
    ROUND(SUM(st_amt), 2) AS sum_amt,
    COUNT(DISTINCT store_code) AS store_cnt,
    COUNT(DISTINCT item_code) AS item_cnt,
    COUNT(DISTINCT store_item_lot_merge) AS merge_cnt
FROM <project>.analysis_reduction_store_unsalable_high_inventory_returns_df
WHERE stat_date = 20260826;
```
* **对比结果**：行数 (39,289)、数量 (82,467.0)、金额 (3,204,540.08)、门店 (533)、商品 (1,218)、店品批 (39,289) **全部 100% 吻合**。

---

## 案例 2：缩铺批次清单导入与历史 Typo 表 RENAME 无损继承（Join 清单模式）

### 1. 业务背景与源数据
- **源文件**：`<topic_dir>/01_source_data/某区域缩铺0820第一批.xlsx`
- **业务定位**：某区域第一批下发的缩铺退货清单（供下游主流程按店品批 `INNER JOIN` 过滤第一批真实执行范围）。
- **本地物化画像**：
  - 总行数：`25,700` 行
  - 覆盖范围：`1,125` 家门店、`183` 个商品
  - 核心指标：批号库存数量合计 `49,233.00` 个，批号库存金额合计 `3,024,599.54` 元（302.46 万元）
  - 主键唯一性：`store_code + item_code + lot` 25,700 唯一无重复

### 2. 线上元数据探查与 Typo 表 RENAME 决策
- **发现**：线上历史表名为 `<project>.anslysis_reduction_store_unsalable_high_inventory_returns_df`（存在 `anslysis_` typo），且已包含 8 个历史生产分区。
- **决策树执行**：
  1. 严禁直接新建空表，否则历史 8 个分区会沦为孤立废弃资产；
  2. 执行 `ALTER TABLE <project>.anslysis_reduction_store_unsalable_high_inventory_returns_df RENAME TO analysis_reduction_store_unsalable_high_inventory_returns_df;`；
  3. 执行 `SHOW PARTITIONS` 确认历史 8 个分区全部在新表名下无损继承；
  4. 将本次 25,700 条数据写入新表名下的 `stat_date=20260822` 分区（使表总分区数达到 9 个）。

### 3. 事后 ODPS 聚合 SQL 举证
```sql
SELECT 
    stat_date,
    COUNT(1) AS row_cnt,
    SUM(st_qty) AS sum_qty,
    ROUND(SUM(st_amt), 2) AS sum_amt,
    COUNT(DISTINCT store_code) AS store_cnt,
    COUNT(DISTINCT item_code) AS item_cnt,
    COUNT(DISTINCT store_item_lot_merge) AS merge_cnt
FROM <project>.analysis_reduction_store_unsalable_high_inventory_returns_df
WHERE stat_date = 20260822
GROUP BY stat_date;
```
* **MaxCompute 返回结果**：`[20260822, 25700, 49233.0, 3024599.54, 1125, 183, 25700]`，与本地 6 项画像指标 **100% 绝对一致**。

### 4. 下游 INNER JOIN 与逐日异动走势印证
- **下游关联 SQL 范式**：
  ```sql
  SELECT t0.*
  FROM <project>.analysis_store_item_lot_reduction_store_item_lot_rlt_detail_df t0
  INNER JOIN (
      SELECT DISTINCT cast(store_code as bigint) as store_code, cast(item_code as string) as item_code, lot
      FROM <project>.analysis_reduction_store_unsalable_high_inventory_returns_df
      WHERE stat_date = 20260822
  ) f ON t0.store_code = f.store_code AND t0.item_code = f.item_code AND t0.lot = f.lot
  WHERE t0.stat_date = 20260818 AND t0.prov_zone_man_nm = '<target_zone>';
  ```
- **异动走势释疑**：
  - 该批次 1,125 店在基线当天匹配率达 **99.99%**；
  - 任务下发后，在周末产生集中退仓出库，与「推广计划」排期完全吻合。
