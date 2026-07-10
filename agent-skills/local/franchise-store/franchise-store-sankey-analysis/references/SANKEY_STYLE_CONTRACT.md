# 桑基图样式合同

在绘制或修改 Sankey 图前使用本合同。

## 1. 视觉锚点

以稳定参考图为老师，不要临时发明新设计。

完成标准：
- Inspect [../assets/franchise_store_sankey_reference.svg](../assets/franchise_store_sankey_reference.svg) before editing when no project-local reference is provided.
- If the project contains a user-approved reference such as `report/franchise_store_sankey_graph_0617.svg`, prefer that newer local reference.
- Keep the same two-column, left-year-to-right-year reading model.
- Keep the same visual vocabulary: solid main nodes, dashed virtual nodes, broad colored bands, and small endpoint labels.
- Do not add decorative boxes, callout cards, dashed phantom bars, legends, or extra semantic nodes unless requested.

## 2. 布局合同

保持宽阔的 Sankey 主体。

完成标准：
- The two main columns stay far enough apart that flow width remains dominant.
- Do not narrow the Sankey body just to make text fit.
- Put labels in side whitespace first; reduce font second; shorten labels last.
- If labels still collide, move only the labels, not the data model.

## 3. 节点合同

Use domain-neutral node roles unless the user is working in the franchise-store catalogue example.

完成标准：
- Left side contains source-period main states plus optional source-side virtual states.
- Right side contains target-period main states plus optional target-side virtual states.
- Main nodes show category plus total amount.
- Virtual nodes show category plus amount, in smaller type.
- Virtual nodes must not be counted into total sales.

Franchise-store example:
- Left side: `2025目录内`, `2025目录外`, optional `2025新增目录内`, optional `2025新增目录外`.
- Right side: `2026目录内`, `2026目录外`, optional `2026目录内汰换`, optional `2026目录外汰换`.

## 4. 标签合同

标签是端点标注，不是色带上的标题。

完成标准：
- Flow labels sit beside the relevant source or target column.
- Labels do not sit on top of colored bands in the final video/page layout.
- Preserve the approved business vocabulary from the latest user-approved reference graph.
- Use endpoint amounts when the flow is not lossless.
- Do not use a lone delta such as `+450万` as the graph label; deltas belong in narration/cards/formula.

Franchise-store example labels:
- `稳定目录内`, `稳定目录外`, `目录外转目录内`, `目录内转目录外`, `新增目录内`, `目录内汰换`, `目录外汰换`.
- `目录外转目录内 2.87亿` on the 2025 side and `目录外转目录内 3.12亿` on the 2026 side.
- If the latest approved local reference uses the full business labels, do not silently shorten them to `稳定内`, `稳定外`, `外转内`, or `内转外`.

## 5. 单位合同

单位保持朴素且一致。

完成标准：
- Use one unit per graph.
- Do not mix `亿` and `万` in the same SVG.
- Match the unit to the approved local reference or the user's explicit request.
- Do not repeat the same number in multiple visual roles unless each role is explicit.

## 6. 排版合同

The graph is the main content, labels are secondary.

完成标准：
- Year labels are largest.
- Main node labels are smaller than year labels.
- Node amounts and flow endpoint labels are smaller than main node labels.
- Virtual labels are smaller than main labels.
- Use text stroke only for readability, not as a visual box.
- Do not use bordered label badges unless explicitly requested.

## 7. 适配合同

The delivered artifact is the rendered page, not the SVG source alone.

完成标准：
- Check the SVG standalone when debugging label quality.
- Check the SVG inside the target HTML container before reporting done.
- Run the text-collision audit from `SANKEY_QA_CHECKLIST.md`.
- If browser scaling makes text unreadable, preserve approved label vocabulary first, then use whitespace/layout/font adjustments, and shorten labels only when the user explicitly asks.
