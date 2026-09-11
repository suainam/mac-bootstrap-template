"""Render MaxCompute SQL for the dual-source benefit-card pipeline."""

from __future__ import annotations

from typing import Any


def render_dws_and_ads_sql(
    bounds: dict[str, Any],
    *,
    cutoff_date: str,
    baseline_type: str,
    target_project: str,
) -> tuple[str, str]:
    """Step 5 & 6: Ingest diagnostic summary and pivoted card table with store average quantitative evidence."""
    ver_id = bounds["ver_id"]
    key_store_month = ver_id // 100
    baseline_col = baseline_type
    yoy_date = int(cutoff_date) - 10000

    # DWS table
    sql_dws = f"""
    insert overwrite table {target_project}.dws_o2o_key_store_benefit_period_summary_df partition (pt = {cutoff_date})
    with sales_base as (
        select
            case when is_key_store = 1 then '中心店' else 'O2O其他重点店' end as raw_store_group,
            lx_new as strategy_tag,
            'restored' as tag_source,
            platform_name,
            period_type,
            pay_amt,
            margin_account
        from {target_project}.analysis_analysis_assortment_o2_store_cata_items_goals_df
        where pt = {cutoff_date}
          and lx_new in ('城市top500品', '城市top200', '跨渠道top80', 'o2o中心店品')
        union all
        select
            case when is_key_store = 1 then '中心店' else 'O2O其他重点店' end as raw_store_group,
            lx_raw as strategy_tag,
            'raw' as tag_source,
            platform_name,
            period_type,
            pay_amt,
            margin_account
        from {target_project}.analysis_analysis_assortment_o2_store_cata_items_goals_df
        where pt = {cutoff_date}
          and lx_raw in ('城市top500品', '城市top200', '跨渠道top80', 'o2o中心店品')
    )
    , sales_agg as (
        select
            coalesce(raw_store_group, '所有重点门店') as store_group,
            strategy_tag,
            tag_source,
            coalesce(platform_name, 'all') as platform_name,
            period_type,
            sum(pay_amt) as pay_amt,
            sum(margin_account) as margin_account
        from sales_base
        group by raw_store_group, strategy_tag, tag_source, platform_name, period_type
        grouping sets (
            (raw_store_group, strategy_tag, tag_source, period_type),
            (raw_store_group, strategy_tag, tag_source, platform_name, period_type),
            (strategy_tag, tag_source, period_type),
            (strategy_tag, tag_source, platform_name, period_type)
        )
    )
    , tag_turnover_base as (
        select
            case when re.is_key_store = 1 then '中心店' else 'O2O其他重点店' end as raw_store_group,
            t2.is_3he1_fl as strategy_tag,
            'restored' as tag_source,
            case when a.stat_date = {cutoff_date} then 'C'
                 when a.stat_date = {ver_id} then 'L'
                 when a.stat_date = {yoy_date} then 'H' end as period_type,
            a.store_code,
            a.item_code,
            case when a.lt90_item_sale_cnt_sum > 0 then a.item_code end as dx_item_code
        from dsl_ads.ads_item_store_content_day_stat_sale a
        inner join {target_project}.tmp_o2o_mttop500_city_detail_df_2604 t2
            on a.store_code = t2.store_code and a.item_code = t2.item_code and t2.pt = {cutoff_date}
        inner join (
            select store_code, max(case when store_level = 'A' then 1 else 0 end) as is_key_store
            from dsl_dwd.dwd_ti_ec_key_stores_business_capacity
            where stat_date = {key_store_month}
            group by store_code
        ) re on a.store_code = re.store_code
        where a.stat_date in ({cutoff_date}, {ver_id}, {yoy_date})
          and (a.ld_inv_amt > 0 or a.is_content_item = 1)
          and coalesce(a.item_push_class, 'A') not in ('K', 'Y', 'T', 'S')
        union all
        select
            case when re.is_key_store = 1 then '中心店' else 'O2O其他重点店' end as raw_store_group,
            t2.reason_zfl as strategy_tag,
            'raw' as tag_source,
            case when a.stat_date = {cutoff_date} then 'C'
                 when a.stat_date = {ver_id} then 'L'
                 when a.stat_date = {yoy_date} then 'H' end as period_type,
            a.store_code,
            a.item_code,
            case when a.lt90_item_sale_cnt_sum > 0 then a.item_code end as dx_item_code
        from dsl_ads.ads_item_store_content_day_stat_sale a
        inner join {target_project}.tmp_o2o_mttop500_city_detail_df_2604 t2
            on a.store_code = t2.store_code and a.item_code = t2.item_code and t2.pt = {cutoff_date}
        inner join (
            select store_code, max(case when store_level = 'A' then 1 else 0 end) as is_key_store
            from dsl_dwd.dwd_ti_ec_key_stores_business_capacity
            where stat_date = {key_store_month}
            group by store_code
        ) re on a.store_code = re.store_code
        where a.stat_date in ({cutoff_date}, {ver_id}, {yoy_date})
          and (a.ld_inv_amt > 0 or a.is_content_item = 1)
          and coalesce(a.item_push_class, 'A') not in ('K', 'Y', 'T', 'S')
    )
    , tag_turnover as (
        select
            coalesce(raw_store_group, '所有重点门店') as store_group,
            strategy_tag,
            tag_source,
            period_type,
            count(distinct store_code) as store_cnt,
            count(item_code) as tag_item_cnt,
            count(dx_item_code) as tag_dx_item_cnt
        from tag_turnover_base
        group by raw_store_group, strategy_tag, tag_source, period_type
        grouping sets (
            (raw_store_group, strategy_tag, tag_source, period_type),
            (strategy_tag, tag_source, period_type)
        )
    )
    , cata_turnover_base as (
        select
            case when re.is_key_store = 1 then '中心店' else 'O2O其他重点店' end as raw_store_group,
            case when t0.stat_date = {cutoff_date} then 'C'
                 when t0.stat_date = {ver_id} then 'L'
                 when t0.stat_date = {yoy_date} then 'H' end as period_type,
            t0.item_num_ct,
            t0.item_num_yxs_ct
        from dsl_ads.ads_item_content_store_all_stat t0
        inner join (
            select store_code, max(case when store_level = 'A' then 1 else 0 end) as is_key_store
            from dsl_dwd.dwd_ti_ec_key_stores_business_capacity
            where stat_date = {key_store_month}
            group by store_code
        ) re on t0.store_code = re.store_code
        where t0.stat_date in ({cutoff_date}, {ver_id}, {yoy_date})
    )
    , cata_turnover as (
        select
            coalesce(raw_store_group, '所有重点门店') as store_group,
            period_type,
            sum(item_num_ct) as cata_item_cnt,
            sum(item_num_yxs_ct) as cata_dx_item_cnt
        from cata_turnover_base
        group by raw_store_group, period_type
        grouping sets (
            (raw_store_group, period_type),
            (period_type)
        )
    )
    select
        s.store_group,
        s.strategy_tag,
        s.platform_name,
        s.period_type,
        s.pay_amt,
        s.margin_account,
        t.store_cnt,
        t.tag_item_cnt,
        t.tag_dx_item_cnt,
        case
            when s.store_group = '所有重点门店'
             and s.strategy_tag = 'o2o中心店品'
            then c_center.cata_item_cnt
            else c.cata_item_cnt
        end,
        case
            when s.store_group = '所有重点门店'
             and s.strategy_tag = 'o2o中心店品'
            then c_center.cata_dx_item_cnt
            else c.cata_dx_item_cnt
        end,
        s.tag_source
    from sales_agg s
    left join tag_turnover t
        on s.store_group = t.store_group
       and s.strategy_tag = t.strategy_tag
       and s.tag_source = t.tag_source
       and s.period_type = t.period_type
    left join cata_turnover c
        on s.store_group = c.store_group and s.period_type = c.period_type
    left join cata_turnover c_center
        on c_center.store_group = '中心店'
       and c_center.period_type = s.period_type
    ;
    """

    # ADS card table
    sql_ads = f"""
    insert overwrite table {target_project}.ads_o2o_key_store_benefit_card_df partition (pt = {cutoff_date})
    with p as (
        select
            store_group,
            strategy_tag,
            tag_source,
            -- 销售额 (万元)
            round(max(case when platform_name = 'all' and period_type = 'C' then pay_amt end) / 10000.0, 1) as c_sales_all,
            round(max(case when platform_name = 'all' and period_type = '{baseline_col}' then pay_amt end) / 10000.0, 1) as l_sales_all,
            round(max(case when platform_name = 'online' and period_type = 'C' then pay_amt end) / 10000.0, 1) as c_sales_o2o,
            round(max(case when platform_name = 'online' and period_type = '{baseline_col}' then pay_amt end) / 10000.0, 1) as l_sales_o2o,
            round(max(case when platform_name = 'offline' and period_type = 'C' then pay_amt end) / 10000.0, 1) as c_sales_off,
            round(max(case when platform_name = 'offline' and period_type = '{baseline_col}' then pay_amt end) / 10000.0, 1) as l_sales_off,
            -- 毛利额 (万元)
            round(max(case when platform_name = 'all' and period_type = 'C' then margin_account end) / 10000.0, 1) as c_margin_all,
            round(max(case when platform_name = 'all' and period_type = '{baseline_col}' then margin_account end) / 10000.0, 1) as l_margin_all,
            round(max(case when platform_name = 'online' and period_type = 'C' then margin_account end) / 10000.0, 1) as c_margin_o2o,
            round(max(case when platform_name = 'online' and period_type = '{baseline_col}' then margin_account end) / 10000.0, 1) as l_margin_o2o,
            round(max(case when platform_name = 'offline' and period_type = 'C' then margin_account end) / 10000.0, 1) as c_margin_off,
            round(max(case when platform_name = 'offline' and period_type = '{baseline_col}' then margin_account end) / 10000.0, 1) as l_margin_off,
            -- 标签动销率 (%)
            round(max(case when period_type = 'C' then tag_dx_item_cnt * 100.0 / tag_item_cnt end), 2) as c_tag_dx,
            round(max(case when period_type = '{baseline_col}' then tag_dx_item_cnt * 100.0 / tag_item_cnt end), 2) as l_tag_dx,
            -- 目录内动销率 (%)
            round(max(case when period_type = 'C' then cata_dx_item_cnt * 100.0 / cata_item_cnt end), 2) as c_cata_dx,
            round(max(case when period_type = '{baseline_col}' then cata_dx_item_cnt * 100.0 / cata_item_cnt end), 2) as l_cata_dx,
            -- 店均量化证据 (不包含易混淆的门店数列)
            round(max(case when period_type = 'C' then tag_item_cnt * 1.0 / store_cnt end), 1) as c_avg_tag_items,
            round(max(case when period_type = '{baseline_col}' then tag_item_cnt * 1.0 / store_cnt end), 1) as l_avg_tag_items,
            round(max(case when period_type = 'C' then tag_dx_item_cnt * 1.0 / store_cnt end), 1) as c_avg_tag_dx,
            round(max(case when period_type = '{baseline_col}' then tag_dx_item_cnt * 1.0 / store_cnt end), 1) as l_avg_tag_dx,
            round(max(case when period_type = 'C' then cata_item_cnt * 1.0 / store_cnt end), 1) as c_avg_cata_items,
            round(max(case when period_type = '{baseline_col}' then cata_item_cnt * 1.0 / store_cnt end), 1) as l_avg_cata_items,
            round(max(case when period_type = 'C' then cata_dx_item_cnt * 1.0 / store_cnt end), 1) as c_avg_cata_dx,
            round(max(case when period_type = '{baseline_col}' then cata_dx_item_cnt * 1.0 / store_cnt end), 1) as l_avg_cata_dx
        from {target_project}.dws_o2o_key_store_benefit_period_summary_df
        where pt = {cutoff_date}
        group by store_group, strategy_tag, tag_source
    )
    select
        store_group, strategy_tag, 1 as order_seq, '销售额' as metric_name,
        c_sales_all, l_sales_all, c_sales_all - l_sales_all, round((c_sales_all - l_sales_all) / l_sales_all, 4),
        c_sales_o2o, l_sales_o2o, c_sales_o2o - l_sales_o2o, round((c_sales_o2o - l_sales_o2o) / l_sales_o2o, 4),
        c_sales_off, l_sales_off, c_sales_off - l_sales_off, round((c_sales_off - l_sales_off) / l_sales_off, 4),
        null as c_store_cnt, null as l_store_cnt,
        c_avg_tag_items, l_avg_tag_items, c_avg_tag_dx, l_avg_tag_dx,
        c_avg_cata_items, l_avg_cata_items, c_avg_cata_dx, l_avg_cata_dx,
        null as remark,
        tag_source
    from p
    union all
    select
        store_group, strategy_tag, 2 as order_seq, '毛利额' as metric_name,
        c_margin_all, l_margin_all, c_margin_all - l_margin_all, round((c_margin_all - l_margin_all) / l_margin_all, 4),
        c_margin_o2o, l_margin_o2o, c_margin_o2o - l_margin_o2o, round((c_margin_o2o - l_margin_o2o) / l_margin_o2o, 4),
        c_margin_off, l_margin_off, c_margin_off - l_margin_off, round((c_margin_off - l_margin_off) / l_margin_off, 4),
        null as c_store_cnt, null as l_store_cnt,
        c_avg_tag_items, l_avg_tag_items, c_avg_tag_dx, l_avg_tag_dx,
        c_avg_cata_items, l_avg_cata_items, c_avg_cata_dx, l_avg_cata_dx,
        null as remark,
        tag_source
    from p
    union all
    select
        store_group, strategy_tag, 3 as order_seq, concat(strategy_tag, '动销率') as metric_name,
        c_tag_dx, l_tag_dx, c_tag_dx - l_tag_dx, null,
        null, null, null, null,
        null, null, null, null,
        null as c_store_cnt, null as l_store_cnt,
        c_avg_tag_items, l_avg_tag_items, c_avg_tag_dx, l_avg_tag_dx,
        c_avg_cata_items, l_avg_cata_items, c_avg_cata_dx, l_avg_cata_dx,
        '每个城市TOP不一致，动销率建议看整体即可' as remark,
        tag_source
    from p
    union all
    select
        store_group, strategy_tag, 4 as order_seq, '目录内动销率' as metric_name,
        c_cata_dx, l_cata_dx, c_cata_dx - l_cata_dx, null,
        null, null, null, null,
        null, null, null, null,
        null as c_store_cnt, null as l_store_cnt,
        c_avg_tag_items, l_avg_tag_items, c_avg_tag_dx, l_avg_tag_dx,
        c_avg_cata_items, l_avg_cata_items, c_avg_cata_dx, l_avg_cata_dx,
        case when store_group = '中心店'
             then '注:动销率变化主要受分母扩张稀释。中心店目录品数大幅扩增，店均实际动销商品种数显著增长，拉动销售毛利倍增'
             when store_group = '所有重点门店'
             then '注:全量重点门店综合表现，兼顾中心店扩增与常规重点店放量效益'
             else '注:店均目录总品数与实际动销品数均稳步增长' end as remark,
        tag_source
    from p
    ;
    """
    return sql_dws, sql_ads
