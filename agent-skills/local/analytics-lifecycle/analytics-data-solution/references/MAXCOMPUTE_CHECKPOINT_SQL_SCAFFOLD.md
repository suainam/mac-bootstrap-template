# MaxCompute 标准检查点 SQL 骨架与范例 (Checkpoint SQL Scaffold)

> 本文为 [MAXCOMPUTE_MULTI_STAGE_CHECKPOINT_SPEC.md](./MAXCOMPUTE_MULTI_STAGE_CHECKPOINT_SPEC.md) 第三节的拆分全文。

## 三、标准 SQL 骨架与检查点范例 (Standard SQL Scaffold)

```sql
-- =============================================================================
-- 【物理检查点 1】锁定试点门店并提取基准目录
-- 产出表：${dsl_tmp_dev}.tmp_32014b_step1_target_catalog_df
-- =============================================================================
DROP TABLE IF EXISTS ${dsl_tmp_dev}.tmp_32014b_step1_target_catalog_df;

CREATE TABLE ${dsl_tmp_dev}.tmp_32014b_step1_target_catalog_df AS
WITH
target_stores AS (
    SELECT DISTINCT s.store_code, s.region_man_code
    FROM ${dsl_dim}.dim_store s
    INNER JOIN ${dsl_dwd}.dwd_item_3he1_db_product_catalog_status_config_model_store_df cfg 
      ON cfg.store_code = s.store_code
    WHERE s.stat_date = ${benchmark_date} AND s.delete_flg = 'N' AND s.opert_close_date > '${benchmark_date}'
      AND cfg.stat_date = ${benchmark_date} AND cfg.deleted = 0 AND cfg.is_deleted = 0 
      AND cfg.scope_type = ${scope_type} AND cfg.config_id = ${config_id}
)
SELECT 
    l.store_code,
    l.item_code,
    ts.region_man_code,
    1 AS in_catalog
FROM ${dsl_ads}.ads_item_3he1_db_1_6_store_item_list_df l
INNER JOIN target_stores ts ON ts.store_code = l.store_code
WHERE l.stat_date = ${benchmark_date} 
  AND l.version_id = ${version_id}
GROUP BY l.store_code, l.item_code, ts.region_man_code;


-- =============================================================================
-- 【物理检查点 2】生成合格候选池（修复开窗 + 12 项履约硬门禁）
-- 产出表：${dsl_tmp_dev}.tmp_32014b_step2_qualified_cand_df
-- =============================================================================
DROP TABLE IF EXISTS ${dsl_tmp_dev}.tmp_32014b_step2_qualified_cand_df;

CREATE TABLE ${dsl_tmp_dev}.tmp_32014b_step2_qualified_cand_df AS
WITH 
target_stores AS (
    SELECT DISTINCT store_code, region_man_code
    FROM ${dsl_tmp_dev}.tmp_32014b_step1_target_catalog_df
),
-- 2a. 营运区候选底表商品
region_candidate_pool AS (
    SELECT region_man_code, item_code 
    FROM ${dsl_ads}.ads_item_3he1_db_1_6_store_item_list_fkxmx_df
    WHERE stat_date = ${benchmark_date} AND is_fkxmx_list = 1
    GROUP BY region_man_code, item_code
),
-- 2b. 商品主推、效益与营运区销量属性池（严格按营运区聚合防跨店扩行）
item_attribute_pool AS (
    SELECT 
        t1.zone_attr_code AS region_man_code,
        t1.dept_name,
        t1.item_varieties,
        t1.item_code,
        t1.label_value,
        t1.label_value_num,
        t2.item_push_class,
        t3.item_sale_cnt_3m_region
    FROM (
        SELECT 
            zone_attr_code, dept_name, item_varieties, item_code, label_value,
            CASE label_value 
                WHEN 'Aa' THEN 6 WHEN 'Ab' THEN 5 WHEN 'Ba' THEN 4 
                WHEN 'Bb' THEN 3 WHEN 'Ac' THEN 2 WHEN 'Bc' THEN 1 ELSE 0 
            END AS label_value_num
        FROM ${dsl_ads}.ads_pxyh_item_zone_label_df
        WHERE stat_date = ${benchmark_date} AND zone_attr_name = 'region'
          AND label_name = '效益' AND label_value IN ('Aa','Ab','Ba','Bb','Ac','Bc')
    ) t1
    INNER JOIN (
        SELECT region_man_code, item_code, mode_push_class AS item_push_class
        FROM ${dsl_dws}.dws_pxyh_item_mode_push_class_df
        WHERE stat_date = ${benchmark_date} AND region_man_code IS NOT NULL AND mode_push_class IN ('A','B','C')
    ) t2 ON t2.region_man_code = t1.zone_attr_code AND t2.item_code = t1.item_code
    INNER JOIN (
        SELECT a22.region_man_code, a21.item_code, SUM(a21.item_sale_cnt_3m) AS item_sale_cnt_3m_region
        FROM ${dsl_ads}.ads_item_3he1_db_1_6_sale_add_profit_cxht_qhht a21
        LEFT JOIN ${dsl_dim}.dim_store a22 ON a22.store_code = a21.store_code AND a22.stat_date = ${benchmark_date}
        WHERE a21.stat_date = ${benchmark_date}
        GROUP BY a22.region_man_code, a21.item_code
    ) t3 ON t3.item_sale_cnt_3m_region > 0 AND t3.region_man_code = t1.zone_attr_code AND t3.item_code = t1.item_code
    INNER JOIN (
        SELECT item_code FROM ${dsl_dim}.dim_item_master
        WHERE stat_date = ${benchmark_date} AND item_level = 2 AND group_code IN (11,12,16)
    ) t4 ON t4.item_code = t1.item_code
),
-- 2c. 识别各门店各品种当前主推缺口（ABC主推款数 = 0）
store_gap_varieties AS (
    SELECT store_code, dept_name, item_varieties
    FROM ${dsl_ads}.ads_item_3he1_db_1_6_store_item_list_fkxmx_df
    WHERE stat_date = ${benchmark_date} AND is_fkxmx_list = 1
    GROUP BY store_code, dept_name, item_varieties
    HAVING SUM(CASE WHEN push_class IN ('A','B','C') THEN 1 ELSE 0 END) = 0
),
-- 2d. 12 项前置履约门禁
warehouse_status_gate AS (
    SELECT store_code, item_code
    FROM ${dsl_ads}.ads_item_3he1_db_1_6_sale_store_item_status
    WHERE stat_date = ${benchmark_date}
      AND is_wh_itme_status_yc = 0 AND is_wh_wtm = 0 AND is_store_jyfwyc = 0
      AND is_store_item_tc = 0 AND is_store_dept_tc = 0 AND is_yyq_item_tc = 0
      AND is_yyq_dept_tc = 0 AND is_store_group_tc = 0 AND is_jjx_varieties_tc = 0
      AND is_push_class_yc = 0 AND is_div_tc = 0 AND is_djp_tc = 0
      AND COALESCE(push_class, 'A') NOT IN ('DS')
),
-- 2e. 营运区 <=TOP60 品种门禁
top_varieties_gate AS (
    SELECT DISTINCT zone_attr_code AS region_man_code, dept_name, item_varieties, label_value AS top_tier
    FROM ${dsl_ads}.ads_pxyh_dept_varieties_zone_label_df
    WHERE stat_date = ${benchmark_date} AND zone_attr_name = 'region'
      AND label_name = '品种' AND label_value IN ('TOP10', 'TOP20', 'TOP30', 'TOP40', 'TOP50', 'TOP60')
),
cand_ranked AS (
    -- 开窗排序关键修复：必须 PARTITION BY 包含 store_code，杜绝跨店候选跳跃
    SELECT 
        ts.store_code, 
        attr.item_code, 
        attr.item_push_class, 
        attr.dept_name, 
        attr.item_varieties, 
        rc.region_man_code,
        tg.top_tier,
        ROW_NUMBER() OVER (
            PARTITION BY rc.region_man_code, attr.dept_name, attr.item_varieties, ts.store_code
            ORDER BY 
                CASE attr.item_push_class WHEN 'A' THEN 1 WHEN 'B' THEN 2 WHEN 'C' THEN 3 ELSE 9 END ASC,
                attr.label_value_num DESC,
                attr.item_sale_cnt_3m_region DESC,
                attr.item_code ASC
        ) AS rk
    FROM item_attribute_pool attr
    INNER JOIN region_candidate_pool rc ON rc.region_man_code = attr.region_man_code AND rc.item_code = attr.item_code
    INNER JOIN target_stores ts ON ts.region_man_code = rc.region_man_code
    INNER JOIN store_gap_varieties gap ON gap.store_code = ts.store_code AND gap.dept_name = attr.dept_name AND gap.item_varieties = attr.item_varieties
    INNER JOIN warehouse_status_gate wh ON wh.store_code = ts.store_code AND wh.item_code = attr.item_code
    INNER JOIN top_varieties_gate tg ON tg.region_man_code = rc.region_man_code 
             AND tg.dept_name = attr.dept_name 
             AND tg.item_varieties = attr.item_varieties
    LEFT JOIN ${dsl_tmp_dev}.tmp_32014b_step1_target_catalog_df base ON base.store_code = ts.store_code AND base.item_code = attr.item_code
    WHERE base.item_code IS NULL -- 排除既有目录商品
)
SELECT 
    store_code, item_code, region_man_code, dept_name, item_varieties, top_tier, item_push_class, 1 AS in_cand
FROM cand_ranked
WHERE rk = 1;


-- =============================================================================
-- 【物理检查点 3】三方全集对齐宽表 (Step 2 候选 + Step 1 基准目录 + 观察日事实)
-- 产出表：${dsl_tmp_dev}.tmp_32014b_step3_aligned_wideform_df
-- =============================================================================
DROP TABLE IF EXISTS ${dsl_tmp_dev}.tmp_32014b_step3_aligned_wideform_df;

CREATE TABLE ${dsl_tmp_dev}.tmp_32014b_step3_aligned_wideform_df AS
WITH
cand_cat_aligned AS (
    SELECT 
        COALESCE(c.store_code, b.store_code) AS store_code,
        COALESCE(c.item_code, b.item_code) AS item_code,
        COALESCE(c.region_man_code, b.region_man_code) AS region_man_code,
        c.dept_name,
        c.item_varieties,
        c.top_tier,
        c.item_push_class,
        COALESCE(c.in_cand, 0) AS in_cand,
        COALESCE(b.in_catalog, 0) AS in_catalog,
        CASE WHEN COALESCE(c.in_cand, 0) = 1 AND COALESCE(b.in_catalog, 0) = 0 THEN 1 ELSE 0 END AS is_pure_add_push
    FROM ${dsl_tmp_dev}.tmp_32014b_step2_qualified_cand_df c
    FULL OUTER JOIN ${dsl_tmp_dev}.tmp_32014b_step1_target_catalog_df b
      ON b.store_code = c.store_code AND b.item_code = c.item_code
),
-- 经营事实快照裁剪（限定试点门店，排除 KYTS）
observation_facts AS (
    SELECT 
        f.store_code,
        f.item_code,
        s.region_man_code,
        f.is_content_item,
        f.is_store_item,
        f.ld_inv_amt,
        f.lt90_item_sale_cnt_sum AS qty,
        f.lt90_sale_amt_sum AS amt,
        f.lt90_sale_profit_sum AS pf,
        1 AS in_facts
    FROM ${dsl_ads}.ads_item_store_content_day_stat_sale f
    INNER JOIN (
        SELECT DISTINCT s.store_code, s.region_man_code
        FROM ${dsl_dim}.dim_store s
        INNER JOIN ${dsl_dwd}.dwd_item_3he1_db_product_catalog_status_config_model_store_df cfg 
          ON cfg.store_code = s.store_code
        WHERE s.stat_date = ${benchmark_date} AND s.delete_flg = 'N' AND s.opert_close_date > '${benchmark_date}'
          AND cfg.stat_date = ${benchmark_date} AND cfg.deleted = 0 AND cfg.is_deleted = 0 
          AND cfg.scope_type = ${scope_type} AND cfg.config_id = ${config_id}
    ) s ON s.store_code = f.store_code
    WHERE f.stat_date = '${observation_date}'
      AND COALESCE(f.item_push_class, '') NOT IN ('K', 'Y', 'T', 'S')
)
SELECT 
    COALESCE(c.store_code, f.store_code) AS store_code,
    COALESCE(c.item_code, f.item_code) AS item_code,
    COALESCE(c.region_man_code, f.region_man_code) AS region_man_code,
    c.dept_name,
    c.item_varieties,
    c.top_tier,
    c.item_push_class,
    COALESCE(c.in_cand, 0) AS in_cand,
    COALESCE(c.in_catalog, 0) AS in_catalog,
    COALESCE(c.is_pure_add_push, 0) AS is_pure_add_push,
    COALESCE(f.in_facts, 0) AS in_facts,
    COALESCE(f.is_content_item, 0) AS is_content_item,
    COALESCE(f.is_store_item, 0) AS is_store_item,
    f.ld_inv_amt,
    f.qty,
    f.amt,
    f.pf
FROM cand_cat_aligned c
FULL OUTER JOIN observation_facts f 
  ON f.store_code = c.store_code AND f.item_code = c.item_code;
```

---
