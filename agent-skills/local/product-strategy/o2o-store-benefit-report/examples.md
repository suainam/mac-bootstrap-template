# O2O Store Benefit Report — Usage Examples

Executable examples covering historical replication (0617), latest production refresh (0907), and automated Excel export.

## Example 1: Run Historical Partition (20260617, C vs H YoY)

Replicates Image #1 cards comparing 2026-04-08 ~ 2026-06-17 with 2025-04-08 ~ 2025-06-17:

```bash
uv run python ~/.agents/skills/o2o-store-benefit-report/scripts/helper.py \
  --cutoff 20260617 \
  --version 20260408 \
  --baseline H \
  --export
```

### Expected Output Summary:
- **Other Key Stores - 城市top500品**: Revenue +6.76%, Margin +8.27%, Tag DX 96.31% (+1.22%)
- **Other Key Stores - 城市top200**: Revenue +12.46%, Margin +8.75%, Tag DX 97.50% (+0.72%)
- **Other Key Stores - 跨渠道top80**: Revenue +7.56%, Margin +8.43%, Tag DX 98.41% (+4.30%)
- **Center Stores - 城市top500品**: Revenue +26.51%, Margin +21.94%, Tag DX 97.04% (+2.62%)
- **Center Stores - 城市top200**: Revenue +29.57%, Margin +29.63%, Tag DX 98.53% (+1.21%)
- **Center Stores - 跨渠道top80**: Revenue +24.22%, Margin +27.27%, Tag DX 99.01% (+2.98%)

---

## Example 2: Run Production Partition (20260907, C vs L MoM)

Executes evaluation for latest version launched on 2026-07-05, including honeycomb products (`o2o中心店品`):

```bash
uv run python ~/.agents/skills/o2o-store-benefit-report/scripts/helper.py \
  --cutoff 20260907 \
  --baseline L \
  --export
```

### Auto-detected parameters:
- `project_yyyyMMdd`: Auto-detected as `20260705`
- C Window: `2026-07-05` ~ `2026-09-07` (65 days)
- L Window: `2026-05-01` ~ `2026-07-04` (65 days)
- Cards produced: 7 cards (3 for Other Key Stores, 4 for Center Stores including Honeycomb Products)

---

## Example 3: Ad-hoc Query for Executive Card Table

```sql
select 
    store_group,
    strategy_tag,
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
order by store_group, strategy_tag, order_seq
;
```

---

## Example 4: Export Formatted Excel Directly Without Re-running ETL

When MaxCompute ADS partition is already computed, use `--export-only` to instantaneously regenerate the formatted Excel report without repeating upstream calculations:

```bash
uv run python .agents/skills/o2o-store-benefit-report/scripts/helper.py \
  --cutoff 20260907 \
  --export-only
```

---

## Example 5: Python Direct Pipeline Ingestion

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / ".agents/skills/o2o-store-benefit-report/scripts"))
from helper import O2OBenefitRunner

runner = O2OBenefitRunner(cutoff_date="20260907", baseline_type="L")
runner.run_pipeline()
excel_path = runner.export_excel(output_dir="topics/o2o_store/04_outputs/tables")
print("Saved to:", excel_path)
```
