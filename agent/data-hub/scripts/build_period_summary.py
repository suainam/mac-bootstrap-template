#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
DATA_HUB_DIR = CURRENT_DIR.parent
if str(DATA_HUB_DIR) not in sys.path:
    sys.path.insert(0, str(DATA_HUB_DIR))

from period_summary import build_period_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a period summary into 70_Summaries.")
    parser.add_argument("--level", choices=["weekly", "monthly", "quarterly", "yearly"], required=True)
    parser.add_argument("--anchor-date", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = build_period_summary(args.level, args.anchor_date)
    print(output_path)


if __name__ == "__main__":
    main()
