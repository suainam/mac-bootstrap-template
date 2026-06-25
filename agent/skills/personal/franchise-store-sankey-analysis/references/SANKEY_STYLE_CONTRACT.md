# Sankey Style Contract

Use this contract before drawing or revising a Sankey graph.

## 1. Visual Anchor

Use the stable reference graph as the teacher, not a new design.

Completion criterion:
- Inspect [../assets/franchise_store_sankey_reference.svg](../assets/franchise_store_sankey_reference.svg) before editing when no project-local reference is provided.
- If the project contains a user-approved reference such as `report/franchise_store_sankey_graph_0617.svg`, prefer that newer local reference.
- Keep the same two-column, left-year-to-right-year reading model.
- Keep the same visual vocabulary: solid main nodes, dashed virtual nodes, broad colored bands, and small endpoint labels.
- Do not add decorative boxes, callout cards, dashed phantom bars, legends, or extra semantic nodes unless requested.

## 2. Layout Contract

Preserve a wide Sankey body.

Completion criterion:
- The two main columns stay far enough apart that flow width remains dominant.
- Do not narrow the Sankey body just to make text fit.
- Put labels in side whitespace first; shorten labels second; reduce font third.
- If labels still collide, move only the labels, not the data model.

## 3. Node Contract

Use domain-neutral node roles unless the user is working in the franchise-store catalogue example.

Completion criterion:
- Left side contains source-period main states plus optional source-side virtual states.
- Right side contains target-period main states plus optional target-side virtual states.
- Main nodes show category plus total amount.
- Virtual nodes show category plus amount, in smaller type.
- Virtual nodes must not be counted into total sales.

Franchise-store example:
- Left side: `2025目录内`, `2025目录外`, optional `2025新增目录内`, optional `2025新增目录外`.
- Right side: `2026目录内`, `2026目录外`, optional `2026目录内汰换`, optional `2026目录外汰换`.

## 4. Label Contract

Labels are endpoint annotations, not band captions.

Completion criterion:
- Flow labels sit beside the relevant source or target column.
- Labels do not sit on top of colored bands in the final video/page layout.
- Use short domain labels.
- Use endpoint amounts when the flow is not lossless.
- Do not use a lone delta such as `+450万` as the graph label; deltas belong in narration/cards/formula.

Franchise-store example labels:
- `稳定内`, `稳定外`, `外转内`, `内转外`, `新增目录内`, `目录内汰换`, `目录外汰换`.
- `外转内 2810万` on the 2025 side and `外转内 3260万` on the 2026 side.

## 5. Unit Contract

Keep units boring and consistent.

Completion criterion:
- Use one unit per graph. For this video-scale graph, prefer `万`.
- Do not mix `亿` and `万` in the same SVG.
- Do not repeat the same number in multiple visual roles unless each role is explicit.

## 6. Typography Contract

The graph is the main content, labels are secondary.

Completion criterion:
- Year labels are largest.
- Main node labels are smaller than year labels.
- Node amounts and flow endpoint labels are smaller than main node labels.
- Virtual labels are smaller than main labels.
- Use text stroke only for readability, not as a visual box.
- Do not use bordered label badges unless explicitly requested.

## 7. Fit Contract

The delivered artifact is the rendered page, not the SVG source alone.

Completion criterion:
- Check the SVG standalone when debugging label quality.
- Check the SVG inside the target HTML container before reporting done.
- Run the text-collision audit from `SANKEY_QA_CHECKLIST.md`.
- If browser scaling makes text unreadable, simplify labels before increasing visual weight.
