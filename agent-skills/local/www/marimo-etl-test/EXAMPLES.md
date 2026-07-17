# Examples

## User trigger

> 我给这个看板新增了一个 ETL task，帮我补测试。

Use this skill to add focused tests for task registration, one-off execution,
`all` execution, serve output, and workflow allowlists.

Run those tests in the Docker-authoritative Merchandise environment. For a code-only
worktree change, mount the worktree read-only instead of installing host dependencies:

```bash
mkdir -p <marimo-worktree>/merchandise/tests/_test_data_tmp
docker run --rm \
  --tmpfs /repo/merchandise/tests/_test_data_tmp:rw \
  -v <marimo-worktree>:/repo:ro \
  -w /repo/merchandise \
  --entrypoint python merchandise:dev \
  -m pytest tests/test_fetch_data.py --no-cov -q -p no:cacheprovider
```

## Task registration

```python
def test_valid_tasks_include_new_topic():
    from etl.fetch_data import VALID_TASKS

    assert "hot_sales_expansion" in VALID_TASKS
```

## One-off task execution

```python
def test_main_task_hot_sales_expansion_only():
    with (
        patch("etl.fetch_data._run_hot_sales_expansion") as mock_hot_sales,
        patch("etl.fetch_data._run_clearance") as mock_clearance,
    ):
        result = main(["--task", "hot_sales_expansion"])

    assert result == 0
    mock_hot_sales.assert_called_once()
    mock_clearance.assert_not_called()
```

## Serve builder receives every source

```python
def test_run_hot_sales_expansion_passes_all_sources():
    summary = pd.DataFrame({"catalog_version": ["202607"]})
    item = pd.DataFrame({"catalog_version": ["202607"]})
    productivity = pd.DataFrame({"catalog_version": ["202607"]})
    business_summary = pd.DataFrame({"catalog_version": ["202607"]})

    with (
        patch(
            "etl.fetch_data.fetch_hot_sales_expansion_data",
            return_value=(summary, item, productivity, business_summary),
        ),
        patch("etl.fetch_data.build_hot_sales_expansion_serve") as build,
    ):
        _run_hot_sales_expansion()

    build.assert_called_once()
    assert build.call_args.args[:4] == (
        summary,
        item,
        productivity,
        business_summary,
    )
```

## Shared batch filtering

When one source marks a batch as not ready, assert every source and dropdown
exclude it:

```python
future = future_catalog_versions(summary_df, item_df, productivity_df)

assert "202608" in future
assert "202608" not in set(
    exclude_catalog_versions(summary_df, future)["catalog_version"]
)
assert "202608" not in set(
    exclude_catalog_versions(item_df, future)["catalog_version"]
)
```

## Preview container mismatch

If the page URL is new but ETL says the task is invalid, you may be inside the
wrong container:

```bash
docker compose exec -T merchandise-dashboard \
  python -m etl.fetch_data --task hot_sales_expansion
# invalid choice: hot_sales_expansion

CID=$(docker ps --format '{{.ID}} {{.Names}} {{.Ports}}' \
  | awk '/59452|feature-hot-sales-expansion-dashboard/ {print $1; exit}')

docker exec -it "$CID" \
  python -m etl.fetch_data --task hot_sales_expansion
```

Before accepting this result, inspect the container mounts and revision label. A matching
container name is insufficient evidence that the command used the intended branch.
