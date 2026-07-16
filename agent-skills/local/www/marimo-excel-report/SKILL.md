---
name: marimo-excel-report
description: Build and revise Marimo business Excel reports with shared bilingual column contracts, seasonal table and chart semantics, filter-aware TwoCellAnchor charts, and WPS/Office verification. Use when changing merchandise workbook, reports CSV, Excel chart styling, chart anchors, or spreadsheet export QA.
---

# Marimo Excel Report

Build the workbook as a projection of an existing analysis batch. Keep business
classification in the analysis layer; use the output layer only for mapping,
serialization, styling, charts, and packaging.

## Workflow

1. Read `marimo/README.md`, `marimo/merchandise/README.md`, the relevant output
   module, and its tests. Confirm the current worktree before editing.
2. Pin the table contract in one presentation module.
   - Share the same `english(中文)` mappings between workbook and reports CSV.
   - Serialize peak/trough month arrays from the existing profile.
   - Blank seasonal fields when `strict_pass` is false.
3. Build workbook sheets from those presentation frames.
   - Keep one summary sheet and one detail sheet per business dimension.
   - Keep item blocks contiguous; add the dark-gray thick bottom border only at
     each block boundary.
   - Restrict semantic row fills to the business table range.
4. Build one chart per item block.
   - Use a `TwoCellAnchor` with zero-based markers: first item row at `_from`,
     last item row boundary at `to`.
   - Reserve at least 20 columns of chart width unless the user specifies more.
   - Keep observed and analysis line colors stable.
   - Reuse the serialized `season_phase` for chart bands and markers.
   - For WPS, make the peak band the primary `AreaChart`; combine the
     `LineChart` afterward. Do not rely on a hidden secondary-axis area layer.
5. Run `$marimo-etl-test`.
   - Run the focused host pytest from the `www` project boundary.
   - Run the current worktree in a one-shot Docker Compose container when the
     workbook is headed for acceptance.
6. Generate a workbook from the retained real review run, then verify:
   - bilingual values and month arrays;
   - fills stop at the table boundary;
   - every chart is a `TwoCellAnchor` with exact row bounds and width;
   - OOXML contains the intended area and line chart order;
   - no formulas or broken references appear unexpectedly.
7. Hand the workbook to the user for WPS/Office filtering and visual QA. Treat
   human acceptance as a hard gate when requested; do not call the visual check
   passed before confirmation.

Read [references/seasonal-chart-pattern.md](references/seasonal-chart-pattern.md)
when implementing or debugging chart bands, markers, anchors, or OOXML checks.

Open [examples/seasonal-chart-example.xlsx](examples/seasonal-chart-example.xlsx)
and [examples/seasonal-chart-example.png](examples/seasonal-chart-example.png)
when matching the approved table-and-chart layout. Treat the workbook as a
visual/structural reference, not a source of business data.

## Completion

Finish only when focused host and Docker tests pass, the generated workbook
passes structural inspection, and any requested WPS/Office acceptance is
explicitly confirmed.
