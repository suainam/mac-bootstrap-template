# 数据质量门禁清单 (Data Quality Checklist)

在基于 ODPS 和 Python 开展任何专题分析或交付输出前，必须逐项执行以下质量防线核对。

---

## 1. 实体粒度与主键约束 (Grain & Uniqueness)

| 检查项 | 验证 SQL / 代码 | 合格标准 |
| :--- | :--- | :--- |
| **单表主键唯一性** | `SELECT COUNT(1) - COUNT(DISTINCT keys) FROM table WHERE pt=MAX_PT('table')` | 严格等于 `0` |
| **多版本并发去重** | 检查是否存在 `version_id` / `version_num` 多版本 | 关联前必须用 CTE `GROUP BY` 收敛 |
| **维表放大防护** | `dim_store` / `dim_item_master` 主键去重 | 关联键在最新分区内重复数为 `0` |

---

## 2. 分区与过滤合法性 (Partition & Filter Gates)

1. **动态最高分区**：一律使用 `MAX_PT('table')`，禁止手写固定日期或测试脏分区。
2. **过滤条件守恒断言**：在应用业务过滤（如 `is_3he1_list = 1`）前后，记录行数与关键维度的覆盖比例，不可出现断崖式未预期漏斗。
3. **NULL 值防护**：所有字符型比较避免被 `NULL` 吞噬，显式使用 `COALESCE(col, 0) == 0` 或 `col IS NULL`。

---

## 3. 跨表 Join 守恒断言 (Join Conservation)

- **Left Join 膨胀门禁**：`Left Join` 后的行数必须精确等于主表过滤后的行数。若行数增加，说明右表主键不唯一，必须停止并报警。
- **Inner Join 漏损门禁**：记录未匹配上的孤儿记录数量（`COUNT(CASE WHEN r.key IS NULL ...)`），占比超过 1% 需给出业务归因。

---

## 4. 交付文件格式规范 (Delivery Quality)

- **CSV 规范**：统一带 UTF-8 BOM（Python 中为 `encoding='utf-8-sig'`），确保 Windows/Mac Excel 打开均不乱码。
- **Excel 规范**：使用 `openpyxl` 引擎，必须包含表头冻结与标准中文列名。
- **行数红线**：严禁直接向 Git 提交超过 1,000,000 行的明细数据；大体积数据存放在外部数据湖，并在 Git 专题仅保留样例与汇总指标。
