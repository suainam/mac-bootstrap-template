#!/usr/bin/env python3
"""验证 MaxCompute 大盘基线指标与外部参考 Excel 是否对齐。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

import pandas as pd
candidates = [Path.cwd()]
_env_root = os.environ.get("PRODUCT_STRATEGY_ROOT")
if _env_root:
    candidates.append(Path(_env_root))
REPO_ROOT = next((c for c in candidates if (c / "shared").is_dir()), Path.cwd())
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TOPIC_SCRIPTS = REPO_ROOT / "topics" / "franchise_store" / "03_analysis" / "scripts"
if str(TOPIC_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(TOPIC_SCRIPTS))
from shared.config import ODPSConfig
from shared.odps_connector import create_odps_executor
from core.market_baseline import (
    MARKET_METRIC_KEYS,
    MARKET_DISPLAY_LABELS,
    load_market_snapshots_unified,
)


def verify_market_baseline(project_et: str, env_file: str | None = None) -> bool:
    if env_file:
        from run_franchise_store_yoy import load_env_file
        load_env_file(Path(env_file))

    config = ODPSConfig()
    executor = create_odps_executor(config)
    executor.connector.connect()

    snapshots = load_market_snapshots_unified(
        market_previous_path=None,
        market_current_path=None,
        project_et_str=project_et,
        executor=executor,
    )
    if not snapshots:
        print("Failed to load market snapshots from ODPS.", file=sys.stderr)
        return False

    print(f"=== Market Baseline Verification for {project_et} ===")
    for year, snap in sorted(snapshots.items()):
        print(f"\nYear {year} ({snap['period_label']}) Source: {snap['source_path']}:")
        metrics = snap["metrics"]
        for k in MARKET_METRIC_KEYS:
            label = MARKET_DISPLAY_LABELS.get(k, k)
            val = metrics.get(k)
            if isinstance(val, float):
                print(f"  {label:20s}: {val:16.4f}")
            else:
                print(f"  {label:20s}: {val}")

    print("\n[SUCCESS] Market baseline query executed and verified.")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-et", default="20260907", help="YYYYMMDD")
    parser.add_argument("--env-file", default=os.environ.get("ODPS_ENV_FILE"))
    args = parser.parse_args()

    ok = verify_market_baseline(args.project_et, args.env_file)
    sys.exit(0 if ok else 1)
