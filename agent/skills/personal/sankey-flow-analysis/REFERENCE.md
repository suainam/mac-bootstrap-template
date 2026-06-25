# Reference

## Scope

This skill is intentionally generic. It can be used for:

- catalogue structure changes
- user funnel or journey migration
- channel in/out movement
- product assortment replacement
- inventory inflow/outflow
- any analysis where entities move between states, groups, or time periods

## Reusable terminology

Prefer domain-native wording from the project, but these generic concepts often map well:

- source state
- target state
- stable base
- inflow
- outflow
- carry-over
- migration
-新增
-流失
-汰换

Use the user or business team's preferred wording whenever it already exists.

## Default chart logic

- use Sankey when the main question is about movement between states
- use width for the single most important metric
- if true zero-width makes a critical flow invisible, use a small visual placeholder
- add virtual nodes when a flow would otherwise appear to start or end in empty space
- avoid adding an intermediate action layer unless it materially improves comprehension

## Preferred reading order

1. stable or unchanged base
2. positive / promoted / target flows
3. loss / downgrade / exit flows
4. net result or business implication

## Presentation guidance

When the user wants a presentation-ready summary:

1. describe the baseline trend
2. describe the structural changes that improved the result
3. explain the offsetting losses or tradeoffs
4. end with the net takeaway

Example pattern:

`在基础盘变化的背景下，结构调整带来了 X 的正向增量，同时受到 Y 和 Z 的影响，最终实现 N 的净变化。`

## Visual design example

Use the catalogue in/out case as a reference for how visual choices should serve the analysis, not just decoration.

### Example setup

- left side: `2025目录内`, `2025目录外`
- right side: `2026目录内`, `2026目录外`
- virtual nodes: `新增`, `汰换`
- width metric: `近90天销售额`
- goal: prove that the stable base declined, while structure changes created positive inner-catalogue growth

### How to handle bars

- main bars should represent the real source and target states the audience already understands
- keep the main bars visually solid so the viewer can immediately identify the core comparison frame
- if a flow starts from “not present yet” or ends in “removed / replaced”, add a separate virtual bar instead of letting the band appear from nowhere

In the catalogue example:

- `2025新增目录内` and `2025新增目录外` were placed as virtual start bars so 2026 new flows had a visible origin
- `2026目录内汰换` and `2026目录外汰换` were placed as virtual end bars so 2025 removed flows had a visible destination

This prevents the common Sankey problem where the audience thinks a band “appears from the middle” or “disappears halfway”.

### How to handle dashed boxes

- use dashed boxes for virtual states rather than normal solid bars
- keep them lighter than the main states so they read as explanatory anchors, not primary business states
- dashed treatment is especially useful for `新增`, `流失`, `汰换`, `未出现`

In the catalogue example, dashed bars signaled that these nodes were not normal catalogue states, but were still necessary to explain the flow completely.

### How to handle text

- keep text outside the flow bands when the chart is dense
- place labels next to bars so the reader can connect value and state quickly
- if both sides of a flow matter, show one value near the source and one near the target
- reduce repeated wording when it causes overlap; let the surrounding year or state headers do part of the work

In the catalogue example:

- amounts were moved out of the bands and placed beside the bars
- labels inside the bands were removed to reduce clutter
- `新增` and `汰换` labels were only shown once near their own virtual bars
- report cards and narrative blocks carried the heavier explanation, so the chart stayed readable

### How to handle color

- assign color by analytical role, not randomly by category
- use low-saturation or neutral colors for stable base flows
- use stronger positive colors for promoted / growth-driving flows
- use warning or loss colors for downgrade / exit / replacement flows
- keep the same semantic color family across chart and report shell

In the catalogue example:

- stable inner and outer flows were muted teal / gray because they formed the baseline
- `目录外 -> 目录内` and `新增目录内` used greener tones because they supported the growth story
- `目录内 -> 目录外` used a warm red tone because it represented downgrade
- `汰换` flows used softer brown / orange tones to show loss or replacement without overpowering the main conclusion

### How visual choices support the story

The chart should help the audience read the conclusion in this order:

1. the stable base is shrinking
2. promoted or new target flows are the main positive drivers
3. replacement and carry-over flows explain offsets
4. the final net effect comes from combining those pieces

In the catalogue example, the visual system was designed to support exactly that reading order:

- solid main bars established the `2025 -> 2026` comparison
- dashed virtual bars made `新增` and `汰换` legible
- outer-band labels prevented clutter
- semantic colors made the positive and negative mechanisms easy to distinguish
- the report shell below the chart converted those flows into the final net-growth statement

## Common pitfalls

- mixing chart wording and report wording
- forcing domain-specific labels into a generic flow problem
- putting too much text inside flow bands
- changing units across summary layers without saying so
- making the chart show transitions while the summary explains a different metric
