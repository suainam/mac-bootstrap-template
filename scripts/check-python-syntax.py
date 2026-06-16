#!/usr/bin/env python3
"""AST-parse Python files without writing pyc caches."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: check-python-syntax.py <file> [<file> ...]", file=sys.stderr)
        return 2

    for name in argv[1:]:
        path = Path(name)
        ast.parse(path.read_text(), filename=str(path))
        print(f"ok {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
