#!/usr/bin/env python3
"""Fuzzy Column Alignment & Mapping Proposal Generator.

Aligns source file columns (Excel/CSV) to target MaxCompute table columns
using domain synonym dictionaries, substring matching, and edit distance.
Generates an interactive markdown proposal for mandatory user confirmation.
"""

from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path
from typing import Any

import pandas as pd


# Common domain synonym dictionary for retail / supply chain
SYNONYM_MAP: dict[str, list[str]] = {
    "store_code": ["门店编码", "门店代码", "店号", "门店号", "store_code", "store_id", "dept_code"],
    "item_code": ["商品编码", "商品代码", "品号", "商品号", "item_code", "goods_code", "sku_id", "sku_code"],
    "lot": ["批号", "商品批号", "生产批号", "lot", "batch_no", "lot_no"],
    "st_qty": ["数量", "批号库存数量", "库存数量", "退货数量", "实收数量", "st_qty", "qty", "stock_qty", "inv_qty"],
    "st_amt": ["金额", "批号库存金额", "收货金额", "退货金额", "库存金额", "st_amt", "amt", "amount", "total_amt"],
    "store_item_lot_merge": ["店品批", "拼接", "店品批拼接", "store_item_lot_merge", "merge_key", "key_merge"],
    "item_lot_merge": ["品批", "品批拼接", "item_lot_merge"],
    "stat_date": ["日期", "统计日期", "业务日期", "分区日期", "stat_date", "dt", "ds"],
}


def score_match(src: str, target_name: str, target_comment: str) -> float:
    src_clean = src.strip().lower()
    target_clean = target_name.strip().lower()
    comment_clean = target_comment.strip().lower()

    # 1. Exact match with target name or comment
    if src_clean == target_clean or src_clean == comment_clean:
        return 1.0

    # 2. Synonym dictionary exact match
    synonyms = [s.lower() for s in SYNONYM_MAP.get(target_name, [])]
    if src_clean in synonyms:
        return 0.95

    # 3. Substring inclusion
    for syn in synonyms:
        if syn in src_clean or src_clean in syn:
            return 0.85
    if target_clean in src_clean or src_clean in target_clean:
        return 0.80
    if comment_clean and (comment_clean in src_clean or src_clean in comment_clean):
        return 0.75

    # 4. Difflib string similarity
    sim_name = difflib.SequenceMatcher(None, src_clean, target_clean).ratio()
    sim_comment = difflib.SequenceMatcher(None, src_clean, comment_clean).ratio() if comment_clean else 0.0
    max_sim = max(sim_name, sim_comment)
    return max_sim * 0.7


def align_columns(
    src_columns: list[str],
    target_columns: list[dict[str, Any]],
    threshold: float = 0.5,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Aligns source columns to target columns.

    Returns:
        (mapped_dict, unmapped_src_cols)
    """
    mapped: dict[str, dict[str, Any]] = {}
    unmapped_src = list(src_columns)

    # For each target column, find best matching source column
    for target in target_columns:
        t_name = target["name"]
        t_comment = target.get("comment", "")
        t_type = target.get("type", "STRING")

        best_src = None
        best_score = 0.0

        for src in src_columns:
            score = score_match(src, t_name, t_comment)
            if score > best_score and score >= threshold:
                best_score = score
                best_src = src

        if best_src:
            mapped[t_name] = {
                "source_col": best_src,
                "target_name": t_name,
                "target_type": t_type,
                "target_comment": t_comment,
                "confidence": round(best_score, 2),
            }
            if best_src in unmapped_src:
                unmapped_src.remove(best_src)
        else:
            mapped[t_name] = {
                "source_col": None,
                "target_name": t_name,
                "target_type": t_type,
                "target_comment": t_comment,
                "confidence": 0.0,
            }

    return mapped, unmapped_src


def render_markdown_proposal(
    table_name: str,
    partition_spec: str | None,
    mapped: dict[str, dict[str, Any]],
    unmapped_src: list[str],
    df_sample: pd.DataFrame | None = None,
) -> str:
    lines = []
    lines.append(f"### 字段对齐确认方案")
    lines.append(f"- **目标表**: `{table_name}`")
    if partition_spec:
        lines.append(f"- **目标分区**: `{partition_spec}`")
    lines.append("")
    lines.append("| ODPS 目标字段 | 类型 | 注释 | 来源列 | 匹配置信度 | 样例值 / 处理规则 |")
    lines.append("|---|---|---|---|---|---|")

    for t_name, info in mapped.items():
        src = info["source_col"]
        t_type = info["target_type"]
        t_comment = info["target_comment"]
        conf = info["confidence"]
        
        sample_val = "-"
        rule = "直接映射"
        if src and df_sample is not None and src in df_sample.columns:
            non_nulls = df_sample[src].dropna()
            if len(non_nulls) > 0:
                sample_val = str(non_nulls.iloc[0])[:30]

        if not src:
            src_display = "**[未匹配 - 待指定/填NULL]**"
            rule = "默认填充 NULL"
        else:
            src_display = f"`{src}`"
            if t_type.upper() in ("DOUBLE", "FLOAT", "DECIMAL"):
                rule = "转为数值型 (DOUBLE)"
            elif t_type.upper() in ("BIGINT", "INT", "SMALLINT", "TINYINT"):
                rule = "转为整型 (BIGINT)"
            elif t_type.upper() == "STRING":
                rule = "转为字符串"

        lines.append(f"| `{t_name}` | `{t_type}` | {t_comment} | {src_display} | {conf} | {rule} (例: `{sample_val}`) |")

    if unmapped_src:
        lines.append("")
        lines.append(f"**源文件中丢弃不入库的列 ({len(unmapped_src)} 列)**:")
        for col in unmapped_src:
            lines.append(f"- `{col}`")

    lines.append("")
    lines.append("> ⚠️ **操作守则**：请用户核对上述字段映射与类型转换规则。确认无误后再执行入库！")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate column alignment mapping.")
    parser.add_argument("source_file", type=Path, help="CSV or Excel source file path")
    parser.add_argument("--schema-json", type=Path, required=True, help="Table introspection JSON")
    parser.add_argument("--partition", type=str, default=None, help="Target partition spec (e.g. stat_date=20260826)")
    args = parser.parse_args()

    schema_data = json.loads(args.schema_json.read_text(encoding="utf-8"))
    target_columns = schema_data.get("columns", [])
    table_name = schema_data.get("table", "unknown_table")

    if args.source_file.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(args.source_file, nrows=10, dtype=str)
    else:
        df = pd.read_csv(args.source_file, nrows=10, dtype=str)

    src_cols = list(df.columns)
    mapped, unmapped = align_columns(src_cols, target_columns)

    proposal_md = render_markdown_proposal(table_name, args.partition, mapped, unmapped, df)
    print(proposal_md)


if __name__ == "__main__":
    main()
