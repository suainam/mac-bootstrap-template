---
name: python-data-analysis
description: "Use for Python data analysis tasks: load data, inspect quality, transform with pandas/polars/duckdb, create reproducible summaries, and validate results before presenting conclusions."
disable-model-invocation: true
---

# Python Data Analysis

Use a reproducible analysis loop:

1. Identify the data source, schema, grain, time range, and expected output.
2. Load a small sample first, then inspect types, nulls, duplicates, outliers,
   and join keys.
3. Prefer explicit transformations over clever chains when business logic is
   important.
4. Validate row counts and aggregates after every filter, join, or reshape.
5. Separate exploration from reusable code. Promote stable logic into functions
   or scripts only after the notebook/marimo exploration is understood.
6. Report assumptions, data-quality caveats, and checks performed with the final
   result.

Default stack inside containers:

- `uv` for dependency locking and running tools.
- `pandas` for common tabular work.
- `polars` or `duckdb` for larger local datasets.
- `pyarrow` for parquet/IPC interchange.
- `plotly`, `altair`, or `matplotlib` depending on the project convention.

Never silently coerce dirty data. When parsing fails, preserve the raw column,
create a cleaned column, and report the parse failure rate.

---

## References

- `references/DATA_QUALITY.md` — 数据质量检查清单和模板
- `references/ANALYSIS_PATTERNS.md` — 对比、拆分、下钻等分析方法
