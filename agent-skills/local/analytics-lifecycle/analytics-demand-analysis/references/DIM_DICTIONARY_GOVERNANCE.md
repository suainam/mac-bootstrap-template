# 维度数据治理与语义完整性规范 (Dimension Integrity & Dictionary Governance)

在业务分析中建立可复现的维度映射，保护中台元数据与业务实体的定义完整性。

## 核心主导词 (Leading Words)

- **`【真源对齐 / dim-grounded】`**：涉及商品品类、陈列中类与空间定义时，统一以数仓 `dsl_dim` 标准维表及其 `layout_display_name` 字段为准。
- **`【语义保真 / semantic-full】`**：完整呈现中台字段的法定命名，保留业务修饰词（如 `OTC阴凉`、`RX阴凉`、`心脑血管`）。
- **`【实体解耦 / entity-decouple】`**：在数据建模中严格将业务分类实体（如陈列中类）与物理承载载体（如货架类型）分拆为独立字段。

---

## 1. 维度表权威对齐矩阵

| 分析实体领域 | 权威数仓维表 | 权威编码列 | 权威展示全称 | 绘图/紧凑简称 | 典型示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **空间陈列中类** | `dsl_dim.dim_scm_mid_category_df` | `scm_mid_category_no` | `scm_mid_category_name` | `layout_display_name` | `[99] OTC阴凉`、`[12] 营养素`、`[18] 消毒用品` |
| **空间货架载体** | `dsl_dim.dim_store_layout_shelf_info_df` | `shelf_no` | `shelf_name` | `render_name` | `[H10012] 中岛货架100CM-双面` |
| **商品主数据类目**| `dsl_dim.dim_item_master` | `class_code` / `subclass_code` | `class_name` / `sub_name` | - | `大类-中类-小类-子类` 标准四级层级 |

---

## 2. 字段映射操作准则

### 2.1 完整使用中台官方字段
展示名称优先取中台规范命名字段：
- 空间图面紧凑标注：使用 `dim_scm_mid_category_df.layout_display_name`；
- 数据表格与决策报告：使用 `dim_scm_mid_category_df.scm_mid_category_name`；
- 避免字符截断：完整保留 `OTC阴凉`、`RX阴凉` 等完整品类标识。

### 2.2 实体与载体双轴分离
在分析模型与报表宽表中，始终保持实体分类与物理载体独立表达：
```
[正确建模范式]
- 陈列中类编码: 12
- 陈列中类名称: 营养素
- 货架编码: H10012
- 货架种类名称: 中岛货架100CM-双面
```

---

## 3. 维度校验与审计断言

在阶段二与后续阶段建立以下自动化验证：
1. **分类存在性验证**：所有提取的中类代码均在 `dim_scm_mid_category_df` 有效记录中；
2. **非载体侵入验证**：断言分类字段不包含纯货架规格词（如中岛、高柜、矮柜、端架等单一载体名词）；
3. **色彩映射一致性**：图表配色直接继承维表 `color_hex` 十六进制色值。
