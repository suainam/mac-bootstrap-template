---
name: sankey-flow-analysis
description: Builds and iterates Sankey-based flow analysis assets, including transition logic, narrative framing, and local HTML report pages. Use when the user asks to analyze changes, crossovers, inflow/outflow, migration,新增/汰换/流失, source-to-target movement, or to turn flow data into a Sankey chart and presentation-ready story.
---

# Sankey Flow Analysis

## Quick start

Use this skill when the work includes:

- state changes across two or more periods
- source-to-target movement between categories
-新增 / 汰换 / 流失 / 迁移 / 承接
- Sankey charts, flow reports, or presentation wording for flow analysis

Default output:

1. Clarify the flow structure, metrics, and story order.
2. Update the Sankey chart or report assets.
3. Verify the rendered page after major visual or interaction changes.

## Workflow

### 1. Gather the flow model

Before editing, confirm or infer:

- time scope or comparison scope
- source states and target states
- whether there are virtual states such as `新增`, `流失`, `汰换`, `未出现`
- width metric, such as sales, counts, users, or volume
- the main business question, such as growth, loss, mix shift, or structural optimization

If the user already has final presentation language, align the chart and summary to that language instead of inventing a new framing.

### 2. Build the narrative

Use the Sankey to support a clear reading order:

1. Explain the stable base or unchanged portion.
2. Highlight the positive or target flows.
3. Explain loss, downgrade, or carry-over flows.
4. End with the net effect, key conclusion, or summary sentence.

Do not hard-code business labels. Reuse the domain terms the user already uses.

### 3. Edit the assets

Prefer to separate:

- graph-only files for node layout, colors, labels, and interactions
- report-shell files for KPI cards, explanation blocks, and summary math

Keep these default conventions unless the user changes them:

- use a two-layer Sankey unless an extra action layer is explicitly needed
- move flow labels outside the bands when readability is better
- use virtual nodes when a flow needs visible start or end anchors
- keep chart logic and report wording on the same metric and wording system

### 4. Verify before finishing

After substantial HTML or chart changes:

1. reload the local page
2. confirm embedded graph assets load
3. check that narration, KPI values, and Sankey labels use the same口径
4. if interactions changed, test dragging or layout behavior

## Deliverables

Return:

- updated file path(s)
- short summary of changes
- any remaining verification gaps

## Reference

See [REFERENCE.md](REFERENCE.md) for reusable flow-analysis guidance, visual design rules, and a concrete catalogue in/out example.
