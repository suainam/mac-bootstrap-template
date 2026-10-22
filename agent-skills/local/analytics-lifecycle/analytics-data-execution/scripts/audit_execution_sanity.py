#!/usr/bin/env python3
"""通用数据执行质检与对抗性核验脚本 (Universal Execution Sanity Gate CLI).

两种模式：

A. 八格新旧对比模式 (eight-cell, 推荐用于缩铺/扩铺/组货目录变更)
  输入为长表，每行一个 (version, store_code, item_code) 实体：
    version         old / new / 可选 forecast
    store_code      门店编码
    item_code       商品编码
    amount          历史金额（有符号，可为负；不得为 NaN/Inf）
    in_catalog      0/1 是否在有效目录内
    fixed_active    0/1 是否固定在营（与 in_catalog 独立，目录外固定在营合法）
    group_code      外层分组标签（每个实体跨版本不可变）
    pure_target     0/1 旧版本行是否纯目标来源
    new_target_hit  0/1 新版本行是否命中新目标来源
    source          可选多来源集合，token 属于 {target, non_target}，以 ';' 或 ',' 分隔
    可选 expected_new 0/1（业务给定的新增预测，须与推导一致）

  八格 = version × in_catalog × fixed_active（共 8 格，外层 group 为分组）。
  核验项：
    1. 复合主键 (version, store_code, item_code) 唯一；
    2. old / new 门店×商品全集完全一致（同一店品全集）；
    3. 状态合法：in_catalog / fixed_active / pure_target / new_target_hit ∈ {0,1}，
       提供 source 时 token 合法且非空；
    4. 八格明细按分组完整输出行数与有符号金额；空格计数为 0 且不伪造
       （--strict-cells 时空格直接失败）；
    5. 历史金额按 (store_code, item_code) 跨版本守恒（容差默认 0.05）；
    6. 非目标来源保留：old 目录内且 source 含 non_target 的实体在 new 中必须仍在目录内，
       固定在营与金额一致（未提供 source 时跳过）；
    7. 旧目录内实体必须在 new 中存在；
    8. 预测与实绩分离：expected_new = (old_in_catalog AND NOT pure_target) OR new_target_hit，
       必须等于 new.in_catalog；forecast 版本独立核验（主键唯一、状态合法、是 new 的子集，
       金额独立不参与历史守恒），不参与 old-new 对比；
    9. 目录增删恒等式：new_catalog - old_catalog == added - removed（只按 in_catalog）；
    10. 分组标签跨版本一致，分组有符号金额守恒。

B. 旧版二元守恒模式 (legacy, 保持向后兼容)
   python audit_execution_sanity.py --data dataset.parquet --id-col 门店编码 \
     --total-sku 全店总在营商品数 --part1-sku 目录内在营商品数 --part2-sku 目录外手工在营商品数 \
     --total-amt 全店总销售额_元 --part1-amt 目录内销售额_元 --part2-amt 目录外手工销售额_元

用法（八格模式）：
  python audit_execution_sanity.py --data eight_cell.csv \
    --id-cols version,store_code,item_code --amount-col amount \
    --state-col in_catalog --fixed-active-col fixed_active --source-col source \
    --old-version old --new-version new [--forecast-version forecast] \
    [--strict-cells] [--json]

支持 .csv / .jsonl / .parquet / .xlsx（后两者需要 pandas）。
缺列、非法状态、未知来源 token、NaN 金额、重复主键、全集缺失均以退出码 1 明确失败。
"""

from __future__ import annotations
import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

# 同级模块导入：脚本既可直接运行，也可被测试按路径加载，因此把自身目录
# 放进 sys.path 再导入，避免依赖调用方的工作目录或包结构。
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

# --------------------------------------------------------------------------
# 共享输入协议与八格核验
# --------------------------------------------------------------------------
#
# 实现在同级模块里：sanity_gate_common 负责输入加载与字段解析，
# eight_cell_audit 负责八格核验。本文件只保留 legacy 断言与 CLI 编排。

from eight_cell_audit import run_eight_cell_audit  # noqa: E402
from sanity_gate_common import (  # noqa: E402
    DEFAULT_AMOUNT_TOLERANCE,
    AuditInputError,
    _format_sample,
    _parse_amount,
    _parse_flag,
    _parse_key_text,
    _parse_source,
    load_records,
)

# --------------------------------------------------------------------------
# 旧版二元守恒模式（保持向后兼容）
# --------------------------------------------------------------------------


