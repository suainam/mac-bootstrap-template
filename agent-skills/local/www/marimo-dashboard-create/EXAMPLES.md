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
