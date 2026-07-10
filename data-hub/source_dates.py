#!/usr/bin/env python3
"""
Shared date resolution rules for external source ingestion and reporting.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


DEFAULT_SOURCE_DATE_MODE = os.environ.get("EXTERNAL_SOURCE_DATE_MODE", "filename_first")


def extract_date_prefix(value: str) -> str | None:
    match = re.match(r"^(\d{4}-\d{2}-\d{2})(?:_|$)", Path(value).name)
    return match.group(1) if match else None


def coerce_metadata(metadata_json: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(metadata_json, dict):
        return metadata_json
    if not metadata_json:
        return {}
    try:
        return json.loads(metadata_json)
    except json.JSONDecodeError:
        return {}


def resolve_document_dates(
    path: str,
    version_tag: str | None,
    captured_at: str | None,
    metadata_json: str | dict[str, Any] | None = None,
) -> dict[str, str | None]:
    metadata = coerce_metadata(metadata_json)
    filename_date = metadata.get("filename_date") or extract_date_prefix(path)
    version_date = str(version_tag)[:10] if version_tag else None
    landing_date = metadata.get("landing_date") or (str(captured_at)[:10] if captured_at else None)
    return {
        "filename_date": filename_date,
        "version_date": version_date,
        "landing_date": landing_date,
    }


def document_matches_target(
    path: str,
    version_tag: str | None,
    captured_at: str | None,
    metadata_json: str | dict[str, Any] | None,
    target_date: str,
    mode: str | None = None,
) -> bool:
    dates = resolve_document_dates(path, version_tag, captured_at, metadata_json)
    source_date_mode = mode or DEFAULT_SOURCE_DATE_MODE
    if source_date_mode in {"filename_first", "landing_or_filename"}:
        if dates["filename_date"]:
            return dates["filename_date"] == target_date
        return dates["landing_date"] == target_date
    if source_date_mode == "filename_only":
        return dates["filename_date"] == target_date
    if source_date_mode == "filename_or_version":
        return dates["filename_date"] == target_date or dates["version_date"] == target_date
    if source_date_mode == "all_signals":
        return target_date in {dates["filename_date"], dates["version_date"], dates["landing_date"]}
    return dates["landing_date"] == target_date
