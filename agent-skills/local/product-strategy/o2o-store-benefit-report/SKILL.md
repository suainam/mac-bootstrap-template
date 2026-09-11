---
name: o2o-store-benefit-report
description: Run and export O2O key store benefit assessment reports (MT500, city TOP200, channel TOP80, honeycomb products) across online/offline channels with pre/post-launch metrics, turnover rates, and Excel cards. Use when user asks to evaluate O2O store assortment performance, compute TOP500/TOP200/TOP80 store benefits, or export O2O benefit card tables.
---

# O2O Store Benefit Report

Orchestrate end-to-end evaluation for O2O key stores and center stores. Produce executive cards comparing post-launch (C) vs baseline (H/L) across Overall, O2O channel, and Offline channel for sales, gross margin, tag turnover, and catalog turnover.

## Core Rules
1. **Single Parameter Drive**: Pass `${yyyyMMdd-1d}` (evaluation cutoff / yesterday). Let the pipeline auto-detect `${project_yyyyMMdd}` (latest version launch date strictly prior to cutoff from `dsl_analysis.ads_item_store_catelogue_version_online_date`).
2. **Strict Physical Partition Pruning & Non-Destructive Partition Writes**:
   - All intermediate tables (`tmp_*`) and delivery tables (`dws_*`, `ads_*`) are partitioned by `(pt bigint comment '跑批日期(yyyyMMdd)')`.
   - DDL uses `create table if not exists` and DML uses `insert overwrite table ... partition (pt = ${cutoff})`. Routine runs NEVER execute `drop table if exists`. Subsequent runs only overwrite the specified partition `pt`, strictly preserving historical partition data.
   - Support `--export-only` mode: directly extracts and formats Excel from the existing ADS partition without re-running upstream ETL.
3. **Cohort (同品池追踪) 历史回溯口径**:
   - 策略（美团TOP500/TOP200/跨渠道TOP80/蜂窝品）均为当年新上线。去年同期（H期）的销售与动销回溯，**严格以今年当前锁定的策略品池 (`store_code + item_code`) 去左关联去年的销售事实**。
   - 业务含义：考核“今年这批算法精选的策略品，在去年的销售基数 vs 现在的销售表现”。去年未动销的商品差值体现“**新品引入**”，已有流水的体现“**目录引入**”（老品纳入策略主推目录放量）。
4. **Dual Store Grouping**: Split stores by `is_key_store` (`0`: O2O other key stores, `1`: Center stores). Center stores additionally evaluate honeycomb products (`o2o中心店品`).
5. **Restored Tag Priority & Version Cleanliness**: Group merchandise by restored priority `is_3he1_fl` (`城市top500品`, `城市top200`, `跨渠道top80`, `o2o中心店品`), not raw `reason_zfl`. Explicitly filter `and version_num not like '%月度%'` to eliminate row duplication from pre-generated monthly iterations.
6. **Two-Layer Delivery Architecture**:
   - `dws_o2o_key_store_benefit_period_summary_df`: Long diagnostic table storing raw sums, item counts, and turnover numerator/denominator.
   - `ads_o2o_key_store_benefit_card_df`: Final card table pivoted to Image #1 executive layout (10 core metric columns + 6 store-average quantitative evidence columns; raw store counts are omitted from the final presentation to reduce cognitive load).

## Step-by-Step Pipeline

```text
Step 1: Date Window Determination (tmp_special_date)
               │
Step 2: Tag Priority Restoration (tmp_o2o_mttop500_city_detail)
               │
Step 3: Channel Sales Ingestion (Online + Offline sub-periods -> Detail)
               │
Step 4: Merchandise Goals Join (analysis_..._goals_df)
               │
Step 5: DWS Diagnostic Summary (dws_..._summary_df)
               │
Step 6: ADS Card Pivot & Export (ads_..._card_df -> Excel)
```