def run_sanity_audit(
    df: Any,
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
    """执行通用数据质量与单调性守恒检查（legacy 模式）."""
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
        logs.append(
            f"• SKU 数量互斥守恒检验: MAX(|{part1_sku_col} + {part2_sku_col} - {total_sku_col}|) = {sku_diff}"
        )
        if sku_diff == 0:
            logs.append("  ✅ SKU 数量二元互斥守恒成立")
        else:
            errors.append(f"❌ SKU 数量不守恒，最大差额: {sku_diff}")

    # 2. 金额全额流水自洽守恒
    if total_amt_col and part1_amt_col and part2_amt_col:
        amt_diff = (df[part1_amt_col] + df[part2_amt_col] - df[total_amt_col]).abs().max()
        logs.append(
            f"• 销售金额自洽守恒检验: MAX(|{part1_amt_col} + {part2_amt_col} - {total_amt_col}|) = {amt_diff:.4f} 元"
        )
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
                        errors.append(
                            f"❌ 比率指标 {r_col} 超出 [0, 100%] 区间! 范围: [{min_v}, {max_v}]"
                        )
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
                        errors.append(
                            f"❌ 发现 {bad_not_null} 条当 {cond_col}=0 时 {guard_col} 被强刷成了非空数值!"
                        )
                    else:
                        logs.append(f"  ✅ 当 {cond_col}=0 时 {guard_col} 严格保留为 NULL 语义")

    is_passed = len(errors) == 0
    return is_passed, logs + errors


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _split_columns(raw: str | None) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()] if raw else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Universal Data Execution Sanity Gate (eight-cell + legacy modes)"
    )
    parser.add_argument("--data", required=True, help="Path to csv/jsonl/parquet/xlsx file")
    # 八格模式
    parser.add_argument("--id-cols", help="Comma-separated composite key: version,store_code,item_code")
    parser.add_argument("--amount-col", help="Signed historical amount column")
    parser.add_argument("--state-col", help="0/1 in_catalog column")
    parser.add_argument("--fixed-active-col", help="0/1 fixed_active column")
    parser.add_argument("--group-col", help="Group label column (required in eight-cell mode)")
    parser.add_argument("--pure-target-col", help="0/1 old-row pure target column")
    parser.add_argument("--new-target-hit-col", help="0/1 new-row target hit column")
    parser.add_argument("--source-col", help="Optional multi-source token column (target;non_target)")
    parser.add_argument("--expected-new-col", help="Optional 0/1 expected_new column")
    parser.add_argument("--old-version", help="Old version label (default: first sorted version)")
    parser.add_argument("--new-version", help="New version label (default: second sorted version)")
    parser.add_argument("--forecast-version", help="Optional forecast version, audited separately")
    parser.add_argument("--amount-tolerance", type=float, default=DEFAULT_AMOUNT_TOLERANCE)
    parser.add_argument("--strict-cells", action="store_true", help="Empty eight-cell group fails")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON report")
    # legacy 模式
    parser.add_argument("--id-col", help="[legacy] Primary entity key column name")
    parser.add_argument("--total-sku", help="[legacy] Total SKU column name")
    parser.add_argument("--part1-sku", help="[legacy] Catalog SKU column name")
    parser.add_argument("--part2-sku", help="[legacy] Manual SKU column name")
    parser.add_argument("--total-amt", help="[legacy] Total sales amount column name")
    parser.add_argument("--part1-amt", help="[legacy] Catalog sales amount column name")
    parser.add_argument("--part2-amt", help="[legacy] Manual sales amount column name")
    parser.add_argument("--rate-cols", help="[legacy] Comma-separated rate column names")
    args = parser.parse_args(argv)

    p = Path(args.data)
    if not p.exists():
        print(f"File not found: {p}", file=sys.stderr)
        return 1

    try:
        if args.id_cols:
            missing_flags = [
                flag
                for flag, value in (
                    ("--amount-col", args.amount_col),
                    ("--state-col", args.state_col),
                    ("--fixed-active-col", args.fixed_active_col),
                    ("--group-col", args.group_col),
                    ("--pure-target-col", args.pure_target_col),
                    ("--new-target-hit-col", args.new_target_hit_col),
                )
                if not value
            ]
            if missing_flags:
                raise AuditInputError(
                    f"八格模式缺少必需参数: {missing_flags}（需要 --amount-col/--state-col/"
                    f"--fixed-active-col/--group-col/--pure-target-col/--new-target-hit-col）"
                )
            records = load_records(p)
            passed, report_lines, summary = run_eight_cell_audit(
                records,
                id_cols=_split_columns(args.id_cols),
                amount_col=args.amount_col,
                state_col=args.state_col,
                fixed_active_col=args.fixed_active_col,
                group_col=args.group_col,
                pure_target_col=args.pure_target_col,
                new_target_hit_col=args.new_target_hit_col,
                source_col=args.source_col,
                old_version=args.old_version,
                new_version=args.new_version,
                forecast_version=args.forecast_version,
                expected_new_col=args.expected_new_col,
                amount_tolerance=args.amount_tolerance,
                strict_cells=args.strict_cells,
            )
            if args.json:
                print(json.dumps({"passed": passed, "summary": summary, "report": report_lines},
                                 ensure_ascii=False, indent=2))
            else:
                print("\n".join(report_lines))
        else:
            if not args.id_col:
                raise AuditInputError("legacy 模式需要 --id-col（或改用 --id-cols 进入八格模式）")
            try:
                import pandas as pd
            except ImportError as exc:  # pragma: no cover - 依赖环境
                raise AuditInputError("legacy 模式需要 pandas，请改用八格模式或安装 pandas") from exc
            df = pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_excel(p)
            rates = _split_columns(args.rate_cols) or None
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
    except AuditInputError as exc:
        print(f"❌ 输入协议错误: {exc}", file=sys.stderr)
        return 1

    if passed:
        print("\n🎉 All Quality & Sanity Gates PASSED.")
        return 0
    print("\n💥 Sanity Gates FAILED.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
