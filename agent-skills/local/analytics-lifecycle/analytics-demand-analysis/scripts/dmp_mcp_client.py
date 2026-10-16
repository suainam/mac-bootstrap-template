#!/usr/bin/env python3
"""DMP Search MCP Client for Data Warehouse metadata inspection.

Usage:
    python dmp_mcp_client.py search <keyword> [--top 10]
    python dmp_mcp_client.py detail <db_tb_nm>
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

def _default_mcp_endpoint() -> str:
    if os.environ.get("DMP_MCP_ENDPOINT"):
        return os.environ["DMP_MCP_ENDPOINT"]
    home_env = Path.home() / ".env"
    if home_env.exists():
        for line in home_env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DMP_MCP_ENDPOINT="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return "http://dmp-search-mcp-vpc.dslbuy.com/mcp"

MCP_ENDPOINT = _default_mcp_endpoint()
def call_mcp_tool(tool_name: str, arguments: dict) -> dict:
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
    # Crucial: bypass proxies for internal VPC addresses
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
        for line in raw.split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[6:])
                return data.get("result", {})
    return {}

def search_tables(keyword: str, top: int = 10):
    result = call_mcp_tool("search", {"keyword": keyword, "top": top})
    text = result.get("content", [{}])[0].get("text", "")
    print(text)

def get_table_detail(db_tb_nm: str, filter_keyword: str | None = None):
    result = call_mcp_tool("detail", {"db_tb_nm": db_tb_nm})
    text = result.get("content", [{}])[0].get("text", "")
    try:
        data = json.loads(text)
        print(f"Table: {data.get('db_tb_nm')}")
        print(f"Comment: {data.get('tb_cmt')}")
        print(f"Scene: {data.get('scene_desc')}")
        columns = data.get("columns", [])
        print(f"Total Columns: {len(columns)}")
        print("-" * 60)
        for col in columns:
            nm = col.get("col_nm", "")
            cmt = col.get("col_cmt", "") or ""
            typ = col.get("col_typ", "")
            if filter_keyword:
                if filter_keyword.lower() in nm.lower() or filter_keyword in cmt:
                    print(f"  {nm} ({typ}): {cmt}")
            else:
                print(f"  {nm} ({typ}): {cmt}")
    except json.JSONDecodeError:
        print(text)

def main():
    parser = argparse.ArgumentParser(description="DMP MCP Client")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    # search
    p_search = subparsers.add_parser("search", help="Search data warehouse tables")
    p_search.add_argument("keyword", help="Search keyword (Chinese or Pinyin)")
    p_search.add_argument("--top", type=int, default=10, help="Number of results")

    # detail
    p_detail = subparsers.add_parser("detail", help="Get table schema details")
    p_detail.add_argument("table", help="Table name like dsl_dim.dim_store")
    p_detail.add_argument("--filter", default=None, help="Filter columns by keyword")

    args = parser.parse_args()
    if args.cmd == "search":
        search_tables(args.keyword, args.top)
    elif args.cmd == "detail":
        get_table_detail(args.table, args.filter)

if __name__ == "__main__":
    main()
