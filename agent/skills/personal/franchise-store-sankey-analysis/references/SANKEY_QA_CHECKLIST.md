# Sankey QA Checklist

Use this checklist before shipping a Sankey graph, especially when values are anonymized or constructed to match a known narrative.

## 1. Ledger First

Build a ledger before drawing.

Completion criterion:
- Every visible node total equals the sum of its incoming or outgoing flows.
- The 2025 total and 2026 total are explicitly computed from main states, not from virtual nodes.
- The bridge formula closes to the stated net result.

Required ledger rows for any Sankey:
- `source main state total = sum(source-side outgoing endpoint values)`
- `target main state total = sum(target-side incoming endpoint values)`
- `source total = sum(source main state totals)`
- `target total = sum(target main state totals)`
- `bridge formula = positive changes - negative changes = net result`

Franchise-store example ledger rows:
- `2025目录内 = stable_inner_left + inner_to_outer_left + gone_inner_left`
- `2025目录外 = stable_outer_left + outer_to_inner_left + gone_outer_left`
- `2025总销售 = 2025目录内 + 2025目录外`
- `2026目录内 = stable_inner_right + outer_to_inner_right + new_inner_right`
- `2026目录外 = stable_outer_right + inner_to_outer_right + new_outer_right`
- `2026总销售 = 2026目录内 + 2026目录外`
- `稳定盘 = stable_inner + stable_outer`
- `正向增长 = outer_to_inner_delta + new_inner`
- `目录外相关损耗 = inner_to_outer_decline + gone_outer_decline`
- `净变化 = 正向增长 - 稳定盘下滑 - 目录内汰换 - 目录外相关损耗`

## 2. Do Not Invent New Semantics

If the user says one source is the truth, treat other data only as shape reference.

Completion criterion:
- The graph uses the user-approved narrative numbers.
- Any constructed detail sums back to those approved numbers.
- No extra conceptual nodes such as `正向贡献`, `最终总盘`, `相关项`, or `沉淀` are introduced unless requested.

## 3. Endpoint Labels, Not Band Labels

Put amount labels beside the relevant columns or flow endpoints.

Completion criterion:
- Labels do not sit on top of Sankey bands in a video-sized layout.
- Main state labels show the node total.
- Flow endpoint labels show endpoint values when transfer is not lossless.
- A delta is shown in surrounding narration or cards, not as the only graph label.

## 4. Text Collision Check

Run a text-collision check on the generated SVG.

Completion criterion:
- Parse every SVG `<text>` element with `x`, `y`, class, font size, and text.
- Group by left, right, and center regions.
- Sort by `y`.
- Flag adjacent labels when vertical gap is less than `max(13, min(font_sizes) + 2)`.
- Fix every flagged collision before reporting done.

## 5. Browser Check

Inspect the real page, not only the SVG source.

Completion criterion:
- The SVG is checked inside the target HTML container.
- The standalone SVG is checked when label quality is questioned.
- No label is clipped by the container.
- The Sankey width is not sacrificed merely to make labels fit; first shorten labels, reduce font size, or move text into side whitespace.

## 6. Lessons From The Ch5 Incident

Do not repeat these mistakes:
- Mixed `亿` and `万` units in the same graph.
- Duplicated the same number on a node and a flow without explaining why.
- Put labels over bands, making the flow unreadable.
- Counted virtual nodes into total sales.
- Treated a stable total, such as `6000万` stable盘, as if it belonged to one state only.
- Moved labels by eye without running a collision audit.
- Declared success from file inspection before browser inspection.
