#!/usr/bin/env python3
"""Check a rewrite against a claim-first case invariant.

Usage:
    check_rewrite.py --case <id> --rewrite <path|->  [--cases <path>]
    check_rewrite.py --self-test

A case carries the invariants a rewrite must satisfy: facts that must survive
(`must_keep`), defensive patterns that must go (`must_drop`), and the numeric
tokens of the source, which are compared both ways so a dropped figure or an
invented one fails.

Exit 0 = every invariant holds. Exit 1 = at least one violation. Exit 2 = the
case or input is unusable, which is not a verdict on the rewrite.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CASE_FILE = Path(__file__).resolve().parents[1] / "examples" / "cases.json"

NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*\s*(?:%|ms|s|MB|GB)?", re.IGNORECASE)
# Chinese numeral + measure word counts as a quantity: 五个数据集, 三种环境.
# Digits alone miss these, and an invented sample size hides exactly there.
COUNT_RE = re.compile(r"[一二三四五六七八九十百千零两]+(?=[个种项类次组条篇位名版])")


def numbers(text: str) -> list[str]:
    found = [match.group(0).strip() for match in NUMBER_RE.finditer(text)]
    found.extend(match.group(0) for match in COUNT_RE.finditer(text))
    return found


def load_cases(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"no cases in {path}")
    return {case["id"]: case for case in cases}


def check(case: dict, rewrite: str) -> list[str]:
    violations: list[str] = []

    for fact in case.get("must_keep", []):
        # A list entry means the fact may be worded any of those ways; a rewrite
        # is free to pick the natural one, but it must carry the fact.
        accepted = fact if isinstance(fact, list) else [fact]
        if not any(candidate in rewrite for candidate in accepted):
            violations.append(f"missing kept fact: {' | '.join(accepted)}")

    for pattern in case.get("must_drop", []):
        if re.search(pattern, rewrite):
            violations.append(f"defensive pattern survived: {pattern}")

    source_numbers = set(numbers(case["source"]))
    rewrite_numbers = set(numbers(rewrite))
    for figure in sorted(source_numbers - rewrite_numbers):
        violations.append(f"dropped figure: {figure}")
    for figure in sorted(rewrite_numbers - source_numbers):
        violations.append(f"invented figure: {figure}")

    return violations


def self_test(cases: dict[str, dict]) -> int:
    """Every golden rewrite must pass; every source must fail its own case."""
    failures: list[str] = []
    for case_id, case in sorted(cases.items()):
        expected = case.get("expected")
        if expected is None:
            failures.append(f"{case_id}: no expected rewrite")
            continue
        remaining = check(case, expected)
        if remaining:
            failures.append(f"{case_id}: golden rewrite violates {remaining}")
        if not check(case, case["source"]):
            failures.append(f"{case_id}: unmodified source passes, case is inert")
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    if failures:
        return 1
    print(f"ok self-test: {len(cases)} cases")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASE_FILE)
    parser.add_argument("--case")
    parser.add_argument("--rewrite", help="path to the rewrite, or - for stdin")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    try:
        cases = load_cases(args.cases)
    except (OSError, ValueError, KeyError) as exc:
        print(f"cannot load cases: {exc}", file=sys.stderr)
        return 2

    if args.self_test:
        return self_test(cases)

    if not args.case or args.rewrite is None:
        parser.error("--case and --rewrite are required unless --self-test is given")
    if args.case not in cases:
        print(f"unknown case: {args.case}", file=sys.stderr)
        return 2

    if args.rewrite == "-":
        rewrite = sys.stdin.read()
    else:
        rewrite = Path(args.rewrite).read_text(encoding="utf-8")

    violations = check(cases[args.case], rewrite)
    for violation in violations:
        print(f"VIOLATION {violation}", file=sys.stderr)
    if violations:
        return 1
    print(f"ok {args.case}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
