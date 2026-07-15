---
name: marimo-analysis
description: Use when building or refactoring marimo notebooks for Python data apps, reproducible analysis, interactive reports, or browser-first local workflows.
---

# Marimo Analysis

Use marimo as a reproducible data app, not a scratchpad.

Repo-specific reality for `www/marimo`:

- Python project boundary is `www/`, not `marimo/`; `pyproject.toml` and
  `uv.lock` live at the workspace root.
- Notebook changes usually touch four layers together: notebook, `lib/`,
  `etl/fetch_data.py`, and tests.
- Current deploy/handoff contract is documented in `marimo/README.md`,
  `marimo/merchandise/docs/ops-knowledge-base.md`, and
  `marimo/merchandise/docs/deployment-update.md`.
- Remote `marimo` / `marimo-next` / `marimo-previews/*` are deploy trees, not
  authoritative Git worktrees.

Guidelines:

- Keep data loading, transformation, visualization, and export in separate cells.
- Put configuration and paths near the top.
- Prefer reactive UI controls for user-facing parameters.
- Avoid hidden global mutation that makes cell order matter.
- Cache expensive reads or transformations when the project convention supports
  it.
- Keep browser-facing notebooks safe to run from a fresh container.
- Match the repo's current `raw/agg/serve` layering instead of inventing ad hoc
  file flows.
- Keep ratios honest: sum numerators/denominators first, then compute ratios.
- Reuse `lib/theme.py` and existing helper patterns before adding notebook-only
  styling or duplicated transforms.
- Name mixed filter scopes in the UI. Users should not have to infer whether a
  filter controls all KPIs/tables or only one detail section.
- Handle hierarchical dimensions deliberately. If a province or region view
  needs a concrete province/region, show guidance or an empty state until that
  value is selected.
- Format business ratios in the unit users expect. Percent-like values should
  display as percentages or percentage points, not raw decimals.
- For multi-source dashboards, remove invalid shared keys consistently across
  all frames before building controls, so a hidden batch in one section cannot
  remain selectable elsewhere.

When converting messy notebook exploration:

1. Preserve the original question and output target.
2. Pull stable transformation logic into named functions.
3. Add lightweight checks for shape, nulls, aggregate totals, and shared
   dimension coverage across sources.
4. Make the final cells read like a report: input assumptions, charts/tables,
   caveats, and export.
5. If the notebook depends on new ETL outputs or changed schema, update the
   corresponding tests and ETL path in the same change.

Validation:

- Quick syntax check:
  `python -m py_compile marimo/merchandise/notebooks/<page>.py`
- Pytest/regression:
  route to `marimo-etl-test`
- Host-side project env:
  `cd <www-root> && UV_CACHE_DIR=.uv-cache uv run --extra test ...`
