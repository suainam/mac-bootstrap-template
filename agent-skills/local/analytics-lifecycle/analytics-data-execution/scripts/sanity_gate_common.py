"""Shared input loading and field parsing for the execution sanity gates.

Both the state-transition matrix gate and the legacy binary-conservation gate
read a long table and must reject the same malformed cells: missing keys, NaN
amounts, non 0/1 flags, and unknown source tokens. Keeping those parsers in one
module means a new gate inherits the same input contract.
"""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SOURCE_TOKENS = frozenset({"target", "non_target"})
DEFAULT_AMOUNT_TOLERANCE = 0.05
SAMPLE_LIMIT = 5


class AuditInputError(ValueError):
    """输入协议不满足时抛出，CLI 统一转为退出码 1。"""


def load_records(path: Path, sheet_name: str | int | None = None) -> list[dict[str, Any]]:
    """按扩展名加载长表记录；CSV/JSONL 走标准库，Parquet/Excel 需要 pandas。"""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            return [dict(row) for row in csv.DictReader(fh)]
    if suffix in {".jsonl", ".ndjson"}:
        records = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records
    if suffix in {".parquet", ".xlsx"}:
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover - 依赖环境
            raise AuditInputError(
                f"读取 {suffix} 需要 pandas，请改用 .csv/.jsonl 或安装 pandas"
            ) from exc
        if suffix == ".parquet":
            frame = pd.read_parquet(path)
        else:
            sheet = 0 if sheet_name is None else sheet_name
            frame = pd.read_excel(path, sheet_name=sheet)
        return frame.to_dict(orient="records")
    raise AuditInputError(f"不支持的数据文件类型: {suffix}（支持 .csv/.jsonl/.parquet/.xlsx）")


def _parse_flag(value: Any, column: str, row_index: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not value.is_integer():
            raise AuditInputError(f"第 {row_index} 行 {column}={value!r} 不是 0/1 整数")
        number = int(value)
        if number in (0, 1):
            return number
        raise AuditInputError(f"第 {row_index} 行 {column}={value!r} 非法，必须为 0 或 1")
    text = str(value).strip()
    if text in {"0", "1"}:
        return int(text)
    raise AuditInputError(f"第 {row_index} 行 {column}={value!r} 非法，必须为 0 或 1")


def _parse_amount(value: Any, column: str, row_index: int) -> float:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise AuditInputError(f"第 {row_index} 行 {column} 为空，金额不得缺失")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AuditInputError(f"第 {row_index} 行 {column}={value!r} 不是数值") from exc
    if not math.isfinite(number):
        raise AuditInputError(f"第 {row_index} 行 {column}={value!r} 为 NaN/Inf")
    return number


def _parse_source(value: Any, row_index: int) -> frozenset[str]:
    if value is None:
        raise AuditInputError(f"第 {row_index} 行 source 为空，必须显式标注来源")
    text = str(value).strip()
    if not text:
        raise AuditInputError(f"第 {row_index} 行 source 为空，必须显式标注来源")
    tokens = {token.strip() for token in text.replace(",", ";").split(";") if token.strip()}
    unknown = tokens - SOURCE_TOKENS
    if unknown:
        raise AuditInputError(
            f"第 {row_index} 行 source={value!r} 含未知 token {sorted(unknown)}，"
            f"仅允许 {sorted(SOURCE_TOKENS)}"
        )
    return frozenset(tokens)


def _parse_key_text(value: Any, column: str, row_index: int) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise AuditInputError(f"第 {row_index} 行 {column} 为空，主键不得缺失")
    return text


def _format_sample(items: Iterable[Any], limit: int = SAMPLE_LIMIT) -> str:
    sample = list(items)[:limit]
    return ", ".join(str(item) for item in sample) if sample else "-"
