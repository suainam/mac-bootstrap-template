---
name: franchise-store-sankey-analysis
description: Sankey skill for franchise-store catalogue analysis and reusable two-period flow graphs. Use when the user wants目录内/目录外 flow analysis, a reusable Sankey HTML/SVG, or a report page generated from new data blocks.
---

# Franchise Store Sankey Analysis

Build reusable Sankey HTML/SVG and report HTML for franchise-store catalogue analysis and adjacent two-period flow analysis.

## Quick start

1. Read the latest data block first.
Completion criterion: you know which block is current and whether the total result is positive or negative.

2. Read the user-facing wording template.
Open [references/WORDING_TEMPLATES.md](references/WORDING_TEMPLATES.md) when the user wants report text or Sankey explanation that follows the established business style.
Completion criterion: you can mirror the user template instead of inventing new phrasing.

3. Read the data contract only when input shape is unclear.
Open [references/DATA_INPUT_CONTRACT.md](references/DATA_INPUT_CONTRACT.md) and [REFERENCE.md](REFERENCE.md) for metric mapping and standard conclusion formulas.
Completion criterion: every metric in the page has a source and a meaning.

4. Build a ledger before drawing.
Open [references/SANKEY_QA_CHECKLIST.md](references/SANKEY_QA_CHECKLIST.md) when the graph contains constructed/anonymized values, video-sized SVG labels, or user-visible financial numbers.
Completion criterion: every node total, flow amount, bridge formula, and label position has passed the checklist.

5. Lock the visual contract before drawing.
Open [references/SANKEY_STYLE_CONTRACT.md](references/SANKEY_STYLE_CONTRACT.md) when creating or revising a Sankey SVG/HTML graph.
Completion criterion: the graph follows the stable two-column style, endpoint labels, unit policy, and browser-fit rules.

6. Reuse the stable HTML skeleton.
Open [templates/report_shell.html](templates/report_shell.html), [templates/report_style.css](templates/report_style.css), and [templates/graph_style.css](templates/graph_style.css) when building or refactoring the pages.
Completion criterion: the report keeps the stable section order and the graph/report styles stay aligned.

7. Verify wording and structure before finishing.
Check the graph HTML and report HTML use the same numbers, the same `汰换` wording, and `%` instead of `pct`.
Completion criterion: no stale sign, no wording drift, no section-order drift, and no SVG text collision.

## Non-negotiables

- Two-layer Sankey only unless the user asks otherwise
- Prefer `汰换`; avoid `损耗`
- Prefer `%`; avoid `pct`
- Explain `存量盘` first, then positive structure actions, then `汰换`, then the net result
- If total result is negative, do not reuse old positive-conclusion wording
- Labels belong beside the relevant node/flow endpoint, not on top of Sankey bands, unless the user explicitly asks for inline labels
- Never ship a graph from visual judgment alone; run a numeric ledger and a text-collision check first
- Preserve the stable visual contract; do not invent a new Sankey style while fixing labels or data

## Reference map

- Metric defaults and formulas: [REFERENCE.md](REFERENCE.md)
- Input contract: [references/DATA_INPUT_CONTRACT.md](references/DATA_INPUT_CONTRACT.md)
- Example wording: [references/WORDING_TEMPLATES.md](references/WORDING_TEMPLATES.md)
- Example source section from `data_0617.md`: [references/REFERENCE_DATA_EXAMPLE.md](references/REFERENCE_DATA_EXAMPLE.md)
- Sankey QA checklist: [references/SANKEY_QA_CHECKLIST.md](references/SANKEY_QA_CHECKLIST.md)
- Sankey style contract: [references/SANKEY_STYLE_CONTRACT.md](references/SANKEY_STYLE_CONTRACT.md)
- Report shell: [templates/report_shell.html](templates/report_shell.html)
- Report CSS: [templates/report_style.css](templates/report_style.css)
- Graph CSS: [templates/graph_style.css](templates/graph_style.css)
