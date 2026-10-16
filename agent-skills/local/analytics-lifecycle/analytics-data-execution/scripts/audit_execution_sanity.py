#!/usr/bin/env python3
"""通用数据执行质检与对抗性核验脚本 (Universal Execution Sanity Gate CLI).

功能：
1. 实体样本覆盖与未预期漏损检查；
2. 数学单调性与二元互斥守恒核验（如：目录内 + 目录外 == 全店）；
3. 销售金额全额流水自洽核验（浮点误差容差 < 0.05元）；
4. 比率指标有界性核验 ([0, 100%])；
5. 空值语义防卫核验（未达条件实体动销率必须保留为 NULL，杜绝强转 0.00%）。

用法：
  python audit_execution_sanity.py --data dataset.parquet --id-col 门店编码 --total-sku 全店总在营商品数 --part1-sku 目录内在营商品数 --part2-sku 目录外手工在营商品数 --total-amt 全店总销售额_元 --part1-amt 目录内销售额_元 --part2-amt 目录外手工销售额_元
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import pandas as pd
import numpy as np


def run_sanity_audit(
    df: pd.DataFrame,
    id_col: str,
    total_sku_col: str | None = None,
    part1_sku_col: str | None = None,
    part2_sku_col: str | None = None,
    total_amt_col: str | None = None,
    part1_amt_col: str | None = None,
    part2_amt_col: str | None = None,
    rate_cols: list[str] | None = None,
    null_guard_pairs: list[tuple[str, str]] | None = None,
) -> tuple[bool, list[str]]:
    """执行通用数据质量与单调性守恒检查."""
    errors = []
    logs = []
    
    total_rows = len(df)
    unique_entities = df[id_col].nunique()
    logs.append(f"• 实体样本总数: {total_rows} 行 (去重实体: {unique_entities} 个)")
    if total_rows != unique_entities:
        errors.append(f"❌ 主键粒度不唯一: 总行数 {total_rows} != 实体数 {unique_entities}")
    else:
        logs.append(f"✅ 主键粒度唯一: {id_col} 无笛卡尔积重复")

    # 1. SKU 数量二元互斥守恒
    if total_sku_col and part1_sku_col and part2_sku_col:
        sku_diff = (df[part1_sku_col] + df[part2_sku_col] - df[total_sku_col]).abs().max()
        logs.append(f"• SKU 数量互斥守恒检验: MAX(|{part1_sku_col} + {part2_sku_col} - {total_sku_col}|) = {sku_diff}")
        if sku_diff == 0:
            logs.append("  ✅ SKU 数量二元互斥守恒成立")
        else:
            errors.append(f"❌ SKU 数量不守恒，最大差额: {sku_diff}")

    # 2. 金额全额流水自洽守恒
    if total_amt_col and part1_amt_col and part2_amt_col:
        amt_diff = (df[part1_amt_col] + df[part2_amt_col] - df[total_amt_col]).abs().max()
        logs.append(f"• 销售金额自洽守恒检验: MAX(|{part1_amt_col} + {part2_amt_col} - {total_amt_col}|) = {amt_diff:.4f} 元")
        if amt_diff < 0.05:
            logs.append("  ✅ 销售金额全额流水自洽成立 (浮点误差 < 0.05元)")
        else:
            errors.append(f"❌ 销售金额不自洽，最大差额: {amt_diff:.4f} 元")

    # 3. 比率上下限区间有界性
    if rate_cols:
        for r_col in rate_cols:
            if r_col in df.columns:
                valid_vals = df[r_col].dropna()
                if len(valid_vals) > 0:
                    min_v, max_v = valid_vals.min(), valid_vals.max()
                    if min_v < -0.01 or max_v > 100.01:
                        errors.append(f"❌ 比率指标 {r_col} 超出 [0, 100%] 区间! 范围: [{min_v}, {max_v}]")
                    else:
                        logs.append(f"  ✅ 比率指标 {r_col} 范围合规: [{min_v}%, {max_v}%]")

    # 4. 语义空值与零隔离防卫
    if null_guard_pairs:
        for cond_col, guard_col in null_guard_pairs:
            if cond_col in df.columns and guard_col in df.columns:
                null_scope = df[df[cond_col] == 0]
                if len(null_scope) > 0:
                    bad_not_null = null_scope[guard_col].notna().sum()
                    if bad_not_null > 0:
                        errors.append(f"❌ 发现 {bad_not_null} 条当 {cond_col}=0 时 {guard_col} 被强刷成了非空数值!")
                    else:
                        logs.append(f"  ✅ 当 {cond_col}=0 时 {guard_col} 严格保留为 NULL 语义")

    is_passed = len(errors) == 0
    return is_passed, logs + errors


def main():
    parser = argparse.ArgumentParser(description="Universal Data Execution Sanity Gate")
    parser.add_argument("--data", required=True, help="Path to parquet or xlsx file")
    parser.add_argument("--id-col", required=True, help="Primary entity key column name")
    parser.add_argument("--total-sku", help="Total SKU column name")
    parser.add_argument("--part1-sku", help="Catalog SKU column name")
    parser.add_argument("--part2-sku", help="Manual SKU column name")
    parser.add_argument("--total-amt", help="Total sales amount column name")
    parser.add_argument("--part1-amt", help="Catalog sales amount column name")
    parser.add_argument("--part2-amt", help="Manual sales amount column name")
    parser.add_argument("--rate-cols", help="Comma-separated rate column names")
    args = parser.parse_args()

    p = Path(args.data)
    if not p.exists():
        print(f"File not found: {p}", file=sys.stderr)
        sys.exit(1)

    df = pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_excel(p)
    rates = [c.strip() for c in args.rate_cols.split(",")] if args.rate_cols else None

    passed, report_lines = run_sanity_audit(
        df=df,
        id_col=args.id_col,
        total_sku_col=args.total_sku,
        part1_sku_col=args.part1_sku,
        part2_sku_col=args.part2_sku,
        total_amt_col=args.total_amt,
        part1_amt_col=args.part1_amt,
        part2_amt_col=args.part2_amt,
        rate_cols=rates,
    )

    print("\n".join(report_lines))
    if passed:
        print("\n🎉 All Quality & Sanity Gates PASSED.")
        sys.exit(0)
    else:
        print("\n💥 Sanity Gates FAILED.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
