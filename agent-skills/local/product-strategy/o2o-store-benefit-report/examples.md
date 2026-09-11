# O2O Store Benefit Report — Usage Examples

Executable examples covering historical replication (0617), latest production refresh (0907), and automated Excel export.
Commands below assume the `product_strategy` checkout. From `mac-bootstrap/template`, replace `.claude/skills/o2o-store-benefit-report` with `agent-skills/local/product-strategy/o2o-store-benefit-report`.

## Example 1: Run Historical Partition (20260617, explicit restored 11-card scope)

Replicates a historical evaluation partition with C vs H YoY metrics. The explicit
scope keeps the preserved `is_3he1_fl` view instead of the default four raw-priority cards:

```bash
uv run python .claude/skills/o2o-store-benefit-report/scripts/helper.py \
  --cutoff 20260617 \
  --version 20260408 \
  --baseline H \
  --card-scope restored_11 \
  --export
```

### Expected Output Shape:
- 11 cards: 4 `所有重点门店` cards, 4 `中心店` cards, 3 `O2O其他重点店` cards.
- Each card contains sales, margin, tag sell-through, and catalog sell-through rows.
---

## Example 2: Run Production Partition (20260907, C vs H YoY)

Executes evaluation for the latest version launched on 2026-07-05. H is the default baseline and the default Excel scope is the four `reason_zfl` cards for `所有重点门店`:

```bash
uv run python .claude/skills/o2o-store-benefit-report/scripts/helper.py \
  --cutoff 20260907 \
  --export
```

### Auto-detected parameters:
- `project_yyyyMMdd`: Auto-detected as `20260705`
- C Window: `2026-07-05` ~ `2026-09-07`
- Baseline: H (YoY; default)
- Cards exported: 4 (`reason_zfl` × `所有重点门店`)

To export the preserved restored-priority 11-card view instead:

```bash
uv run python .claude/skills/o2o-store-benefit-report/scripts/helper.py \
  --cutoff 20260907 \
  --card-scope restored_11 \
  --export
```
---

## Example 3: Ad-hoc Query for Executive Card Table

```sql
select 
    store_group,
    strategy_tag,
    tag_source,
    metric_name,
    all_post, all_pre, all_diff, 
    concat(round(all_diff_ratio * 100, 2), '%') as all_ratio_str,
    o2o_post, o2o_pre, o2o_diff, 
    concat(round(o2o_diff_ratio * 100, 2), '%') as o2o_ratio_str,
    offline_post, offline_pre, offline_diff, 
    concat(round(offline_diff_ratio * 100, 2), '%') as offline_ratio_str,
    remark
from dsl_analysis.ads_o2o_key_store_benefit_card_df
where pt = 20260907
  and tag_source = 'raw'
  and store_group = '所有重点门店'
order by strategy_tag, order_seq
;
```

---

## Example 4: Export Formatted Excel Directly Without Re-running ETL

When the MaxCompute ADS partition is already computed, use `--export-only` to regenerate the default four-card report without repeating upstream calculations:

```bash
uv run python .claude/skills/o2o-store-benefit-report/scripts/helper.py \
  --cutoff 20260907 \
  --export-only
```

Choose another scope explicitly when needed:

```bash
uv run python .claude/skills/o2o-store-benefit-report/scripts/helper.py \
  --cutoff 20260907 \
  --card-scope restored_11 \
  --export-only
```

---

## Example 5: Python Direct Pipeline Ingestion

```python
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(".claude/skills/o2o-store-benefit-report/scripts").resolve()),
)
from helper import O2OStoreBenefitRunner

runner = O2OStoreBenefitRunner(cutoff_date="20260907")  # H + raw_all_stores defaults
runner.run_pipeline()
excel_path = runner.export_excel()
print("Saved to:", excel_path)
```
