#!/usr/bin/env python3
"""Golden Example: Data Exploration & Analysis Pipeline for Demand-31939.

Demonstrates:
1. Safe credential cascading from ~/.env and project .env
2. Metadata inspection via DMP MCP client
3. Ad-hoc MaxCompute (PyODPS) query execution via uv
4. Cross-analysis of store tags, private brands, and medical insurance catalogs
"""
import os
import json
import urllib.request
import subprocess
from pathlib import Path

MCP_ENDPOINT = "http://dmp-search-mcp-vpc.dslbuy.com/mcp"

def call_mcp_tool(tool_name: str, arguments: dict) -> dict:
    """Call DMP Search MCP directly with proxy bypass."""
    req = urllib.request.Request(
        MCP_ENDPOINT,
        data=json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments}
        }).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json"
        }
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
        for line in raw.split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[6:])
                return data.get("result", {})
    return {}
def load_odps_env() -> dict:
    """Load ODPS credentials from ~/.env (per AGENTS.md guardrail)."""
    env_vars = {}
    home_env = Path.home() / ".env"
    for line in home_env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip().strip("'\"")
    return {**os.environ, **env_vars}

def run_odps_query(sql: str, title: str = ""):
    """Run an ad-hoc query via uv and PyODPS without container overhead."""
    if title:
        print(f"\n=== [ODPS Query] {title} ===")
    
    py_runner = f"""
import os
from odps import ODPS

c = ODPS(
    os.environ['ODPS_ACCESS_ID'],
    os.environ['ODPS_SECRET_KEY'],
    project=os.environ.get('ODPS_PROJECT', 'dsl_ai'),
    endpoint=os.environ.get('ODPS_ENDPOINT', 'https://service.cn-shenzhen.maxcompute.aliyun.com/api')
)

inst = c.execute_sql(\"\"\"{sql}\"\"\")
with inst.open_reader() as r:
    cols = [col.name for col in r.schema.columns]
    print("\\t".join(cols))
    for row in r:
        print("\\t".join([str(row[col]) for col in cols]))
"""
    env = load_odps_env()
    res = subprocess.run(
        ["uv", "run", "--with", "pyodps", "--no-project", "python", "-c", py_runner],
        env=env,
        capture_output=True,
        text=True,
        timeout=180
    )
    if res.returncode != 0:
        print("ERROR:", res.stderr.strip())
    else:
        print(res.stdout.strip())

def main():
    print("Step 1: Inspecting Table Metadata via DMP MCP...")
    # Search for medical insurance comparison table
    search_res = call_mcp_tool("search", {"keyword": "医保目录对照", "top": 3})
    print("DMP Search Result:")
    print(search_res.get("content", [{}])[0].get("text", "")[:300] + "...")

    print("\nStep 2: Checking Store Tags Distribution in Target Provinces...")
    sql_store_tags = """
    SELECT 
        state_name_mdm,
        count(1) as total_stores,
        count(case when coalesce(is_coordinate_stores, 0) = 1 then 1 end) as tc_stores,
        count(case when mbfwlx = 'Y' then 1 end) as mb_stores,
        count(case when coalesce(is_coordinate_stores, 0) = 1 and mbfwlx = 'Y' then 1 end) as tc_and_mb_stores
    FROM dsl_dim.dim_store
    WHERE stat_date = (SELECT max(stat_date) FROM dsl_dim.dim_store)
      AND delete_flg = 'N'
      AND opert_close_date > (SELECT max(stat_date) FROM dsl_dim.dim_store)
      AND store_code > 999999999
      AND state_name_mdm in ('上海市', '新疆维吾尔自治区', '河北省', '山西省', '内蒙古自治区', '浙江省')
    GROUP BY state_name_mdm
    ORDER BY total_stores DESC
    """
    run_odps_query(sql_store_tags, "Store Tags in Target Regions")

    print("\nStep 3: Checking Item Attributes (Private Brand & Medical Insurance)...")
    sql_item_attrs = """
    SELECT 
        group_name,
        count(1) as total_items,
        count(case when yb_code is not null and yb_code != '' and yb_code != '0' then 1 end) as yb_code_cnt,
        count(case when dlsx_cate = '自有品牌' then 1 end) as zypp_cnt
    FROM dsl_dim.dim_item_master
    WHERE stat_date = (SELECT max(stat_date) FROM dsl_dim.dim_item_master)
    GROUP BY group_name
    ORDER BY total_items DESC
    LIMIT 10
    """
    run_odps_query(sql_item_attrs, "Item Master Attributes Distribution")

if __name__ == "__main__":
    main()