### Step 1: Ingest Date Windows (`tmp_special_date`)
- Derive start date `c_s_date_id = max(online_date) < ${yyyyMMdd-1d}`.
- Calculate C window $N = \text{datediff}(c\_e\_date, c\_s\_date) + 1$.
- Derive L window: backwards $N$ days from $c\_s\_date - 1$.
- Derive H window: shift C window by $-12$ months.
- **Completion Criterion**: `tmp_special_date_for_o2o_channel_to_cata_info_df_2604` partition `pt = ${yyyyMMdd-1d}` contains non-null day rows for C, L, and H with equal count $N$.

### Step 2: Extract Restored Merchandise Tags (`tmp_o2o_mttop500_city_detail`)
- Query `dsl_ads.ads_item_3he1_db_1_6_store_item_list_df` at `stat_date = ${yyyyMMdd-1d}`.
- Derive `is_3he1_fl`:
  ```sql
  case when coalesce(is_3he1_list,0) = 0 then ''
       when is_o2o_key_item = 1 then o2o_key_reason
       when is_o2o_store_item = 1 and is_city_top200 = 1 then '城市top200'
       when is_o2o_store_item = 1 and is_online_mttbtop80 = 1 then '跨渠道top80'
       when is_o2o_store_item = 1 then 'o2o中心店品'
       else '其他' end
  ```
- Filter out rows where both raw and restored reasons are `其他`.
- **Completion Criterion**: Table partition `pt = ${yyyyMMdd-1d}` contains store-item pairs mapped to valid tags.

### Step 3: Run Channel Sales Ingestion
- **Online**: Query `ads_ec_platform_store_item_subsidy_sum_d` where `business_type_tmp = 'O2O'` and `stat_date between H_start and C_end`. Write to `tmp_o2o_channel_sales_online_df_2604`.
- **Offline Sub-tables**: Query `ads_sale_store_channel_mem_item_metrics_sum_di` independently for:
  - C: `tmp_o2o_sales_off_c_2604` using `stat_date between ${c_s} and ${c_e}`
  - L: `tmp_o2o_sales_off_l_2604` using `stat_date between ${l_s} and ${l_e}`
  - H: `tmp_o2o_sales_off_h_2604` using `stat_date between ${h_s} and ${h_e}`
- **Union Merge**: Concatenate sub-tables into `tmp_o2o_channel_sales_offline_df_2604`, then union online and offline into `tmp_o2o_channel_sales_detail_df_2604`.
- **Completion Criterion**: Total revenue and store counts in detail table match upstream totals across C, L, and H.

### Step 4: Build Store-Item Goals Table
- Join detail sales with restored tag table on `store_code` and `item_code`.
- Retain `lx_new = coalesce(tag.is_3he1_fl, '其他标签')`.
- Overwrite partition in `analysis_analysis_assortment_o2_store_cata_items_goals_df`.
- **Completion Criterion**: Partition populated with non-zero sales under `城市top500品`, `城市top200`, `跨渠道top80`.

### Step 5: Populate DWS Diagnostic Table
- Aggregate revenue and margin by `store_group`, `strategy_tag`, `platform_name`, `period_type` with grouping sets `(all, online, offline)`.
- Left join tag item turnover metrics from `ads_item_store_content_day_stat_sale` (`lt90_item_sale_cnt_sum > 0`).
- Left join catalog turnover metrics from `ads_item_content_store_all_stat` (`item_num_yxs_ct / item_num_ct`).
- **Completion Criterion**: `dws_o2o_key_store_benefit_period_summary_df` has rows for both store groups and all target tags.

### Step 6: Pivot ADS Card Table & Export
- Pivot C and baseline (H for YoY, L for MoM) metrics into `ads_o2o_key_store_benefit_card_df`.
- Execute `scripts/helper.py` to pull data and format into structured Excel sheets with highlight formatting and summary narrative text.
- **Completion Criterion**: Excel file generated and verified with all cards intact.

## References

- API schemas, DDLs, and partition boundaries: [reference.md](reference.md)
- Complete execution examples: [examples.md](examples.md)
- Automated execution & export script: [scripts/helper.py](scripts/helper.py)
