#!/usr/bin/env python3
"""ODPS / MaxCompute Partition Ingestion & Post-Write Verification.

Loads staged CSV/DataFrame, type-coerces columns according to schema,
writes to target table/partition, and runs aggregation verification SQL.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from odps import ODPS
import pandas as pd


def load_env(env_path: Path | None = None) -> dict[str, str]:
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
        raise RuntimeError("Missing ODPS credentials.")

    return ODPS(access_id, secret_key, project=project, endpoint=endpoint)


def upload_and_verify(
    table_full_name: str,
    source_csv: Path,
    mapping_json: Path | None = None,
    partition_spec: str | None = None,
    env_path: Path | None = None,
) -> dict[str, Any]:
    parts = table_full_name.split(".")
    if len(parts) == 2:
        project, table_name = parts
    else:
        project = None
        table_name = parts[0]

    odps = make_odps_client(env_path)
    target_project = project or odps.project
    t = odps.get_table(table_name, project=target_project)

    df_src = pd.read_csv(source_csv, dtype=str)
    schema_cols = [c.name for c in t.table_schema.simple_columns]
    schema_types = {c.name: str(c.type).upper() for c in t.table_schema.simple_columns}

    mapping: dict[str, str] = {}
    if mapping_json and mapping_json.exists():
        mapping = json.loads(mapping_json.read_text(encoding="utf-8"))
    else:
        # Default 1:1 if names match
        for col in schema_cols:
            if col in df_src.columns:
                mapping[col] = col

    # Prepare rows
    rows_to_insert = []
    for _, row in df_src.iterrows():
        record = []
        for col_name in schema_cols:
            src_col = mapping.get(col_name)
            val = row.get(src_col) if src_col else None
            t_type = schema_types.get(col_name, "STRING")

            if val is None or pd.isna(val) or str(val).strip() == "":
                record.append(None)
            else:
                s_val = str(val).strip()
                if t_type in ("BIGINT", "INT", "SMALLINT", "TINYINT"):
                    try:
                        record.append(int(float(s_val)))
                    except Exception:
                        record.append(None)
                elif t_type in ("DOUBLE", "FLOAT", "DECIMAL"):
                    try:
                        record.append(float(s_val))
                    except Exception:
                        record.append(None)
                else:
                    record.append(s_val)
        rows_to_insert.append(record)

    total_rows = len(rows_to_insert)
    print(f"Staged {total_rows} records ready for upload to {target_project}.{table_name}...")

    # Handle Partition
    if partition_spec:
        t.create_partition(partition_spec, if_not_exists=True)
        with t.open_writer(partition=partition_spec, create_partition=True) as writer:
            writer.write(rows_to_insert)
    else:
        with t.open_writer() as writer:
            writer.write(rows_to_insert)

    print("Write complete. Running verification SQL...")

    # Build verification query
    where_clause = f"WHERE {partition_spec.replace(',', ' AND ')}" if partition_spec else ""
    
    # Identify numeric & key columns for summary
    num_cols = [c for c, tp in schema_types.items() if tp in ("DOUBLE", "FLOAT", "DECIMAL")]
    key_cols = [c for c, tp in schema_types.items() if tp in ("STRING", "BIGINT")][:3]

    aggs = ["COUNT(1) AS row_cnt"]
    for nc in num_cols[:2]:
        aggs.append(f"ROUND(SUM({nc}), 2) AS sum_{nc}")
    for kc in key_cols:
        aggs.append(f"COUNT(DISTINCT {kc}) AS distinct_{kc}")

    sql = f"""
    SELECT 
        {', '.join(aggs)}
    FROM {target_project}.{table_name}
    {where_clause};
    """

    inst = odps.execute_sql(sql)
    verify_result = {}
    with inst.open_reader() as reader:
        for rec in reader:
            cols = [c.name for c in reader._schema.columns]
            verify_result = dict(zip(cols, rec.values))

    return {
        "table": f"{target_project}.{table_name}",
        "partition": partition_spec,
        "staged_rows": total_rows,
        "verification": verify_result,
        "logview": inst.get_logview_address(),
    }


def main():
    parser = argparse.ArgumentParser(description="Upload dataset to MaxCompute and verify.")
    parser.add_argument("table", help="Target table name (e.g. dsl_analysis.my_table_df)")
    parser.add_argument("source_csv", type=Path, help="Staged CSV file path")
    parser.add_argument("--partition", type=str, default=None, help="Partition spec (e.g. stat_date=20260826)")
    parser.add_argument("--mapping", type=Path, default=None, help="Mapping JSON file (target_col -> source_col)")
    parser.add_argument("--env-file", type=Path, default=None, help="Path to .env file")
    args = parser.parse_args()

    res = upload_and_verify(args.table, args.source_csv, args.mapping, args.partition, args.env_file)
    print("\n✅ Upload & Verification Result:")
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
