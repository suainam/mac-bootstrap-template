---
name: sql-analysis
description: "Use for SQL analytics work: profile tables, write readable queries, verify joins and aggregations, and produce auditable analytical outputs."
---

# SQL Analysis

Start with table profiling:

1. Confirm the grain of each table.
2. Inspect key columns for nulls, duplicates, and cardinality.
3. Check date/time ranges and timezone assumptions.
4. Verify row counts before and after joins.

Query style:

- Use CTEs for logical stages: source, cleaned, joined, aggregated, final.
- Name metrics precisely and keep units visible.
- Avoid `select *` in final analytical outputs.
- Add comments only for non-obvious business logic.
- Prefer deterministic ordering in exports and examples.

Join checks:

- Before a join, test key uniqueness on both sides.
- After a join, compare row counts and key coverage.
- For many-to-many joins, explicitly state why the expansion is expected.

For local files, prefer DuckDB when possible so CSV/parquet analysis stays close
to production SQL habits.
