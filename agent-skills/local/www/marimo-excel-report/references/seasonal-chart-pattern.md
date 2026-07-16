# Seasonal Chart Pattern

## Source Of Truth

- Consume `AnalysisBatch.results` and `AnalysisBatch.series`.
- Map existing `season_phase`; never infer peak/trough again in workbook code.
- Keep helper series outside the A:L filter range and compress their columns.
- Leave helper cells unfilled so table coloring ends at the business contract.

## Approved Layout Example

Use `examples/seasonal-chart-example.xlsx` as the approved layout reference.
It contains synthetic data and demonstrates:

- one bilingual monthly table ending at column L;
- a one-column gutter before compressed chart-helper columns;
- a 20-column-wide chart aligned to the first and last rows of one item block;
- a primary peak-season area band behind stable observed/analysis lines;
- peak triangle and trough diamond markers;
- a thick gray border marking the item block end.

Use `examples/seasonal-chart-example.png` for a quick visual comparison. Open
the workbook when checking filters, anchors, series order, or exact cell styles.

## WPS-Compatible Layer Order

Use a primary `AreaChart` for the peak background. Set its band values to the
item chart ceiling for peak months and `0` for other months. A practical ceiling
is `max(observed_value, analysis_value) * 1.05`, bounded below by `1`.

Style the area with peak fill `FCE4D6` and no outline. Combine the foreground
`LineChart` afterward:

```python
peak_background += line_chart
```

This order matters. WPS may omit an area layer placed on a hidden secondary
axis even when the generated OOXML is valid.

Keep peak and trough markers as a second visual channel:

- peak: triangle, fill `FCE4D6`, dark orange border;
- trough: diamond, fill `DDEBF7`, dark blue border;
- marker series: no connecting line.

## Anchor Contract

`AnchorMarker` uses zero-based row and column positions. For Excel data rows
`start..end`, anchor the chart with:

```python
TwoCellAnchor(
    editAs="twoCell",
    _from=AnchorMarker(col=chart_start_col, row=start - 1),
    to=AnchorMarker(col=chart_end_col, row=end),
)
```

Use a 20-column difference between `to.col` and `_from.col`. Filtering every
row in an item block should hide the chart; restoring the filter should restore
its original bounds.

## Structural Checks

After saving and reopening the workbook, assert:

- all charts use `TwoCellAnchor(editAs="twoCell")`;
- anchor rows match item block boundaries;
- chart width equals the agreed column span;
- combined chart order is `AreaChart`, then `LineChart`;
- line colors and marker colors remain stable;
- cells after the business table have no semantic fill.

Inspect `xl/charts/chart*.xml` as the final authority when openpyxl does not
round-trip combined-axis metadata through its object model. Count every chart,
check `<areaChart>` precedes `<lineChart>`, and reject missing series references.

## Acceptance Trap

Valid OOXML and green pytest do not prove WPS rendering. Generate the actual
review workbook and require a WPS/Office check for chart bands, filtering,
restoration, label readability, and alignment before publication.
