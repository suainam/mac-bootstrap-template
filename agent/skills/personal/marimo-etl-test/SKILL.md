---
name: marimo-etl-test
description: Writes and runs regression tests for /home/dsl/projects/www/marimo/merchandise ETL, lib, and notebook data flows using the repo's current pytest and Docker setup. Use when changing fetch_data, clearance/assortment helpers, raw/agg/serve outputs, trigger flows, or when the user asks for pytest, regression, or container-based validation.
---

# Marimo ETL Test

## Quick start

优先在容器里跑，不要先假设宿主机 Python 环境完整。这个仓库宿主机可能缺 `pandas`，导致 `pytest` 连 `conftest.py` 都加载不了。

```bash
docker ps --format '{{.Names}}\t{{.Status}}'
docker exec merchandise-dashboard-dev python -m pytest tests/<target>.py --no-cov -q
```

如果容器名不是 `merchandise-dashboard-dev`，先用 `docker ps` 取真实名字。

## Current reality

- 当前项目是 `marimo/merchandise`，不是旧的 `marimo_non_catalog_clearance`。
- `tests/`、`pytest.ini`、`.coveragerc` 当前通常已挂载进开发容器；先验证，再决定是否 `docker cp`。
- `conftest.py` 已处理：
  - `sys.path`
  - 假 ODPS 凭证
  - `DATA_DIR`

## Workflow

1. 先决定要跑宿主机还是容器。
   - 只做语法检查：宿主机可先跑 `python -m py_compile`
   - 真正 pytest：优先容器
2. 先跑最小相关测试，再决定是否扩大到全量。
3. 如果改了 `fetch_data.py`、`clearance_etl.py`、`clearance_data.py`、导出路径或 `raw/agg/serve` 命名：
   - 至少跑 `test_fetch_data.py`
   - 至少跑 `test_clearance_etl.py`
   - 至少跑 `test_clearance_data.py`
   - 如果 HTML/进度表格受影响，再跑 `test_export_html.py`
4. 如果前端空数据，不要只看 pytest。
   - 直接进容器检查 `/workspace/data/raw|agg|serve`
   - 再看 notebook 实际读的路径
   - 再跑 `python -m etl.fetch_data --task <task>`

## Test rules

- patch `etl.fetch_data.DATA_DIR` 时用真实 `tmp_path`，不用 MagicMock。
- 如果模块改成了通过 helper 函数动态取 `DATA_DIR/raw|agg|serve`，测试也要跟着改，不要还断言旧根目录文件。
- 改 `process_info` / `process_agg` 语义时，测试必须同步到最新表结构，不要保留旧的“本地清单 + dim_store 再拼表”假设。
- 比例字段测试必须验证“先求和再算比例”，不能默认平均比例列。
- 文件命名测试要覆盖专题前缀，例如 `off_catalog_clearing_*`。

## Commands

只跑相关测试：

```bash
docker exec merchandise-dashboard-dev python -m pytest \
  tests/test_clearance_etl.py \
  tests/test_data_access.py \
  tests/test_clearance_data.py \
  tests/test_fetch_data.py \
  --no-cov -q
```

加上导出回归：

```bash
docker exec merchandise-dashboard-dev python -m pytest \
  tests/test_export_html.py \
  --no-cov -q
```

全量回归：

```bash
docker exec merchandise-dashboard-dev python -m pytest tests/ --no-cov -q
```

## Known traps

- 宿主机 `pytest` 报 `ModuleNotFoundError: pandas`：改去容器跑，不要继续卡在宿主机。
- 容器里前端没数据，但 pytest 全绿：通常是新 `serve` 文件没生成，不是测试漏了。
- ETL 查 ODPS 返回 0 行：先确认是不是误走了 `source="parquet"`。
- 改了 notebook 读新文件名，但没重跑 ETL：前端一定空白。
- 改了表结构字段名，比如新增 `store_name`：先等表变更完成，再重跑 ETL，不要在代码里瞎兜底。
