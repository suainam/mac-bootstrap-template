#!/usr/bin/env python3
"""校验桑基图资金流向 Ledger 闭环守恒。"""

import argparse
import json
from pathlib import Path
import sys
candidates = [
    Path.cwd(),
    Path("/Users/suai/work/projects/product_strategy"),
]
REPO_ROOT = next((c for c in candidates if (c / "shared").is_dir()), Path.cwd())
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TOPIC_SCRIPTS = REPO_ROOT / "topics" / "franchise_store" / "03_analysis" / "scripts"
if str(TOPIC_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(TOPIC_SCRIPTS))
from core.sankey_engine import validate_sankey_ledger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_json", type=Path, help="Path to franchise_store_sankey_flow_*.json")
    args = parser.parse_args()

    if not args.dataset_json.is_file():
        print(f"Error: dataset file not found: {args.dataset_json}", file=sys.stderr)
        return 1

    data = json.loads(args.dataset_json.read_text(encoding="utf-8"))
    try:
        validate_sankey_ledger(data)
        print(f"[SUCCESS] Sankey dataset {args.dataset_json.name} is ledger-balanced.")
        return 0
    except Exception as e:
        print(f"[FAIL] Sankey ledger validation error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
