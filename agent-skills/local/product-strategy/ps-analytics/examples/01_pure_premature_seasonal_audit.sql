-- ==============================================================================
-- 案例：3合1组货目录下发跨期季节性商品排查与多版本去重纯集穿透
-- 特性：
-- 1. 使用 MAX_PT() 消除嵌套子查询；
-- 2. 关联层对 list_df 进行 (store_code, item_code) 严格聚合去重；
-- 3. 两阶段多模型掩盖排查：剔除所有新品/自有品牌/预测/品牌/O2O/策略必上低优先级重叠。
-- ==============================================================================

WITH latest_xiafa AS (
    SELECT 
        x.store_code,
        x.store_name,
        x.item_code,
        x.item_desc,
        x.state_name_mdm,
        x.region_man_name,
        x.is_3he1_list,
        x.reason_fl,
        x.reason_zfl,
        x.is_shougong_add,
        x.is_bp_store,
        x.is_cjzzy_store,
        x.is_zyppzdsp_store,
        x.is_xshch_store,
        x.is_zdsp_store,
        x.is_bsml_store,
        x.is_bp,
        x.is_cjzzy,
        x.is_zyppzdsp,
        x.is_xshch,
        x.is_zdsp,
        x.is_bsml
    FROM dsl_ads.ads_item_3he1_db_1_6_store_item_xiafa_df x
    WHERE x.stat_date = MAX_PT('dsl_ads.ads_item_3he1_db_1_6_store_item_xiafa_df')
      AND x.is_3he1_list = 1
      AND x.reason_zfl RLIKE '季节'
),
latest_config AS (
    SELECT 
        state_name_mdm,
        varieties,
        COLLECT_SET(mon) as active_mons,
        MAX(CASE WHEN mon = 9 THEN 1 ELSE 0 END) as in_sep,
        MAX(CASE WHEN mon = 10 THEN 1 ELSE 0 END) as in_oct,
        MAX(CASE WHEN mon = 11 THEN 1 ELSE 0 END) as in_nov
    FROM dsl_dwd.dwd_item_ti_seasonal_varieties_for_3he1_catalogue
    WHERE stat_date = MAX_PT('dsl_dwd.dwd_item_ti_seasonal_varieties_for_3he1_catalogue')
      AND is_season = 1
    GROUP BY state_name_mdm, varieties
    HAVING MAX(CASE WHEN mon = 9 THEN 1 ELSE 0 END) = 0
       AND (MAX(CASE WHEN mon = 10 THEN 1 ELSE 0 END) = 1 OR MAX(CASE WHEN mon = 11 THEN 1 ELSE 0 END) = 1)
),
latest_store AS (
    SELECT 
        store_code,
        area_name,
        COALESCE(prov_zone_nm, province_name) as prov_zone_name,
        region_name,
        store_name
    FROM dsl_dim.dim_store
    WHERE stat_date = MAX_PT('dsl_dim.dim_store')
),
latest_item AS (
    SELECT 
        item_code,
        item_desc,
        item_varieties
    FROM dsl_dim.dim_item_master
    WHERE stat_date = MAX_PT('dsl_dim.dim_item_master')
),
-- 核心防笛卡尔积去重层：消除月度/季度/老店/新店版本并发导致的店品重复
dedup_list AS (
    SELECT 
        store_code,
        item_code,
        MAX(CASE WHEN is_brand_item = 1 THEN 1 ELSE 0 END) as is_brand_item,
        MAX(CASE WHEN is_add_push_class_item = 1 THEN 1 ELSE 0 END) as is_add_push_class_item,
        MAX(CASE WHEN is_add_top_varieties = 1 THEN 1 ELSE 0 END) as is_add_top_varieties,
        MAX(CASE WHEN is_xsbd_item = 1 THEN 1 ELSE 0 END) as is_xsbd_item,
        MAX(CASE WHEN is_ky_djp_item = 1 THEN 1 ELSE 0 END) as is_ky_djp_item,
        MAX(CASE WHEN is_rxkp_item = 1 THEN 1 ELSE 0 END) as is_rxkp_item,
        MAX(CASE WHEN is_new_product_add_or_delete_code = 1 THEN 1 ELSE 0 END) as is_new_product_add_or_delete_code,
        MAX(CASE WHEN is_zypp_item_action_code = 1 THEN 1 ELSE 0 END) as is_zypp_item_action_code,
        MAX(CASE WHEN is_zlcjp = 1 THEN 1 ELSE 0 END) as is_zlcjp,
        MAX(CASE WHEN is_qlp = 1 THEN 1 ELSE 0 END) as is_qlp,
        MAX(CASE WHEN is_o2o_store_item = 1 THEN 1 ELSE 0 END) as is_o2o_store_item,
        MAX(CASE WHEN is_o2o_key_item = 1 THEN 1 ELSE 0 END) as is_o2o_key_item
    FROM dsl_ads.ads_item_3he1_db_1_6_store_item_list_df
    WHERE stat_date = MAX_PT('dsl_ads.ads_item_3he1_db_1_6_store_item_list_df')
    GROUP BY store_code, item_code
)
SELECT 
    s.area_name as 大区名称,
    s.prov_zone_name as 省区名称,
    COALESCE(s.region_name, x.region_man_name) as 营运区名称,
    x.store_code as 门店编码,
    COALESCE(x.store_name, s.store_name) as 门店名称,
    x.item_code as 商品编码,
    COALESCE(x.item_desc, i.item_desc) as 商品名称,
    x.is_3he1_list as 是否目录内,
    x.reason_fl as 原因大类,
    x.reason_zfl as 原因子类,
    c.active_mons as 在季月份集合
