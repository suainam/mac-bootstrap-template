# Examples

## User trigger

> 这个 SQL 指标口径很多，帮我先规划成 marimo 看板结构。

Use this skill to separate data sources, shared dimensions, section-specific
filters, and final notebook cells before editing code.

## Mixed filter scope

When one page has global KPIs plus item-level detail, make the control scope
explicit:

```text
Global controls:
- tracking_type
- catalog_version
- result_level
- province / region

Detail-only controls:
- category
- item keyword
- item status
```

Put a short note below the global filters when a hierarchy requires a concrete
selection:

```text
Tracking type, batch, and result level control the full dashboard. If result
level is province or region, select the corresponding area to show the right
data.
```

## Multi-source dimensions

Before building dropdown options, align shared keys across every source:

```python
future_batches = future_catalog_versions(summary_df, item_df, productivity_df)
summary_df = exclude_catalog_versions(summary_df, future_batches)
item_df = exclude_catalog_versions(item_df, future_batches)
productivity_df = exclude_catalog_versions(productivity_df, future_batches)
```

This prevents a batch from being selectable in the header while one section has
already hidden it.

## Ratio display

Use the unit business users expect:

```python
format_ratio_percent(0.00066)  # "0.07%"
```

Do not show raw decimals for percent-like fields unless the business explicitly
asks for them.
