-- ==============================================================================
-- 脚本名称: sql_solution_template.sql
-- 适用引擎: Alibaba MaxCompute (ODPS)
-- 方案规范: 阶段三数据方案标准模板 (基于快照截面对齐近90天口径与二元在营品效)
-- 核心设计准则:
--   1. 优先使用考核结束日截面 (如 20260915)，契约对齐近90天销存聚合 (lt90_sale_amt_sum)；
--   2. 目录内在营严格锁定到店履约事实 (is_content_item=1 AND is_store_item=1)，排除供应链未到货断流品；
--   3. 门店自选在营商品为 (is_content_item=0 AND is_store_item=1)，形成二元互斥闭环；
--   4. 全量除法强制使用 NULLIF(col, 0) 实施除零防卫，无目录门店保留 NULL 语义。
-- ==============================================================================

-- 1. 目标门店清单与动态考核时间窗口切片
WITH target_stores AS (
    SELECT 
        d0.store_code,
        d0.store_name,
        d0.region_man_code,
        d0.region_man_name,
        d0.area_man_code,
        d0.area_man_name,
        CASE 
            WHEN CAST(d0.store_code AS BIGINT) = ${store_code_1} THEN '重点诊断店 A'
            WHEN CAST(d0.store_code AS BIGINT) = ${store_code_2} THEN '静态备货店 B'
            WHEN t2.test_info = 2 THEN '试点实验新店'
            WHEN t2.test_info = 1 THEN '同期对照新店'
            ELSE '大盘样本'
        END AS store_cohort_label,
        CAST(TO_CHAR(DATEADD(TO_DATE(CAST(COALESCE(e.end_dt, d0.opert_open_date) AS STRING), 'yyyy-mm-dd'), 1, 'dd'), 'yyyymmdd') AS BIGINT) AS s_kh,
        CAST(TO_CHAR(DATEADD(TO_DATE(CAST(COALESCE(e.end_dt, d0.opert_open_date) AS STRING), 'yyyy-mm-dd'), 90 + COALESCE(r.reject_cnt, 0), 'dd'), 'yyyymmdd') AS BIGINT) AS e_kh
    FROM ${dsl_dim}.dim_store d0
    LEFT JOIN (
        SELECT CAST(store_code AS BIGINT) AS store_code, start_dt, end_dt
        FROM (
            SELECT store_code, start_dt, end_dt, ROW_NUMBER() OVER(PARTITION BY CAST(store_code AS BIGINT) ORDER BY udt_tms DESC) AS rn
            FROM ${dsl_ods}.ods_ti_man_new_store_event
        ) WHERE rn = 1
    ) e ON CAST(d0.store_code AS BIGINT) = e.store_code
    LEFT JOIN (
        SELECT CAST(store_code AS BIGINT) AS store_code, COUNT(1) AS reject_cnt
        FROM ${dsl_ods}.ods_ti_nst_assessment_date_reject
        GROUP BY CAST(store_code AS BIGINT)
    ) r ON CAST(d0.store_code AS BIGINT) = r.store_code
    LEFT JOIN ${dsl_analysis}.analysis_new_store_info_df t2 
      ON d0.store_name = t2.store_name
    WHERE d0.stat_date = MAX_PT('${dsl_dim}.dim_store')
      AND (
          CAST(d0.store_code AS BIGINT) IN (${store_code_1}, ${store_code_2})
          OR t2.test_info IN (1, 2)
      )
),

-- 2. 考核截面在营店品明细 (is_store_item = 1 货架在营事实)
base_item_detail AS (
    SELECT 
        ts.region_man_code,
        ts.region_man_name,
        ts.area_man_code,
        ts.area_man_name,
        ts.store_code,
        ts.store_name,
        ts.store_cohort_label,
        ts.s_kh,
        ts.e_kh,
        t.item_code,
        t.is_content_item,
        t.is_store_item,
        CAST(t.lt90_item_sale_cnt_sum AS DOUBLE) AS lt90_item_sale_cnt_sum,
        CAST(t.lt90_sale_amt_sum AS DOUBLE) AS lt90_sale_amt_sum,
        CAST(t.lt90_sale_profit_sum AS DOUBLE) AS lt90_sale_profit_sum
    FROM target_stores ts
    INNER JOIN ${dsl_ads}.ads_item_store_content_day_stat_sale t
       ON ts.store_code = t.store_code
    WHERE t.stat_date = ${snapshot_date} -- 优先建议使用考核结束日当天截面
      AND t.is_store_item = 1 -- 锁定在营商品全集
),

