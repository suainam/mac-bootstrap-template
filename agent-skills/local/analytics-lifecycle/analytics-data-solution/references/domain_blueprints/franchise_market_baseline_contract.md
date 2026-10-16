# 大盘基准计算与对齐契约 (Market Baseline Contract)

## 业务背景与口径定义

来源：《22_每天销售查询报表2025》（原 Hologres 语法），已完成 MaxCompute (ODPS) 标准化转写并实现 100% 精度对齐。

### 1. 过滤边界
- **汇总层级**：全国汇总 (`grouptype = 0`, `group by 1`)。
- **开店时间**：`CAST(opert_open_date AS BIGINT) BETWEEN 19930101 AND 20280910`。
- **管理区域**：`area_man_code NOT IN (0, 1008)`。
- **经营方式**：仅统计加盟形态（`JY0201` 员工内加盟、`JY0202` 员工外加盟、`JY0203` 外加盟）。直营批量并购（`JY0103`）不纳入加盟分析盘。
- **上线标识**：包含未上线（`source_type` 不作限定）。
- **毛利来源**：前台毛利（`gData_Source = 1`），毛利额取 `sales_profit_amt`。
- **统计区间**：截止 `project_et`（及去年同期）的严格 90 天窗口。

### 2. 核心 21 项指标定义

| 序号 | 字段名 | 中文标签 | 算法 / 来源 |
|---|---|---|---|
| 1 | `store_count` | 门店数量 | `COUNT(DISTINCT CASE WHEN a.pay_amt <> 0 THEN ds.store_code END)` |
| 2 | `sales_amt` | 整体销售额（元） | `SUM(a.pay_amt)` |
| 3 | `profit_amt` | 整体毛利额（元） | `SUM(a.sales_profit_amt)` |
| 4 | `profit_rate` | 整体毛利率 | `profit_amt / sales_amt` |
| 5 | `traffic` | 整体客流 | `SUM(a.passenger_flow)` |
| 6 | `avg_ticket` | 整体客单价 | `sales_amt / traffic` |
| 7 | `member_sales_amt` | 会员销售额（元） | `SUM(a.mem_pay_amt)` |
| 8 | `member_sales_ratio` | 会员销售额占比 | `member_sales_amt / sales_amt` |
| 9 | `member_profit_amt` | 会员毛利额（元） | `SUM(a.mem_sales_profit_amt)` |
| 10 | `member_profit_ratio` | 会员毛利额占比 | `member_profit_amt / profit_amt` |
| 11 | `member_profit_rate` | 会员毛利率 | `member_profit_amt / member_sales_amt` |
| 12 | `member_traffic` | 会员客流 | `SUM(a.mem_passenger_flow)` |
| 13 | `o2o_sales_amt` | O2O销售额（元） | `SUM(a.o2o_pay_amt)` |
| 14 | `o2o_sales_ratio` | O2O销售额占比 | `o2o_sales_amt / sales_amt` |
| 15 | `o2o_profit_amt` | O2O毛利额（元） | `SUM(a.o2o_sales_profit_amt)` |
| 16 | `o2o_profit_ratio` | O2O毛利额占比 | `o2o_profit_amt / profit_amt` |
| 17 | `o2o_profit_rate` | O2O毛利率 | `o2o_profit_amt / o2o_sales_amt` |
| 18 | `o2o_product_profit_rate` | O2O商品毛利率 | 取自 `ads_ec_platform_store_class_sum_d`: `SUM(o2o_item_margin_account) / SUM(o2o_item_pay_amt)` |
| 19 | `o2o_traffic` | O2O客流 | `SUM(a.o2o_passenger_flow)` |
| 20 | `gift_ratio` | 赠品占比 | `SUM(a.gift_amt) / sales_amt` |
| 21 | `voucher_ratio` | 现金代用券占比 | `SUM(a.coupons_amt) / sales_amt` |

### 3. 数据表映射
- 主销售表：`dsl_ads.ads_sale_store_union_metrics_sum_di`
- O2O品类表：`dsl_ads.ads_ec_platform_store_class_sum_d`
- 电商平台维表：`dsl_dim.dim_ec_platform` (过滤条件: `platform_type_name IN ('第三方平台O2O', '自营平台O2O', '自营O2O') AND business_type_tmp IN ('私域', 'O2O', 'B2C')`)
- 门店维表：`dsl_dim.dim_store` (分区 `stat_date` 默认取截止日)
