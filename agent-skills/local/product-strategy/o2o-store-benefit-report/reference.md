# O2O Store Benefit Report — Reference Documentation

Detailed table schemas, data dictionary, partition rules, and compute engine optimization guidelines.

## 1. Store Classification

Store level classification is maintained in `dsl_dwd.dwd_ti_ec_key_stores_business_capacity`:

| Partition Range | Column Used | Center Store (`is_key_store = 1`) | Other Key Store (`is_key_store = 0`) |
|---|---|---|---|
| `stat_date <= 202608` | `store_level` | `store_level = 'A'` | `store_level <> 'A'` (e.g., 'B') |
| `stat_date > 202608` | `remark` | `remark rlike 'A'` | not `remark rlike 'A'` |

Partition selection rule: `stat_date = floor(c_s_date_id / 100)` (month of version online date).

## 2. Tag Restoration Hierarchy

Restored tag `is_3he1_fl` in `tmp_o2o_mttop500_city_detail_df_2604` follows business priority:

```text
Priority 1: is_o2o_key_item = 1                --> o2o_key_reason
Priority 2: is_o2o_store_item = 1 & city_top200 --> '城市top200'
Priority 3: is_o2o_store_item = 1 & top80       --> '跨渠道top80'
Priority 4: is_o2o_store_item = 1               --> 'o2o中心店品' (蜂窝品)
Priority 5: Others                              --> '其他'
```

Target tags in reporting:
- `城市top500品` (External MT city top 500)
- `城市top200` (Internal city top 200)
- `跨渠道top80` (Internal Meituan & Tao Flash Sale top 80)
- `o2o中心店品` (Honeycomb products, center store exclusive)

## 3. Historical Cohort Matching Logic

Because O2O assortment strategies were launched in the current year (2026), historical baseline periods (Period H: YoY same period last year) have no historical strategy labels. The pipeline implements **Cohort (Fixed Item Pool) Matching**:

1. **Cohort Definition**:
   Merchandise pool is strictly anchored to the current active assortment version (`stat_date = ${cutoff_date}` in `ads_item_3he1_db_1_6_store_item_list_df` excluding monthly iterations).
2. **Historical Sales Matching**:
   Historical sales in Period H (`dsl_ads.ads_sale_store_channel_mem_item_metrics_sum_di` and `ads_ec_platform_store_item_subsidy_sum_d`) are joined on:
   ```sql
   sales.store_code = tags.store_code and sales.item_code = tags.item_code
   ```
3. **Business Attribution**:
   - **新品引入 (New Items Increment)**: If an item had no sales in that store last year (`pay_amt = 0` or absent), its current revenue is 100% incremental contribution from newly introduced strategy items.
   - **目录引入 (Catalog Placement Increment)**: If an item already existed last year, the delta reflects volume uplift from prioritized placement in the O2O catalog.

## 4. Physical Table DDLs

### 3.1 Date Dimension Mapping Table
```sql
create table if not exists ${dsl_analysis}.tmp_special_date_for_o2o_channel_to_cata_info_df_2604 (
    day_id        bigint  comment '日期ID(yyyyMMdd)',
    day_date      string  comment '日期(yyyy-MM-dd)',
    c_s_date      date    comment 'C期起始(组货版本上线日)',
    c_e_date      date    comment 'C期截止(昨天)',
    c_s_date_id   bigint  comment 'C期起始日期ID(最新版本上线日yyyyMMdd)',
    c_days        int     comment 'C期天数(含首尾)',
    period_type   string  comment '周期类型:C上线后/L上线前/H去年同期'
)
comment 'O2O效益分析-特殊日期区间映射表(日粒度)'
partitioned by (pt bigint comment '跑批日期(yyyyMMdd)');
```

### 3.2 Channel Sales Detail Table
```sql
create table if not exists ${dsl_analysis}.tmp_o2o_channel_sales_detail_df_2604 (
    region_man_code bigint         comment '营运区编码',
    store_code      bigint         comment '门店编码',
    item_code       bigint         comment '商品编码',
    is_key_store    bigint         comment '是否中心店:1中心店,0其他重点门店',
    platform_name   string         comment '渠道:online线上/offline线下',
    period_type     string         comment '周期类型:C上线后/L上线前/H去年同期',
    item_sale_cnt   decimal(32,4)  comment '销售数量',
    pay_amt         decimal(32,4)  comment '销售额',
    margin_account  decimal(32,4)  comment '毛利额',
    passenger_flow  bigint         comment '客流'
)
comment 'O2O效益分析-重点门店商品销售明细(线上+线下)'
partitioned by (pt bigint comment '跑批日期(yyyyMMdd)');
```

### 3.3 Goals Wide Table
```sql
create table if not exists ${dsl_analysis}.analysis_analysis_assortment_o2_store_cata_items_goals_df (
    store_code      bigint        comment '门店编码',
    item_code       bigint        comment '商品编码',
    is_key_store    bigint        comment '是否中心店:1中心店,0其他重点门店',
    period_type     string        comment '周期类型:C上线后/L上线前/H去年同期',
    platform_name   string        comment '渠道:online线上/offline线下',
    lx_new          string        comment '还原后优先级标签(is_3he1_fl)',
    pay_amt         decimal(38,4) comment '销售额',
    margin_account  decimal(38,4) comment '毛利额',
    passenger_flow  bigint        comment '客流',
    lx_raw          string        comment '原始优先级标签(reason_zfl)'
)
comment 'O2O效益分析-重点门店商品效益宽表(双标签源)'
partitioned by (pt bigint comment '跑批日期(yyyyMMdd)');
```

