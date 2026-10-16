# 实体粒度锁定与五维数据画像核验指南 (Grain & Profiling Checklist)

在开展专题分析前，必须通过数据画像与实体粒度断言，建立可验证的指标基准线。画像报告必须同时覆盖“宏观营运区店均对比”与“微观门店内部目录内外品效对比”。

---

## 1. 实体粒度与主键约束 (Grain & Key Uniqueness)

| 检查项 | 验证 SQL / 代码 | 合格标准 |
| :--- | :--- | :--- |
| **主键唯一性断言** | `SELECT COUNT(1) - COUNT(DISTINCT keys) FROM table WHERE pt=MAX_PT('table')` | 严格等于 `0` |
| **多版本并发去重** | 检查表是否存在 `version_id` / `version_num` / `batch_id` | 关联前通过 CTE `GROUP BY` 或窗口函数收敛为单版本 |
| **维表放大防卫** | `dim_store` / `dim_item_master` 关联键唯一性验证 | 关联键在最新分区内重复数为 `0` |
| **物理单体vs型号规格防卫** | `SELECT COUNT(DISTINCT code), COUNT(1) FROM tbl` | 若全国/全局仅几百个离散值，判定为规格型号码，严禁作为去重主键，必须使用物理排面节位/单体码（如 `display_code`） |
---

## 2. 6 项基准画像指标 (6 Baseline Metrics)

对原始数据源执行基准数据画像，固化以下 6 项指标基准：

```sql
SELECT 
    COUNT(1) AS row_cnt,                              -- 1. 总行数
    COUNT(DISTINCT store_code) AS store_cnt,          -- 2. 去重门店数
    COUNT(DISTINCT item_code) AS item_cnt,            -- 3. 去重商品数
    COUNT(DISTINCT store_code, item_code) AS merge_cnt, -- 4. 去重主键粒度数
    SUM(COALESCE(qty, 0)) AS sum_qty,                 -- 5. 数量总和
    SUM(COALESCE(amt, 0)) AS sum_amt                  -- 6. 金额总和
FROM source_table
WHERE pt = MAX_PT('source_table');
```

**断言守恒规则**：
- `merge_cnt == row_cnt`：证明实体主键粒度完全成立，无重复记录。
- 数据流转至后续处理阶段时，以该基准指标为基线进行总量守恒核验。

---

## 3. 双层效益对比体系 (Dual-Level Efficiency Comparison)

数据画像必须在阶段二前置物化以下两层对比矩阵，用数据直接支撑策略有效性论证：

### 3.1 宏观层：目标门店 vs 所属营运区店均 (Macro Regional Benchmark)
将试点新店与所属营运区成熟老店店均、全区同期新店店均拉平比较：
- 考核期日均销售额（对比营运区店均达成比）；
- 考核期日均毛利额与综合毛利率；
- 门店在营 SKU 宽度与坪效产出。
- **业务价值**：判定目标门店表现不佳是源于商圈大盘低迷，还是单店选品运营异常。

### 3.2 微观层：门店内部“目录内” vs “目录外 (手工自选)”品效对比 (Micro Catalog Efficiency)
在同一家门店内部，将商品切分为目录内品池与目录外手工品池：
- **动销率对比**：目录内动销率 vs 目录外手工品动销率；
- **单品品效贡献**：
  $$\text{单品日均销售} = \frac{\text{品池总销售额}}{\text{品池在营商品项数} \times \text{考核天数}}$$
  $$\text{单品毛利贡献} = \frac{\text{品池总毛利额}}{\text{品池在营商品项数}}$$
- **销售与毛利占比**：目录内销售贡献占比 vs 目录内 SKU 项数占比（良性状态下，目录内以更少的商品项数撬动更高比例的流水）。
- **业务价值**：直观证明系统组货目录相比区域手工拍脑袋备货具有更高质量与产出。

---

## 4. 分区与过滤条件规范 (Partition & Filter Gates)

1. **动态最高分区**：使用 `MAX_PT('table')`，确保每次运行指向最新有效业务分区。
2. **过滤条件守恒跟踪**：应用业务过滤规则前后，记录行数与关键维度的覆盖比例，保持过滤漏斗平稳透明。
3. **NULL 值显式表达**：字符型与数值型比较使用 `COALESCE(col, 0) == 0` 或 `col IS NULL`，保持逻辑完整性。

---

## 5. 关联计算守恒门禁 (Join Conservation)

- **Left Join 膨胀防卫**：`Left Join` 后的行数与主表行数保持一致；若行数增加，说明右表主键存在重复，需前置去重收敛。
- **Inner Join 匹配度核验**：统计未关联成功记录比例（`COUNT(CASE WHEN r.key IS NULL ...)`），未匹配占比超 1% 时给出业务维度的分布归因。
