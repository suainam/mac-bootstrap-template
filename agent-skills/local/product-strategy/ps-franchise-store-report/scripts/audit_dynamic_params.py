#!/usr/bin/env python3
"""审查生产 Python/SQL 是否残留日期、业务年度或个人绝对路径硬编码。"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


DATE_LITERAL = re.compile(r"(?<!\d)20\d{6}(?!\d)")
YEAR_LITERAL = re.compile(r"(?<!\d)20(?:1\d|2\d)(?!\d)")
PERSONAL_PATH = re.compile(r"['\"]/" + "(?:Users|Volumes)" + "/")


def _is_comment_or_doc(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith(("#", "--", "/*", "*", "//"))


def _allowed_year_line(line: str) -> bool:
    # 命令行兼容别名是接口兼容，不参与业务计算；年份后缀列名则必须动态生成。
    return "--market-2025" in line or "--market-2026" in line


def audit_file(path: Path, include_docs: bool = False) -> list[str]:
    if path.suffix.lower() not in {".py", ".sql"} and not include_docs:
        return []
    findings: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if _is_comment_or_doc(line):
            continue
        if PERSONAL_PATH.search(line):
            findings.append(f"{path}:{line_number}: personal absolute path")
        if DATE_LITERAL.search(line):
            findings.append(f"{path}:{line_number}: date literal")
        code_without_urls = re.sub(r"https?://[^\s\"']+", "", line)
        if YEAR_LITERAL.search(code_without_urls) and not _allowed_year_line(line):
            findings.append(f"{path}:{line_number}: business year literal")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--include-docs", action="store_true")
    args = parser.parse_args(argv)
    findings = []
    for path in args.paths:
        if path.is_file():
            findings.extend(audit_file(path, args.include_docs))
        elif path.is_dir():
            for candidate in sorted(path.rglob("*")):
                if candidate.is_file():
                    findings.extend(audit_file(candidate, args.include_docs))
        else:
            findings.append(f"{path}: path not found")
    if findings:
        print("\n".join(findings))
        return 1
    print("dynamic parameter audit passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
