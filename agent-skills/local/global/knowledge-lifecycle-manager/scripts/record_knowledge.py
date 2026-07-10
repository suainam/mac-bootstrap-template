#!/usr/bin/env python3
"""Compatibility shim for the restored knowledge-record owner module."""

from __future__ import annotations

import importlib.util
from pathlib import Path


CANONICAL_SCRIPT = (
    Path(__file__).resolve().parents[4]
    / "local"
    / "mac-bootstrap"
    / "knowledge-record"
    / "scripts"
    / "record_knowledge.py"
)


def _load_canonical_module():
    spec = importlib.util.spec_from_file_location(
        "knowledge_record_compat_impl",
        CANONICAL_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


_CANONICAL = _load_canonical_module()

ALLOWED_AGENT_TYPES = _CANONICAL.ALLOWED_AGENT_TYPES
TAG_PATTERN = _CANONICAL.TAG_PATTERN
CJK_CHAR_PATTERN = _CANONICAL.CJK_CHAR_PATTERN
LATIN_CHAR_PATTERN = _CANONICAL.LATIN_CHAR_PATTERN
find_db_path = _CANONICAL.find_db_path
make_id = _CANONICAL.make_id
is_chinese_dominant = _CANONICAL.is_chinese_dominant
validate_chinese_dominant = _CANONICAL.validate_chinese_dominant
parse_tags = _CANONICAL.parse_tags
validate_agent_type = _CANONICAL.validate_agent_type
validate_args = _CANONICAL.validate_args
build_record = _CANONICAL.build_record
ensure_schema = _CANONICAL.ensure_schema
insert_record = _CANONICAL.insert_record


def main(argv: list[str] | None = None) -> int:
    return _CANONICAL.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
