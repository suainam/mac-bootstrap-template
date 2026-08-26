# MaxCompute / ODPS 字段对齐与类型定型规范

## 1. 常见业务字段别名映射词典 (Synonyms)

| 目标物理字段 | 目标常用类型 | 常见业务来源列名 / 别名 | 处理与清洗规则 |
|---|---|---|---|
| `store_code` | `STRING` | 门店编码, 门店代码, 店号, 门店号, store_code, store_id, dept_code | 去除首尾空格；若纯数字且存在前导零丢失风险，按业务补足固定位数（如 10 位）。 |
| `item_code` | `BIGINT` / `STRING` | 商品编码, 商品代码, 品号, 商品号, item_code, goods_code, sku_id, sku_code | 转整型 `int(float(x))` 或纯数字字符串。 |
| `lot` | `STRING` | 批号, 商品批号, 生产批号, 批次, lot, batch_no, lot_no | 必须转为文本格式，防止形如 `20260101` 或 `00123` 的批号被误转为数字丢失前导零或精度。 |
| `st_qty` | `DOUBLE` | 数量, 批号库存数量, 库存数量, 退货数量, 实收数量, qty, stock_qty | 转浮点型 `float(x)`，空值填充 `0.0` 或 `None`（视目标字段是否可为 NULL）。 |
| `st_amt` | `DOUBLE` | 金额, 批号库存金额, 收货金额, 退货金额, 库存金额, amt, total_amt | 转浮点型 `float(x)`，保留实际精度。 |
| `store_item_lot_merge` | `STRING` | 店品批, 拼接, 店品批拼接, merge_key | 优先使用源列；若源列为空，采用 `f"{store_code}{item_code}{lot}"` 自动合成。 |
| `item_lot_merge` | `STRING` | 品批, 品批拼接, item_lot_merge | `f"{item_code}{lot}"`。 |
| `stat_date` (分区) | `BIGINT` / `STRING` | 日期, 统计日期, 业务日期, 分区日期, ds, dt | 根据表分区元数据格式统一（如 BIGINT `20260826` 或 STRING `'20260826'`）。 |

---

## 2. 类型定型与边界转换规则 (Typecasting)

1. **数值列 (DOUBLE / FLOAT / DECIMAL)**:
   - 过滤千分位逗号（如 `1,234.50` → `1234.50`）。
   - 科学计数法（如 `1.4283e-05`）正常解析为 float。
   - `NaN` / `None` / `""` 转换为 MaxCompute `NULL`。

2. **整数列 (BIGINT / INT)**:
   - 先转 `float` 再转 `int`，避免 `"123.0"` 字符串直接转 `int` 抛出 `ValueError`。
   - 非法非数值字符报错或置为 `NULL`。

3. **文本编码与批号列 (STRING)**:
   - 严禁直接读取为 float 导出，否则 `A002283` 或 `1240007` 可能变为 `1240007.0`。
   - 必须通过 `str(val).strip()` 清洗。

4. **冗余列处理**:
   - 源文件中未匹配的辅助计算列、行序号（如 `1..39289`）、全空列（如 `更新库存`）必须显式列入“丢弃列表”，并在方案中向用户列出。

---

## 3. 闭环硬性门禁 (Quality Gates)

- **Gate 1 (线上元数据真身)**: 必须运行 `DESC` 或 PyODPS 探查线上真实表名与字段，杜绝盲目按用户输入或历史记忆猜测。
- **Gate 2 (双向确认)**: 必须向用户输出对齐 Markdown 表格，并等待用户显式确认。
- **Gate 3 (分区存在性)**: 必须在写入前声明 `create_partition=True` 或 `if_not_exists=True`。
- **Gate 4 (事后聚合 SQL 举证)**: 写入后必须运行 `COUNT(1)`、`SUM(数值列)` 与 `COUNT(DISTINCT 主键)`，证明与本地物化指标 100% 对齐。
