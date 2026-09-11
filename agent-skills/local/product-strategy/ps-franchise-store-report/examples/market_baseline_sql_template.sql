-- MaxCompute / ODPS SQL
-- 加盟店组货大盘基线 21 项指标统计管道
-- 来源: 《22_每天销售查询报表2025》口径对齐转写
--
-- 参数化注入:
--   ${start_date}      统计起始日 (如 20260610, 严格 90 天窗口起点)
--   ${end_date}        统计截止日 (如 20260907, 严格 90 天窗口终点)
--   ${dim_stat_date}   门店维表快照分区 (默认与 end_date 一致或当前最新分区)

WITH dim_store AS (
    SELECT b.store_code
    FROM ${dsl_dim}.dim_store b
    WHERE b.stat_date = '${dim_stat_date}'
      AND CAST(b.opert_open_date AS BIGINT) >= ${opert_s}
      AND CAST(b.opert_open_date AS BIGINT) <= ${opert_e}
      AND b.area_man_code NOT IN (0, 1008)
      AND b.manage_way_code IN ('JY0201', 'JY0202', 'JY0203')
),
store_sales AS (
    SELECT 
        a.store_code,
        SUM(a.pay_amt) AS sales_amt,
        SUM(a.sales_profit_amt) AS profit_amt,
        SUM(a.passenger_flow) AS passenger_flow,
        SUM(a.mem_pay_amt) AS mem_pay_amt,
        SUM(a.mem_sales_profit_amt) AS mem_profit_amt,
        SUM(a.mem_passenger_flow) AS mem_passenger_flow,
        SUM(a.o2o_pay_amt) AS o2o_pay_amt,
        SUM(a.o2o_sales_profit_amt) AS o2o_profit_amt,
        SUM(a.o2o_passenger_flow) AS o2o_passenger_flow,
        SUM(a.gift_amt) AS gift_amt,
        SUM(a.coupons_amt) AS coupons_amt
    FROM ${dsl_ads}.ads_sale_store_union_metrics_sum_di a
    WHERE a.stat_date BETWEEN ${start_date} AND ${end_date}
    GROUP BY a.store_code
),
agg_sales AS (
    SELECT 
        1 AS dummy_id,
        COUNT(DISTINCT CASE WHEN ss.sales_amt <> 0 THEN ds.store_code END) AS store_count,
        SUM(ss.sales_amt) AS sales_amt,
        SUM(ss.profit_amt) AS profit_amt,
        SUM(ss.passenger_flow) AS passenger_flow,
        SUM(ss.mem_pay_amt) AS mem_pay_amt,
        SUM(ss.mem_profit_amt) AS mem_profit_amt,
        SUM(ss.mem_passenger_flow) AS mem_passenger_flow,
        SUM(ss.o2o_pay_amt) AS o2o_pay_amt,
        SUM(ss.o2o_profit_amt) AS o2o_profit_amt,
        SUM(ss.o2o_passenger_flow) AS o2o_passenger_flow,
        SUM(ss.gift_amt) AS gift_amt,
        SUM(ss.coupons_amt) AS coupons_amt
    FROM store_sales ss
    INNER JOIN dim_store ds ON ss.store_code = ds.store_code
),
o2o_item AS (
    SELECT 
        1 AS dummy_id,
        SUM(a.o2o_item_pay_amt) AS o2o_item_pay_amt,
        SUM(a.o2o_item_margin_account) AS o2o_item_margin_account
    FROM ${dsl_ads}.ads_ec_platform_store_class_sum_d a
    INNER JOIN ${dsl_dim}.dim_ec_platform b ON a.platform_id = b.platform_id
    INNER JOIN dim_store ds ON CAST(a.store_code AS BIGINT) = ds.store_code
    WHERE a.stat_date BETWEEN ${start_date} AND ${end_date}
      AND b.platform_type_name IN ('第三方平台O2O', '自营平台O2O', '自营O2O')
      AND b.business_type_tmp IN ('私域', 'O2O', 'B2C')
      AND COALESCE(a.store_code, '') <> ''
)
SELECT /*+ mapjoin(oi) */
    s.store_count,
    s.sales_amt,
    s.profit_amt,
    s.passenger_flow,
    s.mem_pay_amt,
    s.mem_profit_amt,
    s.mem_passenger_flow,
    s.o2o_pay_amt,
    s.o2o_profit_amt,
    s.o2o_passenger_flow,
    s.gift_amt,
    s.coupons_amt,
    oi.o2o_item_pay_amt,
    oi.o2o_item_margin_account
FROM agg_sales s
LEFT JOIN o2o_item oi ON s.dummy_id = oi.dummy_id;
