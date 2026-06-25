---
name: marimo-dashboard-create
description: Creates or updates Marimo dashboard pages in /home/dsl/projects/www/marimo/merchandise using the repo's current notebook, ETL, theme, and Docker conventions. Use when adding a new merchandise dashboard page, changing notebook data flow, wiring ETL outputs, or aligning a page with the existing raw/agg/serve structure.
---

# Marimo Dashboard Create

## Quick start

先读当前仓库，不要沿用旧的 `marimo_non_catalog_clearance` 路径假设。

- `marimo/merchandise/Dockerfile`
- `marimo/merchandise/docker-compose.yml`
- `marimo/merchandise/scripts/entrypoint.sh`
- `marimo/merchandise/lib/theme.py`
- `marimo/merchandise/etl/fetch_data.py`
- 当前相关 notebook 和 data helper

默认只改代码。不构建、不重启、不跑 Docker，除非用户明确要求。

## Workflow

1. 先确认当前页面入口、ETL 输出、主题 helper、容器运行方式。
2. 只问代码里无法推出的事实，一次只问一个关键问题。
3. 新页面优先复用 `lib/theme.py`、现有 ETL 框架、现有 notebook 模式。
4. 数据设计先定层次，再写页面：
   - `raw/`：ODPS 源表本地镜像
   - `agg/`：供页面/调试复用的中间缓存
   - `serve/`：页面最终直读的小文件
5. 命名要带专题前缀，避免和别的页面混淆，例如 `off_catalog_clearing_*`。
6. 不新增 Docker service，不改端口，不拆出新的部署单元，除非用户明确要求。

## Questions

只问这些推不出来的事实，且一次问一个：

1. 页面名、路由名、卡片标题。
2. 数据源是 ODPS 新表、现有 parquet，还是沿用已有 helper。
3. 该页面要直接读 `serve`，还是需要 `raw -> agg -> serve` 全链路。
4. 需要哪些筛选器、KPI、图、表、导出。
5. 空数据和旧数据怎么展示。

## Rules

- notebook 放在 `marimo/merchandise/notebooks/` 或 `notebooks/sub_projects/`，先匹配现有结构。
- 当前首页入口先确认真实文件，不要假设是旧的 `clearance_dashboard.py`。
- 复用 `COLORS`、`FONT`、`GLOBAL_CSS`、Plotly layout helper；不要新造视觉体系。
- dashboard 专属转换逻辑，只有在 notebook / ETL / tests 复用时才下沉到 `lib/`。
- ETL 输出先写进共享 `etl/fetch_data.py` 或其调用 helper，不要绕开统一任务入口。
- 聚合比例必须按分子分母求和后再算，不能 `mean()` 比例列。
- 明细表隐藏技术编码列，但可以保留这些列用于排序和过滤。
- 如果页面要接新 parquet，先检查导出模块、测试、文档是否要一起改。

## Validation

代码校验优先：

```bash
python -m py_compile marimo/merchandise/notebooks/<page>.py marimo/merchandise/lib/<module>.py marimo/merchandise/etl/fetch_data.py
```

如果用户要求回归，优先走 `marimo-etl-test` skill，在容器里验证，不默认自己跑 Docker build。
