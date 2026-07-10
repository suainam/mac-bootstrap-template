# Data Input Contract

The skill works best when the user provides three current data blocks:

1. `公司发货数据`
2. `门店数据`
3. `桑基图数据`

## Minimum current-input contract

### 1. 公司发货数据

Expected fields:

- year
- store count
- sale
- cost
- profit
- delta / yoy when available

Primary use:

- headline background
- company shipment profit result

### 2. 门店数据

Preferred fields:

- 目录内商品数占比
- 目录内销售额占比
- 目录内毛利额占比
- 全店近90天周转
- total sale / total profit / total 客流 summary

Primary use:

- report conclusion
- KPI cards

### 3. 桑基图数据

Expected dimensions:

- year
- flow type: `保持不变 / 内外切换 / 新增 / 消失`
- is inner or outer
- lt90 sale
- optional profit / 客流

Primary use:

- Sankey node/link widths
- flow explanation
- net contribution formula

## Optional reference-input contract

If the user provides an older `参考数据` block, use it only as style/context reference.
Do not let older positive/negative conclusions overwrite the newest current data block.

## Common derived metrics

- 目录内销售额占比变化
- 目录内毛利额占比变化
- 目录内商品数占比变化
- 存量盘变化
- `目录外 -> 目录内` 表观变化
- `新增 -> 目录内` 正向贡献
- `目录内汰换`
- `目录外汰换`
- final net result

## Priority rule

If `现在的数据如下` exists, treat that as the current truth.
Older example numbers are wording references, not final-result truth.
