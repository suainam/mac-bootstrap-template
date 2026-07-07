# 桑基图 QA 清单

交付 Sankey 图前使用这份清单，尤其在数值是用户可见财务数字或经过结构化整理时。

## 1. 先做台账

画图前先建台账。

完成标准：
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
- `目录外相关汰换 = inner_to_outer_decline + gone_outer_decline`
- `净变化 = 正向增长 - 稳定盘下滑 - 目录内汰换 - 目录外相关汰换`

## 2. 不要发明新语义

If the user says one source is the truth, treat other data only as shape reference.

完成标准：
- The graph uses the user-approved narrative numbers.
- Any constructed detail sums back to those approved numbers.
- No extra conceptual nodes such as `正向贡献`, `最终总盘`, `相关项`, or `沉淀` are introduced unless requested.

## 3. 标签放端点，不放色带

Put amount labels beside the relevant columns or flow endpoints.

完成标准：
- Labels do not sit on top of Sankey bands in a video-sized layout.
- Main state labels show the node total.
- Flow endpoint labels show endpoint values when transfer is not lossless.
- A delta is shown in surrounding narration or cards, not as the only graph label.

## 4. 标签词表一致性检查

Compare the generated graph labels with the latest user-approved local reference graph when one exists.

完成标准：
- The generated SVG preserves the approved business wording for the same semantic flows.
- Do not silently shorten `稳定目录内`, `稳定目录外`, `目录外转目录内`, or `目录内转目录外` when the approved reference uses the full forms.
- If you intentionally shorten labels, the user must have asked for it explicitly.

## 5. 文本碰撞检查

Run a text-collision check on the generated SVG.

完成标准：
- Parse every SVG `<text>` element with `x`, `y`, class, font size, and text.
- Group by left, right, and center regions.
- Sort by `y`.
- Flag adjacent labels when vertical gap is less than `max(13, min(font_sizes) + 2)`.
- Fix every flagged collision before reporting done.

## 6. 浏览器检查

Inspect the real page, not only the SVG source.

完成标准：
- The SVG is checked inside the target HTML container.
- The standalone SVG is checked when label quality is questioned.
- No label is clipped by the container.
- The Sankey width is not sacrificed merely to make labels fit; first use whitespace, layout, or font adjustments before shortening approved label vocabulary.

## 7. Ch5 事故教训

Do not repeat these mistakes:
- Mixed `亿` and `万` units in the same graph.
- Duplicated the same number on a node and a flow without explaining why.
- Put labels over bands, making the flow unreadable.
- Counted virtual nodes into total sales.
- Treated a stable total, such as `6000万` stable盘, as if it belonged to one state only.
- Moved labels by eye without running a collision audit.
- Declared success from file inspection before browser inspection.
- Shortened approved franchise-store flow labels without noticing the wording drift.