-- 3. 门店级指标聚合中间表
store_aggregated AS (
    SELECT 
        region_man_code,
        region_man_name,
        area_man_code,
        area_man_name,
        store_code,
        store_name,
        store_cohort_label,
        s_kh,
        e_kh,
        
        -- 1. 规模与执行率 (无目录门店保留 NULL 语义)
        COUNT(CASE WHEN is_content_item = 1 THEN item_code END) AS catalog_sku_cnt,
        COUNT(CASE WHEN is_content_item = 0 THEN item_code END) AS manual_sku_cnt,
        COUNT(item_code) AS total_on_sale_sku_cnt,
        ROUND(COUNT(CASE WHEN is_content_item = 1 THEN item_code END) / NULLIF(COUNT(item_code), 0) * 100, 2) AS execution_rate_pct,
        
        -- 2. 动销率对比 (若无目录品动销率保留 NULL)
        COUNT(CASE WHEN is_content_item = 1 AND lt90_item_sale_cnt_sum > 0 THEN item_code END) AS catalog_turnover_sku_cnt,
        COUNT(CASE WHEN is_content_item = 0 AND lt90_item_sale_cnt_sum > 0 THEN item_code END) AS manual_turnover_sku_cnt,
        COUNT(CASE WHEN lt90_item_sale_cnt_sum > 0 THEN item_code END) AS total_turnover_sku_cnt,
        ROUND(COUNT(CASE WHEN is_content_item = 1 AND lt90_item_sale_cnt_sum > 0 THEN item_code END) 
              / NULLIF(COUNT(CASE WHEN is_content_item = 1 THEN item_code END), 0) * 100, 2) AS catalog_turnover_rate_pct,
        ROUND(COUNT(CASE WHEN is_content_item = 0 AND lt90_item_sale_cnt_sum > 0 THEN item_code END) 
              / NULLIF(COUNT(CASE WHEN is_content_item = 0 THEN item_code END), 0) * 100, 2) AS manual_turnover_rate_pct,
        ROUND(COUNT(CASE WHEN lt90_item_sale_cnt_sum > 0 THEN item_code END) 
              / NULLIF(COUNT(item_code), 0) * 100, 2) AS overall_turnover_rate_pct,
              
        -- 3. 真实全额流水 (不打折、不缩放)
        ROUND(SUM(CASE WHEN is_content_item = 1 THEN lt90_sale_amt_sum ELSE 0.0 END), 2) AS catalog_sale_amt,
        ROUND(SUM(CASE WHEN is_content_item = 0 THEN lt90_sale_amt_sum ELSE 0.0 END), 2) AS manual_sale_amt,
        ROUND(SUM(lt90_sale_amt_sum), 2) AS total_sale_amt,
        ROUND(SUM(CASE WHEN is_content_item = 1 THEN lt90_sale_amt_sum ELSE 0.0 END) 
              / NULLIF(SUM(lt90_sale_amt_sum), 0) * 100, 2) AS catalog_sale_ratio_pct,
              
        -- 4. 单品品效指标 (衡量单位货架吸金力与净赚力)
        ROUND(SUM(CASE WHEN is_content_item = 1 THEN lt90_sale_amt_sum ELSE 0.0 END) 
              / NULLIF(COUNT(CASE WHEN is_content_item = 1 THEN item_code END), 0), 2) AS catalog_per_item_sale,
        ROUND(SUM(CASE WHEN is_content_item = 0 THEN lt90_sale_amt_sum ELSE 0.0 END) 
              / NULLIF(COUNT(CASE WHEN is_content_item = 0 THEN item_code END), 0), 2) AS manual_per_item_sale,
        ROUND(SUM(CASE WHEN is_content_item = 1 THEN lt90_sale_profit_sum ELSE 0.0 END) 
              / NULLIF(COUNT(CASE WHEN is_content_item = 1 THEN item_code END), 0), 2) AS catalog_per_item_profit,
        ROUND(SUM(CASE WHEN is_content_item = 0 THEN lt90_sale_profit_sum ELSE 0.0 END) 
              / NULLIF(COUNT(CASE WHEN is_content_item = 0 THEN item_code END), 0), 2) AS manual_per_item_profit
    FROM base_item_detail
    GROUP BY 
        region_man_code,
        region_man_name,
        area_man_code,
        area_man_name,
        store_code,
        store_name,
        store_cohort_label,
        s_kh,
        e_kh
)

-- 4. 最终宽表输出: 叠加宏观营运区老店与同期新店双重视角
SELECT 
    sa.region_man_code AS `营运区编码`,
    sa.region_man_name AS `营运区名称`,
    sa.area_man_code AS `片区编码`,
    sa.area_man_name AS `片区名称`,
    sa.store_code AS `门店编码`,
    sa.store_name AS `门店名称`,
    sa.store_cohort_label AS `门店分层`,
    sa.s_kh AS `考核开始日`,
    sa.e_kh AS `考核结束日`,
    
    sa.catalog_sku_cnt AS `目录内在营商品数`,
    sa.manual_sku_cnt AS `目录外手工在营商品数`,
    sa.total_on_sale_sku_cnt AS `全店总在营商品数`,
    sa.execution_rate_pct AS `组货目录执行率_pct`,
    
    sa.catalog_turnover_rate_pct AS `目录内商品动销率_pct`,
    sa.manual_turnover_rate_pct AS `目录外手工动销率_pct`,
    sa.overall_turnover_rate_pct AS `全店综合动销率_pct`,
    
    sa.catalog_sale_amt AS `目录内销售额_元`,
    sa.manual_sale_amt AS `目录外手工销售额_元`,
    sa.total_sale_amt AS `全店总销售额_元`,
    sa.catalog_sale_ratio_pct AS `目录内销售贡献占比_pct`,
    
    sa.catalog_per_item_sale AS `目录内单品累计销售_元_品`,
    sa.manual_per_item_sale AS `目录外手工单品累计销售_元_品`,
    sa.catalog_per_item_profit AS `目录内单品毛利贡献_元_品`,
    sa.manual_per_item_profit AS `目录外手工单品毛利贡献_元_品`,
    
    ROUND(AVG(sa.total_sale_amt) OVER(PARTITION BY sa.region_man_code), 2) AS `所属营运区老店平均销售_元`,
    ROUND(AVG(sa.total_sale_amt) OVER(), 2) AS `全区同期新店平均销售_元`,
    ROUND(sa.total_sale_amt / NULLIF(AVG(sa.total_sale_amt) OVER(PARTITION BY sa.region_man_code), 0) * 100, 2) AS `对比营运区老店达成比_pct`,
    ROUND(sa.total_sale_amt / NULLIF(AVG(sa.total_sale_amt) OVER(), 0) * 100, 2) AS `对比全区大盘达成比_pct`

FROM store_aggregated sa
ORDER BY 
    sa.region_man_code,
    sa.store_code;
