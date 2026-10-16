# 新店效益指标契约 (New Store Benefit Metrics Contract)

本文档定义新店 90 天效益分析宽表的 32 项核心字段契约，涵盖源表字段映射、中文字段命名、计算公式与值域防卫规则。

---

## 一、指标契约清单 (32 项)

| 序号 | 英文原字段 | 规范中文字段名 | 数据类型 | 源表/来源 | 计算口径与取值规则 | 极端值与防卫规则 |
|:---:|---|---|:---:|---|---|---|
| 1 | `area_man_code` | **大区编码** | BIGINT | `dsl_dim.dim_store` | 组织维度：大区编码 | 必须非空且 > 0 |
| 2 | `area_man_name` | **大区名称** | STRING | `dsl_dim.dim_store` | 组织维度：大区名称 | 不允许 NULL 或空字符串 |
| 3 | `prov_zone_man_cd` | **省区编码** | BIGINT | `dsl_dim.dim_store` | 组织维度：省区编码 | 必须非空且 > 0 |
| 4 | `prov_zone_man_nm` | **省区名称** | STRING | `dsl_dim.dim_store` | 组织维度：省区名称 | 不允许 NULL |
| 5 | `region_man_code` | **营运区编码** | BIGINT | `dsl_dim.dim_store` | 组织维度：营运区编码 | 必须非空且 > 0 |
| 6 | `region_man_name` | **营运区名称** | STRING | `dsl_dim.dim_store` | 组织维度：营运区名称 | 不允许 NULL |
| 7 | `store_code` | **门店编码** | BIGINT | `dsl_dim.dim_store` | 门店唯一身份标识码（如 `2000017165`） | 必须为合规门店编号 |
| 8 | `store_name` | **门店名称** | STRING | `dsl_dim.dim_store` | 门店对外营业标准全称 | 不允许 NULL |
| 9 | `jmlx` | **经营方式** | STRING | `tmp_ads_item_content_store_summary_df` | 门店经营管理属性（直营 / 加盟） | 只能为指定枚举值 |
| 10 | `assessment_status`| **考核类型** | STRING | 派生判定 | 根据考核进度判定：`跟进中` / `已结束` | 严格二元枚举 |
| 11 | `is_test_region` | **试点营运区** | STRING | `tmp_ads_item_content_store_summary_df` | 是否属于新店组货策略试点营运区（`是`/`否`） | 杜绝“是否测试营运区”等异名 |
| 12 | `item_num_ct` | **目录内商品数** | BIGINT | `tmp_ads_item_content_store_summary_df` | 门店经营目录内的 SKU 规格品项数 | 必须 >= 0，且 <= `item_num_all` |
| 13 | `item_num_yxs_ct` | **目录内有效动销商品数** | BIGINT | `tmp_ads_item_content_store_summary_df` | 经营目录内产生正向销售贡献的 SKU 数 | 必须 >= 0，且 <= `item_num_ct` |
| 14 | `sale_amt_ct` | **目录内近90天折算日均销售额** | DECIMAL | `tmp_ads_item_content_store_summary_df` | 经营目录内近90天累计销售除以90天基准平摊值(元)；新店未满90天时前序未开业按0摊入 | >= 0.00，保留 2 位小数 |
| 15 | `sale_profit_ct` | **目录内近90天折算日均毛利额** | DECIMAL | `tmp_ads_item_content_store_summary_df` | 经营目录内近90天累计毛利除以90天基准平摊值(元)；新店未满90天时前序未开业按0摊入 | 可为负（促销亏损），保留 2 位小数 |
| 16 | `lt90_inv_av_cost_amt_ct` | **目录内近 90 天日均库存成本** | DECIMAL | `tmp_ads_item_content_store_summary_df` | 经营目录内商品近 90 天日均库存持有成本(元) | >= 0.00，杜绝“平均库存成本”歧义 |
| 17 | `lt90_sale_cost_ct` | **目录内近 90 天日均销售成本** | DECIMAL | `tmp_ads_item_content_store_summary_df` | 经营目录内商品近 90 天日均商品销售成本(元) | >= 0.00 |
| 18 | `item_num_all` | **全店商品数** | BIGINT | `tmp_ads_item_content_store_summary_df` | 全店总经营 SKU 规格品项数 | 必须 >= `item_num_ct` |
| 19 | `item_num_yxs_all`| **全店有效动销商品数** | BIGINT | `tmp_ads_item_content_store_summary_df` | 全店产生正向销售贡献的总 SKU 数 | 必须 >= 0，且 <= `item_num_all` |
| 20 | `sale_amt_all` | **全店近90天折算日均销售额** | DECIMAL | `tmp_ads_item_content_store_summary_df` | 全店近90天累计总销售除以90天基准平摊值(元)；新店未满90天时前序未开业按0摊入 | 必须 >= `sale_amt_ct` |
| 21 | `sale_profit_all` | **全店近90天折算日均毛利额** | DECIMAL | `tmp_ads_item_content_store_summary_df` | 全店近90天累计总毛利除以90天基准平摊值(元)；新店未满90天时前序未开业按0摊入 | 综合毛利额 |
| 22 | `lt90_inv_av_cost_amt_all` | **全店近 90 天日均库存成本** | DECIMAL | `tmp_ads_item_content_store_summary_df` | 全店商品近 90 天日均总库存成本(元) | 必须 >= `lt90_inv_av_cost_amt_ct` |
| 23 | `lt90_sale_cost_all` | **全店近 90 天日均销售成本** | DECIMAL | `tmp_ads_item_content_store_summary_df` | 全店商品近 90 天日均总销售成本(元) | 必须 >= `lt90_sale_cost_ct` |
| 24 | `store_passenger_flow` | **近 90 天日均客流** | DECIMAL | `tmp_ads_item_content_store_summary_df` | 全店近 90 天总客流除以 90 (人次/天) | >= 0.0，保留 1 位小数 |
| 25 | `item_num_yxs_ct_rate` | **目录内商品动销率** | FLOAT | 派生计算 | `item_num_yxs_ct / NULLIF(item_num_ct, 0)` | 0.0% ~ 100.0%，除零保护回退 0% |
| 26 | `sale_amt_ct_rate` | **目录内销售额占比** | FLOAT | 派生计算 | `sale_amt_ct / NULLIF(sale_amt_all, 0)` | 0.0% ~ 100.0%，除零保护回退 0% |
| 27 | `sale_profit_ct_rate` | **目录内毛利额占比** | FLOAT | 派生计算 | `sale_profit_ct / NULLIF(sale_profit_all, 0)` | 允许超过 100% (若目录外毛利为负) |
| 28 | `sjkysj` | **实际开业时间** | STRING | `dsl_dim.dim_store` | 门店正式开业首日（YYYY-MM-DD） | 合法标准日期字符串 |
| 29 | `s_kh` | **考核开始日期** | STRING | 业务规则/预算底表 | 开业大促结束次日（`end_dt + 1`） | 必须在 `sjkysj` 之后 |
| 30 | `assess_target_total` | **90 天总指标** | DECIMAL | 预算保本底表派生 | `月保本销 × 3 × 达标标准系数` | 必须 > 0.00 |
| 31 | `time_progress` | **时间进度** | FLOAT | 周期派生 | 考核已过有效天数 / 90天 | 跟进中 0~100%，已结束严格 100% |
| 32 | `cumulative_completion_rate` | **累计达成率** | FLOAT | 考核销售/总指标 | `(线下销售 + O2O销售/3) / 90天总指标` | 百分比展示，保留 2 位小数 |

---

## 二、边界防卫与数据一致性断言

1. **品项包含性断言**：
   $$\text{item\_num\_yxs\_ct} \le \text{item\_num\_ct} \le \text{item\_num\_all}$$
2. **销售包含性断言**：
   $$\text{sale\_amt\_ct} \le \text{sale\_amt\_all}$$
3. **库存成本包含性断言**：
   $$\text{lt90\_inv\_av\_cost\_amt\_ct} \le \text{lt90\_inv\_av\_cost\_amt\_all}$$
4. **除零防卫 (Zero-Division Defensiveness)**：
   所有百分比计算中，分母若为 `0` 或 `None`，统一返回 `0.00%` 或 `-`，严禁抛出 `ZeroDivisionError` 或生成 `#DIV/0!`。
