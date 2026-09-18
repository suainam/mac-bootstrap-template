---
name: o2o-store-benefit-report
description: Run and export O2O key store benefit assessment reports (MT500, city TOP200, channel TOP80, honeycomb products) across online/offline channels with pre/post-launch metrics, turnover rates, and Excel cards. Use when user asks to evaluate O2O store assortment performance, compute TOP500/TOP200/TOP80 store benefits, or export O2O benefit card tables.
---

# O2O Store Benefit Report

Orchestrate end-to-end evaluation for O2O key stores and center stores. Produce executive cards comparing post-launch (C) vs the default H baseline across Overall, O2O channel, and Offline channel for sales, gross margin, tag turnover, and catalog turnover. L is an explicit optional window, never the default.

## Core Rules
1. **Single Parameter Drive**: Pass `${yyyyMMdd-1d}` (evaluation cutoff / yesterday). Let the pipeline auto-detect `${project_yyyyMMdd}` (latest version launch date strictly prior to cutoff from `dsl_analysis.ads_item_store_catelogue_version_online_date`).
2. **Strict Physical Partition Pruning & Non-Destructive Partition Writes**:
   - All intermediate tables (`tmp_*`) and delivery tables (`dws_*`, `ads_*`) are partitioned by `(pt bigint comment '跑批日期(yyyyMMdd)')`.
   - DDL uses `create table if not exists` and DML uses `insert overwrite table ... partition (pt = ${cutoff})`. Routine runs NEVER execute `drop table if exists`. Subsequent runs only overwrite the specified partition `pt`, strictly preserving historical partition data.
   - Support `--export-only` mode: directly extracts and formats Excel from the existing ADS partition without re-running upstream ETL.
3. **Cohort (同品池追踪) 历史回溯口径**:
   - 策略（美团TOP500/TOP200/跨渠道TOP80/蜂窝品）均为当年新上线。去年同期（H期）的销售与动销回溯，**严格以今年当前锁定的策略品池 (`store_code + item_code`) 去左关联去年的销售事实**。
   - 业务含义：考核“今年这批算法精选的策略品，在去年的销售基数 vs 现在的销售表现”。去年未动销的商品差值体现“**新品引入**”，已有流水的体现“**目录引入**”（老品纳入策略主推目录放量）。
4. **Three-Tier Store Grouping (via `grouping sets`)**: Split stores by `is_key_store` (`0`: O2O other key stores, `1`: Center stores), plus an aggregate `所有重点门店` tier produced by the same `grouping sets` clause (no separate UNION table). Center stores additionally evaluate honeycomb products (`o2o中心店品`), which does not exist for other key stores, so `所有重点门店` equals `中心店` (not a sum) for that tag.
5. **Dual Tag Sources Without Replacing Existing Aggregations**: Keep both `is_3he1_fl` (restored priority) and `reason_zfl` (raw priority). The goals table carries them in separate columns (`lx_new` and `lx_raw`); the DWS/ADS layers carry `tag_source` (`restored`/`raw`). Add the required all-store/category rows with `grouping sets`; do not delete the existing restored aggregations or alter the tag detail table.
6. **Card Scope Switch**:
   - Default `--card-scope raw_all_stores`: export 4 cards for `所有重点门店` using the raw `reason_zfl` priority.
   - `--card-scope restored_11`: export the existing 11-card view using the restored priority `is_3he1_fl`.
   - `--card-scope all`: export every source/store-group/strategy combination materialized in the ADS partition; raw and restored cards stay separate.
   - If the request says only “导出卡片/最新报告” without an explicit scope, use the default 4 raw-priority cards. Use `restored_11` only when the restored three-store-group view is explicitly requested. If “上线前” is used as a baseline term, confirm whether the user means the default H baseline or explicitly wants L.
7. **Two-Layer Delivery Architecture**:
   - `dws_o2o_key_store_benefit_period_summary_df`: Long diagnostic table storing strategy raw sums, item counts, and turnover numerator/denominator.
   - `ads_o2o_key_store_benefit_card_df`: Final card table pivoted to Image #1 executive layout (12 channel metric columns + 8 store-average quantitative evidence columns; legacy absolute-store-count columns remain null for schema compatibility).
   - Strategy share rows use strategy sales/margin as numerator and the effective store scope's all-item sales/margin as denominator. For `o2o中心店品` on the `所有重点门店` card, the effective denominator is `中心店`, matching its actual affected stores.
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
- Derive L window: backwards $N$ days from `c_s_date - 1`.
- Derive H window: shift C window by `-12` months. H is the default baseline.
- **Completion Criterion**: `tmp_special_date_for_o2o_channel_to_cata_info_df_2604` partition `pt = ${yyyyMMdd-1d}` contains non-null C/L/H day rows with equal count $N$.

### Step 2: Extract Both Tag Priorities (`tmp_o2o_mttop500_city_detail`)
- Query `dsl_ads.ads_item_3he1_db_1_6_store_item_list_df` at `stat_date = ${yyyyMMdd-1d}`.
- Preserve `reason_zfl` unchanged as the raw priority and derive `is_3he1_fl` as the restored priority:
  ```sql
  case when coalesce(is_3he1_list,0) = 0 then ''
       when is_o2o_key_item = 1 then o2o_key_reason
       when is_o2o_store_item = 1 and is_city_top200 = 1 then '城市top200'
       when is_o2o_store_item = 1 and is_online_mttbtop80 = 1 then '跨渠道top80'
       when is_o2o_store_item = 1 then 'o2o中心店品'
       else '其他' end
  ```
