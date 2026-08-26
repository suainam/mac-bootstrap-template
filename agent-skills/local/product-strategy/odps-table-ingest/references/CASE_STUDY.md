# 经典实战案例：粤东退货剩余库存导入

本案例记录了一次完整的 Excel 源数据探查、字段模糊对齐、用户确认、分区写入与事后 ODPS SQL 闭环举证全流程。

---

## 1. 业务背景与源数据
- **源文件**：`topics/non_catalogue_clear/01_source_data/粤东退货剩余退货-260825.xlsx`
- **文件状态**：带有 `%TSD-Header-###%` 加密头，但 macOS 下 Python/openpyxl 可透明读取明文。
- **本地物化**：通过 Python 导出为 `02_working_data/粤东退货剩余退货-260825_Sheet1_20260826.csv`，源文件 SHA-256 保持不变。
- **源数据画像**：
  - 总行数：39,289 行（无空行）
  - 覆盖范围：533 家门店、1,218 个商品
  - 核心指标：批号库存数量合计 `82,467`，批号库存金额合计 `3,204,540.08` 元
  - 主键唯一性：`store_code + item_code + lot` 39,289 唯一无重复

---

## 2. 线上 MaxCompute 表真实元数据探查

### 执行探查
```python
from odps import ODPS
o = ODPS(access_id, secret_key, project="dsl_analysis", endpoint=endpoint)
t = o.get_table("anslysis_reduction_store_unsalable_high_inventory_returns_df")
```

### 探查发现
1. **表名真实拼写**：线上表名为 `dsl_analysis.anslysis_reduction_store_unsalable_high_inventory_returns_df`（存在历史拼写 `anslysis_`，而不是 `analysis_`）。
2. **表结构与分区**：
   - `store_code`: STRING（门店编码（10位数））
   - `item_code`: BIGINT（商品编码）
   - `lot`: STRING（批号(文本格式)）
   - `st_qty`: DOUBLE（数量）
   - `store_item_lot_merge`: STRING（拼接）
   - `st_amt`: DOUBLE（收货金额）
   - 分区键：`stat_date` BIGINT（格式 `yyyyMMdd`，历史已有 `20260528`, `20260724`, `20260812` 等分区）

---

## 3. 字段映射方案与用户确认

### 呈现给用户的对齐方案
| ODPS 目标字段 | 类型 | 注释 | Excel 来源列 | 处理与转换规则 | 样例值 |
|---|---|---|---|---|---|
| `store_code` | `STRING` | 门店编码（10位数） | `门店编码` (第1列) | 转 10 位文本 | `'1012011421'` |
| `item_code` | `BIGINT` | 商品编码 | `商品编码` (第2列) | 转 BIGINT 整数 | `8207529` |
| `lot` | `STRING` | 批号(文本格式) | `批号` (第3列) | 转文本格式 | `'A002283'` |
| `st_qty` | `DOUBLE` | 数量 | `批号库存数量` (第4列) | 转 DOUBLE 数值 | `3.0` |
| `store_item_lot_merge` | `STRING` | 拼接 | `店品批` (第7列) | 取原值（校验与三键拼接一致） | `'10120114218207529A002283'` |
| `st_amt` | `DOUBLE` | 收货金额 | `批号库存金额` (第5列) | 转 DOUBLE 数值 | `542.151489` |
| **`stat_date` (分区)** | `BIGINT` | 日期分区 (yyyyMMdd) | 系统生成 | 写入分区 `20260826` | `20260826` |

**Excel 中丢弃不入库的冗余列**：
- `品批` (第6列)
- `Unnamed_7` (第8列)
- `Unnamed_8` (第9列，行序号 1~39289)
- `更新库存` (第10列，全空)

**用户确认指令**：“确认”

---

## 4. 入库执行与分区写入
```python
part_spec = "stat_date=20260826"
t.create_partition(part_spec, if_not_exists=True)
with t.open_writer(partition=part_spec, create_partition=True) as writer:
    writer.write(records_to_upload)
```

---

## 5. 事后 ODPS SQL 聚合举证闭环

### 执行线上验证 SQL
```sql
SELECT 
    COUNT(1) AS row_cnt,
    SUM(st_qty) AS sum_qty,
    ROUND(SUM(st_amt), 2) AS sum_amt,
    COUNT(DISTINCT store_code) AS store_cnt,
    COUNT(DISTINCT item_code) AS item_cnt,
    COUNT(DISTINCT store_item_lot_merge) AS merge_cnt
FROM dsl_analysis.anslysis_reduction_store_unsalable_high_inventory_returns_df
WHERE stat_date = 20260826;
```

### 举证对比结果
| 指标项 | 本地物化源数据 | MaxCompute 线上查询结果 | 对齐结论 |
|---|---|---|---|
| 总行数 (`row_cnt`) | 39,289 | 39,289 | ✅ 100% 一致 |
| 数量总和 (`sum_qty`) | 82,467.0 | 82,467.0 | ✅ 100% 一致 |
| 金额总和 (`sum_amt`) | 3,204,540.08 | 3,204,540.08 | ✅ 100% 一致 |
| 门店去重数 (`store_cnt`) | 533 | 533 | ✅ 100% 一致 |
| 商品去重数 (`item_cnt`) | 1,218 | 1,218 | ✅ 100% 一致 |
| 主键去重数 (`merge_cnt`) | 39,289 | 39,289 | ✅ 100% 一致 |