FROM latest_xiafa x
LEFT JOIN latest_store s ON CAST(x.store_code AS STRING) = CAST(s.store_code AS STRING)
LEFT JOIN latest_item i ON CAST(x.item_code AS STRING) = CAST(i.item_code AS STRING)
INNER JOIN latest_config c 
  ON x.state_name_mdm = c.state_name_mdm 
 AND i.item_varieties = c.varieties
LEFT JOIN dedup_list l
  ON x.store_code = l.store_code
 AND x.item_code = l.item_code
WHERE NOT (
    -- 排除下发表本身记录的业务手工增加或策略必上
    COALESCE(x.is_shougong_add, 0) = 1
    OR COALESCE(x.is_bp_store, 0) = 1
    OR COALESCE(x.is_cjzzy_store, 0) = 1
    OR COALESCE(x.is_zyppzdsp_store, 0) = 1
    OR COALESCE(x.is_xshch_store, 0) = 1
    OR COALESCE(x.is_zdsp_store, 0) = 1
    OR COALESCE(x.is_bsml_store, 0) = 1
    OR COALESCE(x.is_bp, 0) = 1
    OR COALESCE(x.is_cjzzy, 0) = 1
    OR COALESCE(x.is_zyppzdsp, 0) = 1
    OR COALESCE(x.is_xshch, 0) = 1
    OR COALESCE(x.is_zdsp, 0) = 1
    OR COALESCE(x.is_bsml, 0) = 1
    -- 排除 list_df 中因优先级较低被掩盖但正当入选的模型属性
    OR COALESCE(l.is_brand_item, 0) = 1
    OR COALESCE(l.is_add_push_class_item, 0) = 1
    OR COALESCE(l.is_add_top_varieties, 0) = 1
    OR COALESCE(l.is_xsbd_item, 0) = 1
    OR COALESCE(l.is_ky_djp_item, 0) = 1
    OR COALESCE(l.is_rxkp_item, 0) = 1
    OR COALESCE(l.is_new_product_add_or_delete_code, 0) = 1
    OR COALESCE(l.is_zypp_item_action_code, 0) = 1
    OR COALESCE(l.is_zlcjp, 0) = 1
    OR COALESCE(l.is_qlp, 0) = 1
    OR COALESCE(l.is_o2o_store_item, 0) = 1
    OR COALESCE(l.is_o2o_key_item, 0) = 1
);