### 3.4 Diagnostic Summary Table (DWS)
```sql
create table if not exists ${dsl_analysis}.dws_o2o_key_store_benefit_period_summary_df (
    store_group      string        comment '门店群:所有重点门店/中心店/O2O其他重点店',
    strategy_tag     string        comment '策略标签:城市top500品/城市top200/跨渠道top80/o2o中心店品',
    platform_name    string        comment '渠道:all整体/online线上/offline线下',
    period_type     string        comment '周期:C上线后/L上线前/H去年同期',
    pay_amt         decimal(32,4) comment '销售额(元)',
    margin_account   decimal(32,4) comment '毛利额(元)',
    store_cnt       bigint         comment '参与统计的门店数',
    tag_item_cnt     bigint        comment '标签商品店品数',
    tag_dx_item_cnt  bigint        comment '标签商品动销店品数',
    cata_item_cnt    bigint        comment '目录内店品总数',
    cata_dx_item_cnt bigint        comment '目录内动销店品总数',
    tag_source       string        comment '标签来源:restored/raw'
)
comment 'O2O重点店效益分析-指标明细排障表'
partitioned by (pt bigint comment '跑批日期(yyyyMMdd)');
```

Runtime additions used by the dual-source card pipeline:
- Goals table `analysis_analysis_assortment_o2_store_cata_items_goals_df` carries `lx_raw` beside the existing `lx_new`.
- DWS carries `tag_source` (`restored` for `is_3he1_fl`, `raw` for `reason_zfl`) and keeps `store_cnt` for store-average evidence.
- The detail tag table is not changed by card-scope selection.

### 3.5 Final Executive Card Table (ADS)
```sql
create table if not exists ${dsl_analysis}.ads_o2o_key_store_benefit_card_df (
    store_group        string        comment '门店群:所有重点门店/中心店/O2O其他重点店',
    strategy_tag       string        comment '策略标签:城市top500品/城市top200/跨渠道top80/o2o中心店品',
    order_seq          int           comment '行排序:1销售额/2毛利额/3标签动销率/4目录内动销率',
    metric_name        string        comment '指标名称:销售额/毛利额/topXX商品动销率/目录内动销率',
    all_post           decimal(18,2) comment '整体-上线后',
    all_pre            decimal(18,2) comment '整体-上线前',
    all_diff           decimal(18,2) comment '整体-差异值',
    all_diff_ratio     decimal(18,4) comment '整体-增幅(百分比)',
    o2o_post           decimal(18,2) comment 'O2O渠道-上线后',
    o2o_pre            decimal(18,2) comment 'O2O渠道-上线前',
    o2o_diff           decimal(18,2) comment 'O2O渠道-差异值',
    o2o_diff_ratio     decimal(18,4) comment 'O2O渠道-增幅(百分比)',
    offline_post       decimal(18,2) comment '线下渠道-上线后',
    offline_pre        decimal(18,2) comment '线下渠道-上线前',
    offline_diff       decimal(18,2) comment '线下渠道-差异值',
    offline_diff_ratio decimal(18,4) comment '线下渠道-增幅(百分比)',
    c_store_cnt       bigint        comment '兼容字段(当前卡片透视为空)',
    l_store_cnt       bigint        comment '兼容字段(当前卡片透视为空)',
    c_avg_tag_items   decimal(18,1) comment '上线后店均标签品数',
    l_avg_tag_items   decimal(18,1) comment '上线前店均标签品数',
    c_avg_tag_dx      decimal(18,1) comment '上线后店均标签动销品数',
    l_avg_tag_dx      decimal(18,1) comment '上线前店均标签动销品数',
    c_avg_cata_items  decimal(18,1) comment '上线后店均目录品数',
    l_avg_cata_items  decimal(18,1) comment '上线前店均目录品数',
    c_avg_cata_dx     decimal(18,1) comment '上线后店均目录动销品数',
    l_avg_cata_dx     decimal(18,1) comment '上线前店均目录动销品数',
    remark            string        comment '备注说明(如动销率看整体即可)',
    tag_source        string        comment '标签来源:restored/raw'
)
comment 'O2O重点店效益分析-终态卡片交付表(对齐Image #1汇报格式)'
partitioned by (pt bigint comment '跑批日期(yyyyMMdd)');
```

The ADS table also carries `tag_source` (`restored`/`raw`) as the final non-partition column. The Excel exporter filters this column according to `--card-scope`; it does not rerun upstream ETL under `--export-only`.

## 4. Compute Engine Optimization & Tuning

1. **Static Partition Pruning**:
   - Never use `where b.stat_date in (select day_id from ...)` when scanning partitioned transaction tables.
   - Always resolve continuous date ranges (`min(day_id)` and `max(day_id)`) and query with `where b.stat_date between ... and ...`.
2. **Sub-table Isolation**:
   - Decompose offline table ingestion into 3 independent parallel sub-jobs (C, L, H).
   - This keeps individual scan size under 85 partitions and runtime within 15~25s per sub-job.
3. **MapJoin Ingestion**:
   - Small tables (`key_store`, `tmp_special_date`, `dim_store`) must be flagged with `/*+ mapjoin(...) */` to eliminate heavy distributed reduce shuffles.
4. **Execution Hints**:
   - `odps.sql.type.system.odps2 = true`
   - `odps.sql.submit.mode = script`
   - Running in `dsl_ads` project or setting appropriate queue resources dramatically accelerates slot allocation.
