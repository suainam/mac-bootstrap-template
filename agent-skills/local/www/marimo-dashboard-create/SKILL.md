---
name: marimo-dashboard-create
description: Creates or updates Merchandise Marimo dashboard pages using the repository's local page registry, notebook, ETL, theme, Docker, and preview contracts. Use when adding or materially changing a page, navigation, theme integration, data source, serve output, or dashboard structure under `www/marimo/merchandise`.
---

# Marimo Dashboard Create

## Start From Repository Truth

Work in a dedicated Marimo worktree when `main` is dirty or shared. Read:

- `marimo/README.md`
- `merchandise/AGENTS.md`
- `merchandise/CONTEXT.md`
- `merchandise/docs/dashboard-development-contract.md`
- `merchandise/config/dashboard_pages.yaml`
- the related notebook, data helper, ETL helper, tests, theme, and deploy workflow

Remote `marimo`, `marimo-next`, and `marimo-previews/*` directories are deploy trees, not Git
authority. Use workflow SHA and image revision labels for deployment truth.

## Workflow

1. Confirm the route, user question, source tables, current serve outputs, filter scope, and
   empty/error/stale states.
2. Design `raw -> agg -> serve` before composing the page. The notebook reads serve output;
   stable transformations belong in `lib/` or ETL.
3. Reuse `lib.theme` tokens and helpers. Keep page CSS narrowly namespaced.
4. Update the full contract chain in one change:
   - page registry and README status
   - navigation and smoke lists
   - ETL task, `all` order, and workflow allowlist
   - producer and consumer tests
   - export/download behavior and relevant documentation
5. Keep code deployment and data refresh separate. A successful preview can still contain old
   or missing serve data.

## Registry Contract

Register each formal page with a unique route, title, kind, status, navigation group, ETL task,
smoke state, and serve prefix. For every serve output declare:

- `name`
- `granularity`
- `unique_key`
- `required_columns`
- `snapshot`
- `empty_behavior`

Bind existing producer and consumer pytest node IDs. Old-page exceptions belong only in the
exact, shrink-only baseline; never add a broad `legacy` bypass or raise counts to hide new debt.

## Page Rules

- Reuse the existing page shell, header, filter, KPI, section, table, and state patterns.
- Label global and local filter scope in the UI.
- Require a concrete selection for hierarchical views that cannot represent an aggregate.
- Compute ratios from summed components and display percentages/percentage points explicitly.
- Keep technical keys available for filtering and sorting even when hidden from display.
- Do not add a Docker service, port, or deployment unit unless the requested architecture
  requires it.

Read `EXAMPLES.md` for page skeleton and filter patterns.

## Validation

Run syntax and registry checks:

```bash
python -m py_compile merchandise/notebooks/<page>.py merchandise/lib/<module>.py
make check
```

For every pytest/regression decision, invoke `$marimo-etl-test`; it owns Docker-authoritative
commands and environment selection. Do not duplicate uv or pytest environment commands here.

Visible changes require a real preview at desktop and narrow viewport, plus at least one key
interaction and evidence that content does not overlap. Verify the preview's branch, port,
image revision, and data snapshot before accepting screenshots.

Commit and push Marimo first. Update the parent `www` submodule pointer only after the child
commit exists remotely.
