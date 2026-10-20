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
- **脚本列名解耦契约**：数据聚合与中间字典严禁直接使用包含空格或括号的长中文表头作为字典 Key；统一采用清晰的 `snake_case` 英文标识（如 `cancel_lines`、`store_code`），仅在最终 `write_excel` 或渲染映射阶段通过 `COLUMN_MAPPING` 统一转换为中英双语表头，防止表头微调引发 `KeyError`。
---

## 5. 空间与图元尺度有界性断言 (Spatial & Scale Invariants)

在执行可视化制图、布局解析或空间组件渲染时，前置执行以下对抗性几何约束：

1. **绝对物理单位基准**：绘图引擎统一声明物理度量单位（如 $1\text{ unit} == 1\text{ cm}$ 或 $1\text{ unit} == 1\text{ mm}$），坐标计算与图元渲染严格遵循同一比例尺。
2. **字号与图元尺度有界门禁**：文字高度必须受控于容器尺寸（如文字字号 $\le$ 货架厚度的 $35\%$），严禁绝对字号超出实体几何厚度引发文字重叠挤压。
3. **几何多边形无缝与无交断言**：同组同排相邻货架的边缘间距误差 $< 0.1\text{cm}$，不同独立货架矩形闭包交集面积严格为 0。
4. **对抗性自动化用例固化**：脚本产出后必须配套执行对抗性审查测试（Adversarial Test），覆盖列名唯一性、图元上界与分类映射完整性。
5. **物理空间密度常识断言 (Physical Density Sanity Check)**：涉及门店物理货架、展架、设备等空间指标时，计算空间承载密度比值（如 $\frac{\text{门店陈列架总长度 (米)}}{\text{门店营业面积 (m²)}}$）。正常经营药店/便利店该比值处于 $[0.4, 1.8]$ 区间；低于 0.3 说明存在严重漏登或型号误折叠，高于 2.0 说明存在跨品类重复混陈双计，必须触发阻断审查。
