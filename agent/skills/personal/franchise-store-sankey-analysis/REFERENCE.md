# Reference

Use this file for the minimum always-use rules. Push everything else to the linked references.

## Default chart logic

- Time direction: usually `2025 -> 2026`
- Sankey depth: two layers only
- Width metric: default to `近90天销售额`
- Unit: `亿`
- Virtual nodes: `新增` and `汰换`

## Default wording

- `目录内`
- `目录外`
- `新增`
- `汰换`
- `存量盘`

Use `%`, not `pct`.
Use `汰换`, not `损耗`.

## Stable report structure

1. KPI cards
2. Report conclusion
3. Sankey summary cards
4. Sankey graph
5. Sankey explanation (`总 -> 分 -> 总`)
6. Footnote / 口径提醒

## Standard reading order

1. `存量盘`变化
2. `目录外 -> 目录内`
3. `新增 -> 目录内`
4. `目录内汰换`
5. `目录外承接/汰换`
6. Net conclusion

## Conclusion formulas

Positive case:

`26年目录内带来正向贡献 X，减去存量减少 Y，减去目录内汰换 Z，减去目录外汰换 W，最终剩余 N。`

Negative case:

`26年目录内带来正向贡献 X，但减去存量盘负增长 Y、目录内汰换 Z、目录外汰换 W 后，最终总盘仍净减 N。`

## Open only when needed

- Input shape unclear: [references/DATA_INPUT_CONTRACT.md](references/DATA_INPUT_CONTRACT.md)
- Need business wording: [references/WORDING_TEMPLATES.md](references/WORDING_TEMPLATES.md)
- Need reusable styles: [templates/report_style.css](templates/report_style.css), [templates/graph_style.css](templates/graph_style.css)
