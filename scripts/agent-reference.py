#!/usr/bin/env python3
"""Check or refresh the canonical agent path reference in the README."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- agent-reference:start -->"
END = "<!-- agent-reference:end -->"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--manifest", type=Path, default=ROOT / "agent/agent-manifest.json")
    parser.add_argument("--readme", type=Path, default=ROOT / "agent/README.md")
    args = parser.parse_args()
    try:
        canonical = json.loads(args.manifest.read_text())["canonical"]
        original = args.readme.read_text()
        if original.count(START) != 1 or original.count(END) != 1:
            raise ValueError("expected exactly one pair of agent-reference markers")
        start_idx = original.find(START)
        end_idx = original.find(END)
        if end_idx < start_idx:
            raise ValueError("expected START marker before END marker")
        left = original[:start_idx]
        right = original[end_idx + len(END):]
        rows = [f"| `{key}` | `{value}` |" for key, value in sorted(canonical.items())]
        section = "\n| Manifest key | Source path |\n|---|---|\n" + "\n".join(rows) + "\n"
        expected = left + START + section + END + right
        if args.write:
            if expected != original:
                args.readme.write_text(expected)
        elif expected != original:
            raise ValueError("agent reference is stale; run scripts/agent-reference.py --write")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"agent reference: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