- Filter out rows where both raw and restored reasons are `其他`.
- Exclude rows whose `version_num` contains `月度` (implemented by retaining `version_num not like '%月度%'`); this is part of the agreed raw-label report scope.
- **Completion Criterion**: The tag detail partition contains store-item pairs with valid raw/restored labels. Do not alter this detail table for card-scope export.

### Step 3: Run Channel Sales Ingestion
- **Online**: Query `ads_ec_platform_store_item_subsidy_sum_d` where `business_type_tmp = 'O2O'` and `stat_date between H_start and C_end`. Write to `tmp_o2o_channel_sales_online_df_2604`.
- **Offline Sub-tables**: Query `ads_sale_store_channel_mem_item_metrics_sum_di` independently for C/L/H windows.
- **Union Merge**: Concatenate offline sub-tables into `tmp_o2o_channel_sales_offline_df_2604`, then union online and offline into `tmp_o2o_channel_sales_detail_df_2604`.
- **Completion Criterion**: Total revenue and store counts in detail tables match upstream totals across C, L, and H.

### Step 4: Build Store-Item Goals Table
- Join detail sales with the tag table on `store_code` and `item_code`.
- Retain `lx_new = coalesce(tag.is_3he1_fl, '其他标签')` and `lx_raw = coalesce(tag.reason_zfl, '其他标签')` as separate columns.
- Overwrite partition in `analysis_analysis_assortment_o2_store_cata_items_goals_df`.
- **Completion Criterion**: Partition populated with non-zero sales under both source-label sets.

### Step 5: Populate DWS Diagnostic Table
- Aggregate revenue/margin by `store_group`, `strategy_tag`, `platform_name`, `period_type`, and `tag_source` with `grouping sets` for all stores plus center/other stores and online/offline channels.
- Keep the existing `restored` (`is_3he1_fl`) aggregation and add `raw` (`reason_zfl`) aggregation; never replace the former.
- Left join tag turnover metrics from `ads_item_store_content_day_stat_sale` (`lt90_item_sale_cnt_sum > 0`) and catalog turnover metrics from `ads_item_content_store_all_stat` (`item_num_yxs_ct / item_num_ct`) with the same source/group keys.
- **Completion Criterion**: DWS contains separated `restored` and `raw` rows without cross-source joins.

### Step 6: Pivot ADS Card Table & Export
- Pivot C and the default H baseline metrics into `ads_o2o_key_store_benefit_card_df`.
- Each card contains six metric rows: `销售额`、`毛利额`、`销售占比`、`毛利占比`、策略动销率、`目录内动销率`.
- `销售占比` / `毛利占比` are percentages; Excel and summaries use the `sigfig` package to round these two metrics to two significant figures before displaying `%`; turnover rates keep two decimal places. Zero denominators render null.
- Default `--card-scope raw_all_stores`: filter `tag_source='raw'` and `store_group='所有重点门店'`; export 4 cards.
- `--card-scope restored_11`: export the existing 11-card `is_3he1_fl` view.
- `--card-scope all`: export every source/store-group/strategy combination materialized in the ADS partition.
- Excel includes one summary sentence per card and the H/L label is derived from the explicitly selected baseline.
- **Completion Criterion**: Excel contains exactly the requested card scope; H is used unless L is explicitly selected.

## Testing

Regression coverage lives in `.claude/skills/o2o-store-benefit-report/scripts/test_helper.py` in the `product_strategy` checkout (use `agent-skills/local/product-strategy/o2o-store-benefit-report/scripts/test_helper.py` from `mac-bootstrap/template`; outside project pytest `testpaths`, so pass the path explicitly):

```bash
ODPS_ENV_FILE=/path/to/merchandise/.env \
  uv run pytest .claude/skills/o2o-store-benefit-report/scripts/test_helper.py -v
```

Covers: restored 11-card grouping-set count, six metric rows per card, additive aggregation correctness, default raw-priority 4-card scope, source separation, center-store denominator for the honeycomb share rows, and Excel card-banner ordering. Requires live ODPS credentials and a populated ADS partition for the target cutoff date.

Lint before commit:

```bash
uv run ruff check .claude/skills/o2o-store-benefit-report/scripts/helper.py \
  .claude/skills/o2o-store-benefit-report/scripts/sql_builder.py \
  .claude/skills/o2o-store-benefit-report/scripts/test_helper.py
uv run ruff format .claude/skills/o2o-store-benefit-report/scripts/helper.py \
  .claude/skills/o2o-store-benefit-report/scripts/sql_builder.py \
  .claude/skills/o2o-store-benefit-report/scripts/test_helper.py
```

## References

- API schemas, DDLs, and partition boundaries: [reference.md](reference.md)
- Complete execution examples: [examples.md](examples.md)
- Automated execution & export script: [scripts/helper.py](scripts/helper.py)
- Regression tests: [scripts/test_helper.py](scripts/test_helper.py)
