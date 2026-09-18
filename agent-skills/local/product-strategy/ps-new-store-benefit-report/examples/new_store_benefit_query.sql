-- ==============================================================================
-- 模版名称: new_store_benefit_query.sql
-- 适用引擎: Alibaba MaxCompute (ODPS)
-- 业务场景: 新店 90 天效益与考核宽表直算（参数化、动态分区、带除零防卫）
-- 参数约定:
--   ${event_date} : 评估事件基准日，格式 YYYYMMDD，默认昨日
--   ${gap_level}  : 汇总粒度，默认 'STORE'
--   ${store_list} : 限定门店列表，以逗号分隔（可选）
-- ==============================================================================

WITH params AS (
    SELECT 
        CAST(COALESCE('${event_date}', TO_CHAR(DATEADD(GETDATE(), -1, 'dd'), 'yyyymmdd')) AS BIGINT) AS event_date,
        COALESCE('${gap_level}', 'STORE') AS gap_level
),

store_dim AS (
    SELECT 
        area_man_code,
        area_man_name,
        prov_zone_man_cd,
        prov_zone_man_nm,
        region_man_code,
        region_man_name,
        CAST(store_code AS BIGINT) AS store_code,
        store_name,
        sjkysj,
        opert_open_date
    FROM dsl_dim.dim_store
    WHERE stat_date = MAX_PT('dsl_dim.dim_store')
),

store_benefit AS (
    SELECT 
        d.area_man_code,
        d.area_man_name,
        d.prov_zone_man_cd,
        d.prov_zone_man_nm,
        d.region_man_code,
        d.region_man_name,
        d.store_code,
        d.store_name,
        d.sjkysj,
        d.opert_open_date,
        t0.jmlx,
        CASE WHEN t0.is_test_region IN ('是', '1', 1) THEN '是' ELSE '否' END AS is_test_region,
        
        -- 目录内 (ct)
        COALESCE(t0.item_num_ct, 0) AS item_num_ct,
        COALESCE(t0.item_num_yxs_ct, 0) AS item_num_yxs_ct,
        ROUND(COALESCE(t0.sale_amt_ct, 0.0), 2) AS sale_amt_ct,
        ROUND(COALESCE(t0.sale_profit_ct, 0.0), 2) AS sale_profit_ct,
        ROUND(COALESCE(t0.lt90_inv_av_cost_amt_ct, 0.0), 2) AS lt90_inv_av_cost_amt_ct,
        ROUND(COALESCE(t0.lt90_sale_cost_ct, 0.0), 2) AS lt90_sale_cost_ct,
        
        -- 全店 (all)
        COALESCE(t0.item_num_all, 0) AS item_num_all,
        COALESCE(t0.item_num_yxs_all, 0) AS item_num_yxs_all,
        ROUND(COALESCE(t0.sale_amt_all, 0.0), 2) AS sale_amt_all,
        ROUND(COALESCE(t0.sale_profit_all, 0.0), 2) AS sale_profit_all,
        ROUND(COALESCE(t0.lt90_inv_av_cost_amt_all, 0.0), 2) AS lt90_inv_av_cost_amt_all,
        ROUND(COALESCE(t0.lt90_sale_cost_all, 0.0), 2) AS lt90_sale_cost_all,
        
        -- 客流与衍生比率（除零安全保护）
        ROUND(COALESCE(t0.store_passenger_flow, 0.0) / 90.0, 1) AS store_passenger_flow,
        CASE 
            WHEN COALESCE(t0.item_num_ct, 0) > 0 
            THEN ROUND(CAST(t0.item_num_yxs_ct AS DOUBLE) / CAST(t0.item_num_ct AS DOUBLE), 4)
            ELSE 0.0 
        END AS item_num_yxs_ct_rate,
        CASE 
            WHEN COALESCE(t0.sale_amt_all, 0.0) > 0 
            THEN ROUND(CAST(t0.sale_amt_ct AS DOUBLE) / CAST(t0.sale_amt_all AS DOUBLE), 4)
            ELSE 0.0 
        END AS sale_amt_ct_rate,
        CASE 
            WHEN COALESCE(t0.sale_profit_all, 0.0) != 0.0 
            THEN ROUND(CAST(t0.sale_profit_ct AS DOUBLE) / CAST(t0.sale_profit_all AS DOUBLE), 4)
            ELSE 0.0 
        END AS sale_profit_ct_rate
        
    FROM dsl_tmp.tmp_ads_item_content_store_summary_df t0
    CROSS JOIN params p
    INNER JOIN store_dim d ON CAST(t0.store_code AS BIGINT) = d.store_code
    WHERE t0.gap_level = p.gap_level
      AND t0.event_date = p.event_date
      ${if(len(store_list) > 0, "AND d.store_code IN (" + store_list + ")", "")}
)

SELECT *
FROM store_benefit
ORDER BY prov_zone_man_cd, store_code;
