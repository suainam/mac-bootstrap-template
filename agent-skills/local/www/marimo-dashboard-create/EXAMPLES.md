# Examples

## User trigger

> 在 marimo 里面加一个销售毛利看板，风格和库存清理看板保持一致。

Load this skill, then inspect the existing Marimo app before asking questions.

## Minimal dashboard skeleton

```python
import marimo

__generated_with = "0.23.5"
app = marimo.App(width="full", app_title="新看板标题")


@app.cell
def _imports():
    import logging
    import os
    from datetime import datetime
    from pathlib import Path

    import marimo as mo
    import pandas as pd
    import plotly.graph_objects as go

    from lib.theme import (
        COLORS,
        FONT,
        GLOBAL_CSS,
        kpi_card,
        kpi_label,
        kpi_value,
        section_container,
        section_title,
        time_trend_layout,
    )

    return (
        COLORS,
        FONT,
        GLOBAL_CSS,
        Path,
        datetime,
        go,
        logging,
        mo,
        os,
        pd,
        kpi_card,
        kpi_label,
        kpi_value,
        section_container,
        section_title,
        time_trend_layout,
    )


@app.cell
def _config(os, Path):
    DATA_FILE = Path(os.getenv("NEW_DASHBOARD_DATA_FILE", "/workspace/data/new_dashboard_latest.parquet"))
    return (DATA_FILE,)


@app.cell
def _data_loader(DATA_FILE, logging, mo, pd):
    refresh = mo.ui.refresh(default_interval="1h", label="自动刷新（1小时）")

    def load_data() -> pd.DataFrame:
        _ = refresh
        if not DATA_FILE.exists():
            return pd.DataFrame()
        try:
            return pd.read_parquet(DATA_FILE)
        except Exception as exc:
            logging.warning(f"加载数据失败: {exc}")
            return pd.DataFrame()

    return load_data, refresh


@app.cell
def _header(DATA_FILE, GLOBAL_CSS, datetime, load_data, mo, refresh):
    df = load_data()
    if df.empty:
        info_text = "数据加载中，请稍候..."
    else:
        update_time = datetime.fromtimestamp(DATA_FILE.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        info_text = f"数据更新：{update_time} | 记录：{len(df):,} 条"

    header_output = mo.Html(f"""
    {GLOBAL_CSS}
    <div class="header-card">
        <h1 class="header-title">新看板标题</h1>
        <p class="header-info">{info_text}
        <div class="refresh-container">{refresh.text}</div>
        </p>
    </div>
    """)
    mo.output.replace(header_output)
    return (header_output,)


if __name__ == "__main__":
    app.run()
```

## Shared ETL pattern

Add a small function for the new dataset and call it from the existing shared ETL main flow. Write outputs atomically and keep `*_latest.parquet` as the notebook input.

Do not add a second cron daemon or a second compose service for the new page.

## New ETL task checklist

When adding a dashboard-specific task such as `hot_sales_expansion`, update the
whole chain in one change:

```text
merchandise/lib/<topic>_etl.py
merchandise/lib/<topic>_data.py
merchandise/etl/fetch_data.py
.gitea/workflows/etl-refresh.yaml
scripts/validate-staging.sh
scripts/verify-deployment.sh
merchandise/tests/test_fetch_data.py
merchandise/tests/test_<topic>_etl.py
merchandise/tests/test_<topic>_data.py
merchandise/config/dashboard_pages.yaml
```

Register each serve output with its grain, unique key, required columns, snapshot behavior,
empty-data behavior, and real producer/consumer pytest node IDs.

In `fetch_data.py`, cover both the one-off task and `all`:

```python
VALID_TASKS = {"all", "clearance", "merchandise", "assortment", "<topic>"}

if task == "all":
    subtask_order = ["clearance", "merchandise", "assortment", "<topic>"]
```

## Filter guidance note

Use a small note below global filters when the page has mixed global and local
controls:

```python
mo.Html(
    """
    <div class="filter-note">
      说明：跟踪类型、批次、汇总层级会影响整个看板的数据范围；
      汇总层级选择省区或营运区时，请同步选择具体区域。
    </div>
    """
)
```

Keep item/category/keyword filters near the item detail table when they do not
control the full dashboard.

## Preview container check

If the preview URL works but `docker compose exec` enters an old container, find
the real container by port or branch slug:

```bash
CID=$(docker ps --format '{{.ID}} {{.Names}} {{.Ports}}' \
  | awk '/59452|feature-hot-sales-expansion-dashboard/ {print $1; exit}')

docker exec -it "$CID" python -m etl.fetch_data --task <topic>
```

Code deployment and ETL refresh are separate. A preview can serve the latest
notebook while still needing a manual refresh of `/workspace/data/serve`.
