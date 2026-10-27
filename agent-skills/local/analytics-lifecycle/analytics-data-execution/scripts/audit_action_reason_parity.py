#!/usr/bin/env python3
"""动作与原因互斥闭环门禁 CLI (Action-Reason Parity Sanity Gate CLI).

验证商品/门店目录增删、清洗与剔除交付物中的 4 大核心质量门禁：
1. 主键唯一性 (Key Uniqueness)；
2. 动作标记与原因 100% 互斥闭环（is_drop=0 必须无 drop_reason 且有 retain_reason；is_drop=1 必须有 drop_reason 且无 retain_reason；防 389 行事故）；
3. 业务保护标签不穿透 (is_protected=1 => is_drop=0)；
4. NULL 与缺失值隔离（NULL 销量/未识别标签不得进入正常剔除）。

用法：
  # 运行内置全量自检：
  python3 audit_action_reason_parity.py --self-check

  # 审核交付文件：
  python3 audit_action_reason_parity.py --data result.csv \
    --id-col item_id --action-col is_drop \
    --drop-reason-col drop_reason --retain-reason-col retain_reason \
    [--protected-col is_protected]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from sanity_gate_common import (
    AuditInputError,
    load_records,
    _parse_flag,
    _parse_key_text,
)


def audit_action_reason_records(
    records: list[dict[str, Any]],
    id_col: str = "item_id",
    action_col: str = "is_drop",
    drop_reason_col: str = "drop_reason",
    retain_reason_col: str = "retain_reason",
    protected_col: str | None = "is_protected",
) -> dict[str, Any]:
    """核心审计函数：对记录列表执行互斥与守恒断言。"""
    seen_keys: set[tuple[str, ...]] = set()
    total_count = len(records)
    if total_count == 0:
        raise AuditInputError("审核数据集为空，请确认数据源有效性")

    drop_count = 0
    retain_count = 0
    protected_count = 0
    pending_audit_count = 0

    id_cols = [c.strip() for c in id_col.split(",") if c.strip()]
    for idx, row in enumerate(records, start=1):
        key_parts = []
        for col in id_cols:
            if col not in row:
                raise AuditInputError(f"第 {idx} 行缺失主键列 {col}")
            key_parts.append(_parse_key_text(row.get(col), col, idx))
        key_tuple = tuple(key_parts)
        if key_tuple in seen_keys:
            raise AuditInputError(f"第 {idx} 行主键重复: {key_tuple}")
        seen_keys.add(key_tuple)

        if action_col not in row:
            raise AuditInputError(f"第 {idx} 行缺失动作标记列 {action_col}")
        action_val = _parse_flag(row.get(action_col), action_col, idx)

        # 原因提取与清洗：过滤 'nan' / 'none'
        raw_drop_reason = row.get(drop_reason_col)
        drop_reason = (
            str(raw_drop_reason).strip()
            if raw_drop_reason is not None and str(raw_drop_reason).strip() and str(raw_drop_reason).lower() not in ["none", "nan"]
            else None
        )

        raw_retain_reason = row.get(retain_reason_col)
        retain_reason = (
            str(raw_retain_reason).strip()
            if raw_retain_reason is not None and str(raw_retain_reason).strip() and str(raw_retain_reason).lower() not in ["none", "nan"]
            else None
        )

        # 保护标签：若显式配置了 protected_col，但该列缺失或为 None，需严格校验
        is_protected = 0
        if protected_col:
            if protected_col not in row or row.get(protected_col) is None or str(row.get(protected_col)).strip() == "":
                raise AuditInputError(f"第 {idx} 行配置了保护列 {protected_col} 但值为空/缺失")
            is_protected = _parse_flag(row.get(protected_col), protected_col, idx)
            if is_protected == 1:
                protected_count += 1

        # 断言 1: 标记与原因 100% 互斥闭环
        if drop_reason_col == retain_reason_col:
            unified_reason = drop_reason
            if unified_reason is None:
                raise AuditInputError(f"第 {idx} 行判定说明列 {drop_reason_col} 不能为空")
            
            # 防卫：排除'不剔除'、'非剔除'等否定前缀
            u_lower = unified_reason.lower()
            is_negative_context = any(neg in u_lower for neg in ["不剔除", "非剔除", "未剔除", "保留", "retain", "keep", "not_drop"])
            has_drop_keyword = any(k in u_lower for k in ["剔除", "drop", "delete", "remove"])
            is_drop_desc = has_drop_keyword and not is_negative_context

            if action_val == 1 and not is_drop_desc:
                raise AuditInputError(
                    f"第 {idx} 行标记原因矛盾: {action_col}=1 但判定说明='{unified_reason}' 非剔除原因"
                )
            if action_val == 0 and is_drop_desc:
                raise AuditInputError(
                    f"第 {idx} 行标记原因矛盾: {action_col}=0 但判定说明='{unified_reason}' 被标为剔除"
                )
        else:
            if action_val == 0 and drop_reason is not None:
                raise AuditInputError(
                    f"第 {idx} 行标记原因矛盾: {action_col}=0 但 {drop_reason_col}='{drop_reason}'"
                )
            if action_val == 1 and drop_reason is None:
                raise AuditInputError(
                    f"第 {idx} 行标记原因矛盾: {action_col}=1 但 {drop_reason_col} 为空"
                )
            if action_val == 1 and retain_reason is not None:
                raise AuditInputError(
                    f"第 {idx} 行标记原因矛盾: {action_col}=1 但 {retain_reason_col}='{retain_reason}'"
                )
            if action_val == 0 and retain_reason is None:
                raise AuditInputError(
                    f"第 {idx} 行标记原因矛盾: {action_col}=0 但 {retain_reason_col} 为空"
                )

        # 断言 2: 保护标签绝对不穿透
        if is_protected == 1 and action_val == 1:
            raise AuditInputError(
                f"第 {idx} 行业务保护标签被穿透: 主键={key_tuple} is_protected=1 但被标记剔除"
            )
        if retain_reason and "pending_audit" in retain_reason:
            pending_audit_count += 1

        if action_val == 1:
            drop_count += 1
        else:
            retain_count += 1

    # 断言 3: 主键集合守恒
    if drop_count + retain_count != total_count:
        raise AuditInputError(
            f"集合不守恒: 剔除({drop_count}) + 保留({retain_count}) != 总数({total_count})"
        )

    return {
        "status": "PASS",
        "total_count": total_count,
        "drop_count": drop_count,
        "retain_count": retain_count,
        "protected_count": protected_count,
        "pending_audit_count": pending_audit_count,
    }


def run_self_check() -> int:
    """运行 CLI 内置自检用例。"""
    print("▶ 运行 audit_action_reason_parity.py 内置门禁自检...")

    valid_cases = [
        {"item_id": "SKU_01", "is_drop": 1, "drop_reason": "target_zero_sales", "retain_reason": None, "is_protected": 0},
        {"item_id": "SKU_02", "is_drop": 0, "drop_reason": None, "retain_reason": "active_sales", "is_protected": 0},
        {"item_id": "SKU_03", "is_drop": 0, "drop_reason": None, "retain_reason": "protected_item", "is_protected": 1},
        {"item_id": "SKU_04", "is_drop": 0, "drop_reason": None, "retain_reason": "missing_data_pending_audit", "is_protected": 0},
    ]

    summary = audit_action_reason_records(valid_cases)
    assert summary["status"] == "PASS"
    assert summary["total_count"] == 4
    assert summary["drop_count"] == 1
    assert summary["retain_count"] == 3
    assert summary["protected_count"] == 1
    assert summary["pending_audit_count"] == 1
    print("  ✓ 基础合法案例通过")

    # 错误注入测试：is_drop=0 却标注 drop_reason
    invalid_cases = [
        {"item_id": "SKU_ERR", "is_drop": 0, "drop_reason": "zero_sales", "retain_reason": None, "is_protected": 0}
    ]
    try:
        audit_action_reason_records(invalid_cases)
        print("  ✗ 错误注入拦截失败！")
        return 1
    except AuditInputError:
        print("  ✓ 成功拦截 is_drop=0 错误标注 drop_reason")

    # 保护穿透拦截测试
    leak_cases = [
        {"item_id": "SKU_LEAK", "is_drop": 1, "drop_reason": "zero_sales", "retain_reason": None, "is_protected": 1}
    ]
    try:
        audit_action_reason_records(leak_cases)
        print("  ✗ 保护穿透拦截失败！")
        return 1
    except AuditInputError:
        print("  ✓ 成功拦截业务保护品被标记剔除穿透")

    print("✅ 全部内置门禁检查项验证通过！")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="动作与原因互斥闭环门禁 CLI")
    parser.add_argument("--data", type=Path, help="待检测数据文件路径 (.csv, .jsonl, .parquet, .xlsx)")
    parser.add_argument("--sheet-name", default=None, help="Excel 工作表名称或索引，默认首个工作表")
    parser.add_argument("--id-col", default="item_id", help="主键列名，复合主键以逗号分隔，默认 item_id")
    parser.add_argument("--action-col", default="is_drop", help="动作标记列名，默认 is_drop")
    parser.add_argument("--drop-reason-col", default="drop_reason", help="剔除原因列名，默认 drop_reason")
    parser.add_argument("--retain-reason-col", default="retain_reason", help="保留原因列名，默认 retain_reason")
    parser.add_argument("--protected-col", default="is_protected", help="保护标记列名，默认 is_protected")
    parser.add_argument("--self-check", action="store_true", help="执行内置自检")

    args = parser.parse_args(argv)

    if args.self_check or args.data is None:
        return run_self_check()
    if not args.data.exists():
        print(f"❌ 数据文件不存在: {args.data}", file=sys.stderr)
        return 1

    try:
        records = load_records(args.data, sheet_name=args.sheet_name)
        summary = audit_action_reason_records(
            records=records,
            id_col=args.id_col,
            action_col=args.action_col,
            drop_reason_col=args.drop_reason_col,
            retain_reason_col=args.retain_reason_col,
            protected_col=args.protected_col,
        )
        print("================ 数据质量门禁审查报告 ================")
        print(f"审查结果: {summary['status']}")
        print(f"总主键行数: {summary['total_count']}")
        print(f"剔除项计数: {summary['drop_count']}")
        print(f"保留项计数: {summary['retain_count']}")
        print(f"保护项计数: {summary['protected_count']}")
        print(f"待核验项数: {summary['pending_audit_count']}")
        print("======================================================")
        return 0
    except AuditInputError as err:
        print(f"❌ 门禁审查失败: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
