#!/usr/bin/env python3
"""ODPS / MaxCompute Table Introspection Tool.

Retrieves table existence, native column schema, comments,
partition specifications, existing partitions, and recent sample data.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from odps import ODPS


def load_env(env_path: Path | None = None) -> dict[str, str]:
    """Cascading load of ODPS credentials from env_path, local .env, and environment."""
    values: dict[str, str] = {}
    candidate_paths = [
        env_path,
        Path.cwd() / ".env",
        Path.home() / "work/projects/www/marimo/merchandise/.env",
        Path.home() / ".env",
    ]
    for p in candidate_paths:
        if p and p.exists():
            for raw_line in p.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                    v = v[1:-1]
                values.setdefault(k.strip(), v)

    # Environment variables take precedence
    for k, v in os.environ.items():
        if k.startswith("ODPS_") or k.startswith("ALIBABA_CLOUD_"):
            values[k] = v
    return values


def make_odps_client(env_path: Path | None = None) -> ODPS:
    env = load_env(env_path)
    access_id = env.get("ODPS_ACCESS_ID") or env.get("ALIBABA_CLOUD_ACCESS_KEY_ID")
    secret_key = (
        env.get("ODPS_SECRET_KEY")
        or env.get("ODPS_SECRET_ACCESS_KEY")
        or env.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
    )
    project = env.get("ODPS_PROJECT", "dsl_analysis")
    endpoint = env.get(
        "ODPS_ENDPOINT", "http://service.cn-shanghai.maxcompute.aliyun.com/api"
    )

    if not access_id or not secret_key:
        raise RuntimeError("Missing ODPS credentials (ODPS_ACCESS_ID / ODPS_SECRET_KEY).")

    return ODPS(access_id, secret_key, project=project, endpoint=endpoint)


def introspect(table_full_name: str, env_path: Path | None = None) -> dict[str, Any]:
    parts = table_full_name.split(".")
    if len(parts) == 2:
        project, table_name = parts
    else:
        project = None
        table_name = parts[0]

    odps = make_odps_client(env_path)
    target_project = project or odps.project

    exists = odps.exist_table(table_name, project=target_project)
    if not exists:
        # Check if there's a common typo or similar table
        similar_tables = [
            t.name for t in odps.list_tables(project=target_project, prefix=table_name[:8])
        ]
        return {
            "table": f"{target_project}.{table_name}",
            "exists": False,
            "similar_tables": similar_tables[:10],
        }

    t = odps.get_table(table_name, project=target_project)

    columns = [
        {"name": col.name, "type": str(col.type), "comment": col.comment or ""}
        for col in t.table_schema.simple_columns
    ]
    partitions = [
        {"name": part.name, "type": str(part.type), "comment": part.comment or ""}
        for part in t.table_schema.partitions
    ]

    existing_partitions = [p.name for p in list(t.partitions)] if partitions else []

    sample_rows = []
    try:
        if partitions and existing_partitions:
            latest_part = t.get_partition(existing_partitions[-1])
            with latest_part.open_reader() as reader:
                for rec in reader[:3]:
                    sample_rows.append(list(rec.values))
        elif not partitions:
            with t.open_reader() as reader:
                for rec in reader[:3]:
                    sample_rows.append(list(rec.values))
    except Exception as e:
        sample_rows = [f"Error fetching samples: {e}"]

    return {
        "table": f"{target_project}.{table_name}",
        "exists": True,
        "comment": t.comment or "",
        "columns": columns,
        "partitions": partitions,
        "existing_partitions": existing_partitions[-10:],
        "sample_rows": sample_rows,
    }


def main():
    parser = argparse.ArgumentParser(description="Introspect MaxCompute / ODPS table.")
    parser.add_argument("table", help="Table name (e.g. dsl_analysis.my_table_df)")
    parser.add_argument("--env-file", type=Path, default=None, help="Path to .env credential file")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    result = introspect(args.table, args.env_file)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if not result["exists"]:
        print(f"❌ Table '{result['table']}' does NOT exist.")
        if result.get("similar_tables"):
            print(f"Did you mean one of these? {', '.join(result['similar_tables'])}")
        sys.exit(1)

    print(f"=== Table: {result['table']} ===")
    print(f"Comment: {result['comment']}")
    print("\nColumns:")
    for col in result["columns"]:
        print(f"  - {col['name']} ({col['type']}): {col['comment']}")

    if result["partitions"]:
        print("\nPartition Key(s):")
        for part in result["partitions"]:
            print(f"  - {part['name']} ({part['type']}): {part['comment']}")
        print(f"\nRecent Existing Partitions ({len(result['existing_partitions'])} shown):")
        for p in result["existing_partitions"]:
            print(f"  - {p}")
    else:
        print("\nTable is UNPARTITIONED.")


if __name__ == "__main__":
    main()
