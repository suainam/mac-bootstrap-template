#!/usr/bin/env python3
"""ODPS 表快速画像探查 CLI (odps_quick_probe).

用法:
  python odps_quick_probe.py dsl_ads.ads_item_3he1_db_1_6_store_item_xiafa_df --keys store_code,item_code
"""

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(REPO_ROOT))

from shared.odps_connector import ODPSConnector
from shared.config import ODPSConfig


def probe_table(table_name: str, keys: list[str] | None = None):
    cfg = ODPSConfig()
    odps = ODPSConnector(cfg).connect()

    print(f"=== Table Probe: {table_name} ===")
    t = odps.get_table(table_name)
    
    print("\n[Partitions]")
    partitions = list(t.partitions)
    if partitions:
        print(f"  Total partitions: {len(partitions)}")
        for p in partitions[-5:]:
            print(f"  Partition: {p.name}")
    else:
        print("  Non-partitioned table.")

    # 查 MAX_PT
    if partitions:
        max_pt_sql = f"SELECT MAX_PT('{table_name}')"
        res = odps.execute_sql(max_pt_sql).open_reader().read()
        max_pt = res[0][0]
        print(f"  MAX_PT: {max_pt}")
        where_clause = f"WHERE stat_date = '{max_pt}'" if 'stat_date' in partitions[0].name else f"WHERE pt = '{max_pt}'"
    else:
        where_clause = ""

    # 查行数与主键唯一性
    if keys:
        keys_str = ", ".join(keys)
        sql = f"""
        SELECT 
            COUNT(1) as total_rows,
            COUNT(DISTINCT {keys_str}) as distinct_keys,
            COUNT(1) - COUNT(DISTINCT {keys_str}) as dup_count
        FROM {table_name}
        {where_clause};
        """
        print(f"\n[Uniqueness Probe on ({keys_str})]")
        inst = odps.execute_sql(sql)
        with inst.open_reader() as reader:
            for r in reader:
                print(f"  Total rows: {r['total_rows']}")
                print(f"  Distinct keys: {r['distinct_keys']}")
                print(f"  Duplicate count: {r['dup_count']}")
                if r['dup_count'] == 0:
                    print("  Status: UNIQUE (PASS)")
                else:
                    print("  Status: DUPLICATES DETECTED (FAIL)")


def main():
    parser = argparse.ArgumentParser(description="Quick ODPS table profiler")
    parser.add_argument("table", help="Full table name: project.table_name")
    parser.add_argument("--keys", help="Comma-separated primary key columns")
    args = parser.parse_args()

    keys = [k.strip() for k in args.keys.split(",")] if args.keys else None
    probe_table(args.table, keys)


if __name__ == "__main__":
    main()
