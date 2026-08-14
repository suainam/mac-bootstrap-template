#!/usr/bin/env python3
"""Compare AgentShield findings with a privacy-safe acknowledged baseline."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any


class InvalidBaseline(ValueError):
    pass


def finding_key(finding: Any, *, hash_fingerprint: bool) -> tuple[str, str, str, str]:
    if not isinstance(finding, dict):
        raise InvalidBaseline
    finding_id = finding.get("id")
    file = finding.get("file")
    severity = finding.get("severity")
    if (
        not isinstance(finding_id, str)
        or not finding_id
        or not isinstance(file, str)
        or not file
        or severity not in {"critical", "high"}
    ):
        raise InvalidBaseline
    if hash_fingerprint:
        fingerprint = finding.get("fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise InvalidBaseline
        digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    else:
        digest = finding.get("fingerprint_sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise InvalidBaseline
        try:
            bytes.fromhex(digest)
        except ValueError as error:
            raise InvalidBaseline from error
    return finding_id, file, severity, digest


def finding_counter(
    value: Any, *, hash_fingerprint: bool
) -> Counter[tuple[str, str, str, str]]:
    if not isinstance(value, list):
        raise InvalidBaseline
    return Counter(finding_key(item, hash_fingerprint=hash_fingerprint) for item in value)


def safe_label(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._/:-" else "?" for ch in value)[:160]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scan")
    parser.add_argument("baseline")
    args = parser.parse_args()

    try:
        scan = json.loads(Path(args.scan).read_text(encoding="utf-8"))
        if not isinstance(scan, dict):
            raise InvalidBaseline
        current = finding_counter(scan.get("findings"), hash_fingerprint=True)
    except (InvalidBaseline, OSError, json.JSONDecodeError):
        print("invalid_scan_baseline")
        return 2

    try:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        if not isinstance(baseline, dict) or baseline.get("version") != 2:
            raise InvalidBaseline
        acknowledged = finding_counter(
            baseline.get("acknowledged_findings"), hash_fingerprint=False
        )
    except (InvalidBaseline, OSError, json.JSONDecodeError):
        print("invalid_acknowledged_baseline")
        return 2

    if current == acknowledged:
        print(f"acknowledged={sum(current.values())}")
        return 0

    for key in sorted((current - acknowledged).elements()):
        print(
            f"new_or_changed id={safe_label(key[0])} "
            f"file={safe_label(key[1])} severity={safe_label(key[2])}"
        )
    for key in sorted((acknowledged - current).elements()):
        print(
            f"no_longer_present id={safe_label(key[0])} "
            f"file={safe_label(key[1])} severity={safe_label(key[2])}"
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
