# Reference Data Example

This file preserves the reference-style sections extracted from `data_0617.md`.

Use it for:

- expected data block layout
- expected report tone
- expected Sankey explanation rhythm

Do not treat these numbers as current truth when the user also provides a newer `现在的数据如下` block.

## Example company data

```sql
yr  is_tg  is_kbtb_ct  store_cnt  tsf_sale_amt    tsf_cost_amt    profit       ct_delta     ct_yoy
2026  1    1           4,112.00   621,424,726.11  556,844,664.63  64,580,061.48  5,957,270.47  10.16%
2025       1           4,112.00   620,587,654.52  561,964,863.51  58,622,791.01
```

## Example store summary data

```sql
is_kbtb_ct  year_id  store_cnt  avg_store_item  lt90_sale_amt  lt90_sale_profit_sum  lt90_kl
1           2026     4,112.00   2,299.90        1,046,176,486.75  445,375,439.05    38,163,072.00
1           2025     4,112.00   2,419.33        1,041,505,852.46  441,787,719.58    39,081,051.00
```

## Example Sankey rows

```sql
年份  状态转换  是否目录内  门店数   店均商品数  条目数       近90天销售      近90天毛利      近90天客流
2026  保持不变  0         4,096.00 867       3,552,407.00 125,042,604.21 49,440,167.76 4,100,133.00
2025  保持不变  0         4,096.00 867       3,552,464.00 134,495,299.18 53,832,395.36 4,494,791.00
2026  保持不变  1         4,110.00 321       1,321,208.00 416,252,660.37 180,493,721.13 14,246,239.00
2025  保持不变  1         4,110.00 321       1,321,208.00 466,180,989.87 204,767,775.17 15,948,232.00
```

## Usage rule

Use this file for format memory only.
Use the newest user-provided block for final numbers and final sign.
