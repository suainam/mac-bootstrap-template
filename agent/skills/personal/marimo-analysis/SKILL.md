---
name: marimo-analysis
description: Use when building or refactoring marimo notebooks for Python data apps, reproducible analysis, interactive reports, or browser-first local workflows.
---

# Marimo Analysis

Use marimo as a reproducible data app, not a scratchpad.

Guidelines:

- Keep data loading, transformation, visualization, and export in separate cells.
- Put configuration and paths near the top.
- Prefer reactive UI controls for user-facing parameters.
- Avoid hidden global mutation that makes cell order matter.
- Cache expensive reads or transformations when the project convention supports
  it.
- Keep browser-facing notebooks safe to run from a fresh container.

When converting messy notebook exploration:

1. Preserve the original question and output target.
2. Pull stable transformation logic into named functions.
3. Add lightweight checks for shape, nulls, and aggregate totals.
4. Make the final cells read like a report: input assumptions, charts/tables,
   caveats, and export.
