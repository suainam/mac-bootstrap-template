---
name: marimo-etl-test
description: Writes and runs regression tests for the `www/marimo/merchandise` ETL, lib, and notebook data flows using the repo's current pytest, uv, and Docker setup. Use when changing fetch_data, clearance/assortment helpers, raw/agg/serve outputs, trigger flows, or when the user asks for pytest, regression, or container-based validation.
---

# Marimo ETL Test

## Quick start

先把 `www/` 根目录当成 Python 项目边界。当前仓库的 `pyproject.toml` 和 `uv.lock`
在 `www/` 根，不在 `marimo/` 子目录里。

默认先走 `uv`，不要先假设只能靠容器：

```bash
cd <www-root>
UV_CACHE_DIR=.uv-cache uv run --extra test pytest \
  marimo/merchandise/tests/<target>.py \
  --no-cov -q
```

如果用户明确要求运行时/容器验证，或宿主机回归无法覆盖镜像、挂载、数据目录问题，
再切到容器：

```bash
docker ps --format '{{.Names}}\t{{.Status}}'
docker exec merchandise-dashboard-dev python -m pytest tests/<target>.py --no-cov -q
```

如果容器名不是 `merchandise-dashboard-dev`，先用 `docker ps` 取真实名字。

需要具体断言写法或排查流程时，读 `EXAMPLES.md`。

## Current reality

- 当前项目是 `marimo/merchandise`，不是旧的 `marimo_non_catalog_clearance`。
- 当前宿主机测试入口是 `www/pyproject.toml` + `uv.lock`，`tool.pytest.ini_options`
  已指向 `marimo/merchandise/tests`。
- `tests/`、`pytest.ini`、`.coveragerc` 当前通常已挂载进开发容器；先验证，再决定是否 `docker cp`。
- `conftest.py` 已处理：
  - `sys.path`
  - 假 ODPS 凭证
  - `DATA_DIR`
- `marimo/README.md`、`merchandise/docs/ops-knowledge-base.md`、
  `merchandise/docs/deployment-update.md` 已记录当前 deploy / handoff 现实；
  测试判断要和这些文档保持一致。

## Workflow

1. 先决定要跑宿主机还是容器。
   - 只做语法检查：宿主机可先跑 `python -m py_compile`
   - 代码级 pytest：优先 `uv run --extra test pytest ...`
   - 容器级验证：留给镜像、挂载、运行时数据、真实 entrypoint 问题
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
5. 如果测试涉及 deploy / release / workflow 脚本：
   - 优先跑 `test_gitea_deploy.py`
   - 断言应以当前主仓库、semver tag 发布、revision label 校验为准
   - 不要保留旧的 subtree split 或旧 split-repo 假设
6. 如果新增了 ETL task：
   - 测 `VALID_TASKS` 包含新 task。
   - 测 `main(["--task", "<task>"])` 只跑该 task。
   - 测 `_run_<task>` 把所有源表传给 serve builder。
   - 测 `task == "all"` 时子任务顺序包含新 task。
   - 测部署/手动 ETL workflow 的 task allowlist 包含新 task。
7. 对跨表共享筛选字段做回归，尤其是批次、跟踪类型、地理层级和观察口径；如果某个批次任一源表标记为未来窗口，页面层要一致排除该批次。

## Test rules

- patch `etl.fetch_data.DATA_DIR` 时用真实 `tmp_path`，不用 MagicMock。
- 如果模块改成了通过 helper 函数动态取 `DATA_DIR/raw|agg|serve`，测试也要跟着改，不要还断言旧根目录文件。
- 改 `process_info` / `process_agg` 语义时，测试必须同步到最新表结构，不要保留旧的“本地清单 + dim_store 再拼表”假设。
- 比例字段测试必须验证“先求和再算比例”，不能默认平均比例列。
- 文件命名测试要覆盖专题前缀，例如 `off_catalog_clearing_*`。
- 百分比展示测试要覆盖小数值，例如 `0.00066` 应显示为 `0.07%`，避免业务看到空值或裸小数。

## Commands

只跑 deploy / release 回归：

```bash
cd <www-root>
UV_CACHE_DIR=.uv-cache uv run --extra test pytest \
  marimo/merchandise/tests/test_gitea_deploy.py \
  --no-cov -q
```

只跑相关测试：

```bash
cd <www-root>
UV_CACHE_DIR=.uv-cache uv run --extra test pytest \
  marimo/merchandise/tests/test_clearance_etl.py \
  marimo/merchandise/tests/test_data_access.py \
  marimo/merchandise/tests/test_clearance_data.py \
  marimo/merchandise/tests/test_fetch_data.py \
  --no-cov -q
```

加上导出回归：

```bash
cd <www-root>
UV_CACHE_DIR=.uv-cache uv run --extra test pytest \
  marimo/merchandise/tests/test_export_html.py \
  --no-cov -q
```

全量回归：

```bash
cd <www-root>
UV_CACHE_DIR=.uv-cache uv run --extra test pytest \
  marimo/merchandise/tests/ \
  --no-cov -q
```

## Known traps

- 在 `marimo/` 子目录里直接跑 `uv` / `pytest`：容易错过真正的 `www` 项目边界。
- `uv` 默认缓存目录不可写：改用 `UV_CACHE_DIR=.uv-cache`。
- 宿主机缺依赖时不要直接 `pip install`；优先 `uv sync` / `uv run --extra test ...`。
- 容器里前端没数据，但 pytest 全绿：通常是新 `serve` 文件没生成，不是测试漏了。
- `docker compose exec` 报新 task invalid choice，但按端口访问页面是新版：可能进错容器。用 `docker ps --format '{{.ID}} {{.Names}} {{.Ports}}'` 按端口或 preview slug 找真实容器，再 `docker exec`。
- ETL 查 ODPS 返回 0 行：先确认是不是误走了 `source="parquet"`。
- 改了 notebook 读新文件名，但没重跑 ETL：前端一定空白。
- 改了表结构字段名，比如新增 `store_name`：先等表变更完成，再重跑 ETL，不要在代码里瞎兜底。
- `test_gitea_deploy.py` 失败时先看是不是文档/脚本断言还停留在旧的发布路径，而不是先怀疑 workflow 本身坏了。
