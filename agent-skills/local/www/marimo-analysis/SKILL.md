---
name: marimo-analysis
description: Builds or refactors reproducible Merchandise Marimo analysis and notebook data flows with explicit metric, filter, multi-source, serve, and consumer contracts. Use when changing dashboard metrics, ratios, filters, chart data, notebook reactivity, exports, or analytical interpretation under `www/marimo/merchandise`.
---

# Marimo Analysis

Use Marimo as a reproducible data app, not a scratchpad. Work in the authoritative Marimo Git
worktree and read local `AGENTS.md`, `CONTEXT.md`, the Dashboard development contract, page
registry, related ETL/data helpers, and tests.

Read `EXAMPLES.md` for filter-scope, ratio-formatting, and multi-source examples.

## Design Rules

- Separate loading, transformation, visualization, and export cells.
- Pull stable transformations and business calculations into named `lib/` functions.
- Read small stable serve outputs; do not make notebooks read `raw/` or `agg/` directly.
- Preserve reactive dependencies and avoid hidden mutation or cell-order assumptions.
- State metric grain, numerator, denominator, time basis, exclusions, and display unit.
- Sum numerators and denominators before calculating ratios; do not average ratios.
- Distinguish percentages from percentage-point changes.
- Label global, section, and detail filter scopes.
- Intersect valid shared keys across all sources before building controls.
- Show guidance or an empty state when a hierarchy requires a concrete region/province.
- Keep page and export on the same run/snapshot, or label the difference explicitly.
- Reuse `lib.theme` and established layout helpers before adding notebook-only styles.

## Data Contract

When analysis changes a serve output, update the registry with its `granularity`, `unique_key`,
`required_columns`, `snapshot`, and `empty_behavior`. Update both sides:

- Producer tests prove files, schema, grain, snapshot, and empty behavior.
- Consumer tests load producer-shaped fixtures and prove filters, metrics, and display data.
- Cross-source tests prove snapshot and shared-key consistency.

Bind those real pytest node IDs in the page registry. Do not use a filename text match as the
only producer/consumer proof.

## Refactoring Exploration

1. Preserve the original business question and expected output.
2. Identify source and serve grain before changing charts.
3. Extract stable transformations into testable functions.
4. Add checks for shape, required columns, nulls, aggregate totals, shared dimensions, and
   empty data.
5. Keep final notebook cells focused on controls, charts/tables, caveats, and export.

## Validation

- Run `python -m py_compile merchandise/notebooks/<page>.py` for syntax.
- Run `make check` when registry, navigation, smoke, ETL, serve, README, or theme debt changes.
- Invoke `$marimo-etl-test` for all pytest and runtime validation. Docker is the test authority;
  host uv is optional fast feedback only when derived from Docker dependency inputs.
- For visible changes, validate a real revision-matched preview at desktop and narrow viewport
  and exercise the relevant filter/selection flow.

Commit and push the Marimo child repository before updating the parent submodule pointer.
