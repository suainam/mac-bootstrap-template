---
name: odps-query-uv
description: "Ad-hoc MaxCompute (ODPS) queries, DMP metadata search, and demand exploration using uv and ~/.env without Docker"
---

# odps-query-uv

Run ad-hoc MaxCompute (ODPS) queries, DMP metadata search, and demand exploration using `uv` and `~/.env` without Docker overhead.

## Steps

### 1. Discover Metadata via DMP MCP
Search tables and inspect schemas via `DMP_MCP_ENDPOINT` (or `~/.env`) using the bundled CLI (bypasses system proxy and sets required SSE headers):

```bash
# Search tables by keyword
python3 .agents/skills/odps-query-uv/scripts/dmp_mcp_client.py search "医保目录" --top 5

# Inspect table schema and filter columns
python3 .agents/skills/odps-query-uv/scripts/dmp_mcp_client.py detail dsl_dim.dim_store --filter 统筹
```

### 2. Map Business Logic (Assortment Demands)
When analyzing assortment demands (`demand-XXXXX-*.md`), locate production SQL and rules in `topics/assortment/202608组货模型复盘/`:
* `06_模型配置消费链路与提取说明.md` — `scope_type` switch mapping (`2`=新品, `3`=自有品牌, `7`=同质化).
* `门店常规经营目录V7.0完整文档.md` — business rules for hot sale, long sale, and private brands.
* `20260717更新sql及血缘关系/` — DataWorks node SQL (`10002166175` yyq PSD, `10002393468` private brand, `10002339877` homogenization).

### 3. Execute Ad-hoc ODPS Queries via `uv`
Load credentials from `~/.env` and run `pyodps` via `uv run --with pyodps --no-project`:

```python
import os, subprocess
from pathlib import Path

env = {**os.environ}
for line in (Path.home() / ".env").read_text().splitlines():
    if line.strip() and not line.strip().startswith("#") and "=" in line:
        k, v = line.strip().split("=", 1)
        env[k.strip()] = v.strip().strip("'\"")

py_code = """
import os
from odps import ODPS

c = ODPS(
    os.environ['ODPS_ACCESS_ID'],
    os.environ['ODPS_SECRET_KEY'],
    project=os.environ.get('ODPS_PROJECT', 'dsl_ai'),
    endpoint=os.environ.get('ODPS_ENDPOINT', 'https://service.cn-shenzhen.maxcompute.aliyun.com/api')
)

sql = "SELECT max(stat_date) as max_dt FROM dsl_dim.dim_store"
with c.execute_sql(sql).open_reader() as r:
    for row in r:
        print(row['max_dt'])
"""

subprocess.run(["uv", "run", "--with", "pyodps", "--no-project", "python", "-c", py_code], env=env, check=True)
```

### 4. Deliver RFC Design Doc
Write design docs to `topics/<topic_id>/03_analysis/demand-XXXXX-rfc-technical-design.md` covering: Metadata (`demand-XXXXX`, author `数据智能-<owner>`), Executive Summary, Problem Definition, Goals/Non-Goals, Architecture Mermaid, Data Dictionary, SQL Implementation, Empirical Validation, and Operational Runbook.

## Disclosed Reference & Assets
* [`scripts/dmp_mcp_client.py`](scripts/dmp_mcp_client.py) — zero-dependency CLI for DMP table search and column filtering.
* [`examples/demand-31939-golden-exploration.py`](examples/demand-31939-golden-exploration.py) — runnable end-to-end exploration template (DMP search + ODPS verification).
