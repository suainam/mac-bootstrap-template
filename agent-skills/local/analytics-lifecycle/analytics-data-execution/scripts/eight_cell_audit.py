"""Catalog state-transition matrix audit for old/new catalog versions.

Crosses old/new catalog, in/out of catalog, and operating status so every
store-item row lands in exactly one cell. Historical amounts are signed and
conserved across versions; only non-operating additions may carry a separately
labelled estimate. Protocol and cell definitions live in
`analytics-demand-analysis/references/EIGHT_CELL_AUDIT_REFERENCE.md`.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sanity_gate_common import (
    DEFAULT_AMOUNT_TOLERANCE,
    AuditInputError,
    _format_sample,
    _parse_amount,
    _parse_flag,
    _parse_key_text,
    _parse_source,
)


def run_eight_cell_audit(
    records: list[dict[str, Any]],
    *,
    id_cols: list[str],
    amount_col: str,
    state_col: str,
    fixed_active_col: str,
    group_col: str,
    pure_target_col: str,
    new_target_hit_col: str,
    source_col: str | None = None,
    old_version: str | None = None,
    new_version: str | None = None,
    forecast_version: str | None = None,
    expected_new_col: str | None = None,
    amount_tolerance: float = DEFAULT_AMOUNT_TOLERANCE,
    strict_cells: bool = False,
) -> tuple[bool, list[str], dict[str, Any]]:
    """执行八格新旧对比核验，返回 (是否通过, 报告行, 结构化结果)."""
    errors: list[str] = []
    logs: list[str] = []

    if len(id_cols) != 3:
        raise AuditInputError(
            f"八格模式要求 --id-cols 为 version,store_code,item_code 三列，收到 {id_cols}"
        )
    version_col, store_col, item_col = id_cols
    required = [
        version_col,
        store_col,
        item_col,
        amount_col,
        state_col,
        fixed_active_col,
        group_col,
        pure_target_col,
        new_target_hit_col,
    ]
    if source_col:
        required.append(source_col)
    if expected_new_col:
        required.append(expected_new_col)
    if not records:
        raise AuditInputError("输入数据为空（0 行），无法核验")

    header = set(records[0].keys())
    missing = [column for column in required if column not in header]
    if missing:
        raise AuditInputError(
            f"缺少必需列: {missing}；实际列为 {sorted(header)}"
        )

    # ---- 解析与逐行协议校验 ----
    rows: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=2):  # 表头占第 1 行
        version = _parse_key_text(record.get(version_col), version_col, index)
        store = _parse_key_text(record.get(store_col), store_col, index)
        item = _parse_key_text(record.get(item_col), item_col, index)
        row = {
            "version": version,
            "store": store,
            "item": item,
            "key": (store, item),
            "amount": _parse_amount(record.get(amount_col), amount_col, index),
            "in_catalog": _parse_flag(record.get(state_col), state_col, index),
            "fixed_active": _parse_flag(record.get(fixed_active_col), fixed_active_col, index),
            "group": _parse_key_text(record.get(group_col), group_col, index),
            "pure_target": _parse_flag(record.get(pure_target_col), pure_target_col, index),
            "new_target_hit": _parse_flag(
                record.get(new_target_hit_col), new_target_hit_col, index
            ),
            "source": (
                _parse_source(record.get(source_col), index) if source_col else None
            ),
            "expected_new": None,
        }
        if expected_new_col:
            raw_expected = record.get(expected_new_col)
            if raw_expected is not None and str(raw_expected).strip() != "":
                row["expected_new"] = _parse_flag(
                    raw_expected, expected_new_col, index
                )
        rows.append(row)

    versions = sorted({row["version"] for row in rows})
    if old_version is None or new_version is None:
        if len(versions) < 2:
            raise AuditInputError(f"仅存在版本 {versions}，无法进行新旧对比")
        old_version, new_version = versions[0], versions[1]
    if old_version == new_version:
        raise AuditInputError(f"old/new 版本不得相同: {old_version}")
    if old_version not in versions:
        raise AuditInputError(f"old 版本 {old_version!r} 不在数据中，实际版本 {versions}")
    if new_version not in versions:
        raise AuditInputError(f"new 版本 {new_version!r} 不在数据中，实际版本 {versions}")
    allowed_versions = {old_version, new_version}
    if forecast_version:
        if forecast_version not in versions:
            raise AuditInputError(
                f"forecast 版本 {forecast_version!r} 不在数据中，实际版本 {versions}"
            )
        allowed_versions.add(forecast_version)
    unexpected = sorted(set(versions) - allowed_versions)
    if unexpected:
        errors.append(f"❌ 存在未声明版本 {unexpected}，禁止混入新旧对比")

    logs.append(f"• 版本集合: {versions}（old={old_version}, new={new_version}"
                + (f", forecast={forecast_version}" if forecast_version else "")
                + "）")

    # ---- 1. 复合主键唯一性 ----
    seen: Counter[tuple[str, str, str]] = Counter()
    for row in rows:
        seen[(row["version"], row["store"], row["item"])] += 1
    duplicates = [key for key, count in seen.items() if count > 1]
    if duplicates:
        errors.append(
            f"❌ 复合主键 (version, store_code, item_code) 重复 {len(duplicates)} 组: "
            f"{_format_sample(duplicates)}"
        )
    else:
        logs.append("✅ 复合主键唯一: (version, store_code, item_code) 无重复")

    # ---- 2. 八格明细（按分组，行数与有符号金额）----
    cell_stats: dict[tuple[str, str, int, int], list[float]] = {}
    groups = sorted({row["group"] for row in rows})
    for row in rows:
        cell = (row["group"], row["version"], row["in_catalog"], row["fixed_active"])
        stats = cell_stats.setdefault(cell, [0.0, 0.0])
        stats[0] += 1
        stats[1] += row["amount"]

    logs.append("• 八格明细（分组 × version × in_catalog × fixed_active）:")
    cells: dict[str, dict[str, int]] = {}
    group_cells: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    for version in versions:
        version_cells: dict[str, int] = {}
        for state in (0, 1):
            for fixed in (0, 1):
                label = f"in_catalog={state},fixed_active={fixed}"
                count = sum(
                    cell_stats.get((group_name, version, state, fixed), [0.0, 0.0])[0]
                    for group_name in groups
                )
                version_cells[label] = int(count)
                if count == 0 and strict_cells:
                    errors.append(
                        f"❌ 八格存在空格: {version} | {label} 行数为 0（--strict-cells）"
                    )
        cells[version] = version_cells
        for group in groups:
            group_version: dict[str, dict[str, float]] = {}
            for state in (0, 1):
                for fixed in (0, 1):
                    label = f"in_catalog={state},fixed_active={fixed}"
                    count, amount = cell_stats.get((group, version, state, fixed), [0.0, 0.0])
                    group_version[label] = {
                        "rows": int(count),
                        "amount": round(amount, 2),
                    }
                    if count == 0 and strict_cells:
                        errors.append(
                            f"❌ 分组八格存在空格: {group} | {version} | {label} 行数为 0"
                            "（--strict-cells）"
                        )
                    logs.append(
                        f"  - {group} | {version} | {label} | 行数={int(count)} | 金额={amount:.2f}"
                    )
            group_cells.setdefault(group, {})[version] = group_version
    if not strict_cells:
        logs.append("  （空格保留为 0，不伪造数据；--strict-cells 可将空格升级为失败）")

    # ---- 3. 版本分组与全集一致性 ----
    by_version: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for row in rows:
        by_version.setdefault(row["version"], {})[row["key"]] = row

    old_rows = by_version.get(old_version, {})
    new_rows = by_version.get(new_version, {})
    if not old_rows:
        errors.append(f"❌ old 版本 {old_version} 无数据行")
    if not new_rows:
        errors.append(f"❌ new 版本 {new_version} 无数据行")

    old_universe = set(old_rows)
    new_universe = set(new_rows)
    missing_in_new = sorted(old_universe - new_universe)
    missing_in_old = sorted(new_universe - old_universe)
    if missing_in_new:
        errors.append(
            f"❌ {len(missing_in_new)} 个店品在 new 中缺失: {_format_sample(missing_in_new)}"
        )
    if missing_in_old:
        errors.append(
            f"❌ {len(missing_in_old)} 个店品在 old 中缺失: {_format_sample(missing_in_old)}"
        )
    if not missing_in_new and not missing_in_old:
        logs.append(f"✅ 店品全集一致: {len(old_universe)} 个 (store_code, item_code)")

    # ---- 4. 历史金额按实体跨版本守恒 ----
    amount_drifts = []
    for key in sorted(old_universe & new_universe):
        drift = abs(new_rows[key]["amount"] - old_rows[key]["amount"])
        if drift > amount_tolerance:
            amount_drifts.append((key, old_rows[key]["amount"], new_rows[key]["amount"], drift))
    if amount_drifts:
        errors.append(
            f"❌ 历史金额跨版本不守恒 {len(amount_drifts)} 组（容差 {amount_tolerance}）: "
            f"{_format_sample([f'{k[0]}/{k[1]} old={o} new={n} drift={d:.4f}' for k, o, n, d in amount_drifts])}"
        )
    else:
        logs.append(f"✅ 历史金额跨版本守恒: 容差 {amount_tolerance} 内全部通过")

    # ---- 5. 非目标来源保留（未提供 source 列时跳过）----
    non_target_broken = []
    for key, old_row in sorted(old_rows.items()):
        if old_row["source"] is None or "non_target" not in old_row["source"]:
            continue
        if old_row["in_catalog"] != 1:
            continue
        new_row = new_rows.get(key)
        if new_row is None:
            non_target_broken.append((key, "new 缺失"))
            continue
        if new_row["in_catalog"] != 1:
            non_target_broken.append((key, "new 未保留目录内"))
            continue
        if (
            new_row["fixed_active"] != old_row["fixed_active"]
            or abs(new_row["amount"] - old_row["amount"]) > amount_tolerance
        ):
            non_target_broken.append(
                (
                    key,
                    (
                        f"fixed_active {old_row['fixed_active']}->{new_row['fixed_active']}, "
                        f"amount {old_row['amount']}->{new_row['amount']}"
                    ),
                )
            )
    if source_col is None:
        logs.append("• 未提供 source 列，跳过非目标来源保留核验")
    elif non_target_broken:
        errors.append(
            f"❌ 非目标来源未保留目录内 {len(non_target_broken)} 组: "
            f"{_format_sample(non_target_broken)}"
        )
    else:
        logs.append("✅ 非目标来源全部保留在目录内（金额与在营标记一致）")

    # ---- 6. 旧目录内实体必须在 new 中存在 ----
    old_catalog = {key for key, row in old_rows.items() if row["in_catalog"] == 1}
    lost_catalog = sorted(old_catalog - new_universe)
    if lost_catalog:
        errors.append(
            f"❌ {len(lost_catalog)} 个旧目录内店品在 new 中不存在: {_format_sample(lost_catalog)}"
        )
    else:
        logs.append(f"✅ 旧目录内实体全部存在: {len(old_catalog)} 个")

    # ---- 7. 预测与实绩分离：expected_new 推导核对 ----
    expectation_mismatch = []
    expectation_checked = 0
    for key in sorted(old_universe & new_universe):
        old_row = old_rows[key]
        new_row = new_rows[key]
        old_in_catalog = old_row["in_catalog"] == 1
        pure_target = old_row["pure_target"] == 1
        new_target_hit = new_row["new_target_hit"] == 1
        derived = int((old_in_catalog and not pure_target) or new_target_hit)
        actual = new_row["in_catalog"]
        expectation_checked += 1
        if derived != actual:
            expectation_mismatch.append((key, derived, actual))
        supplied = old_row["expected_new"]
        if supplied is not None and supplied != derived:
            expectation_mismatch.append((key, f"given={supplied}", f"derived={derived}"))
    if expectation_mismatch:
        errors.append(
            f"❌ 预测与实绩不一致 {len(expectation_mismatch)} 组 "
            f"(expected_new 应为 (old_in_catalog AND NOT pure_target) OR new_target_hit): "
            f"{_format_sample(expectation_mismatch)}"
        )
    else:
        logs.append(f"✅ 预测与实绩一致: {expectation_checked} 个店品通过 expected_new 核对")

    # ---- 8. 目录增删恒等式（只按 in_catalog，fixed_active 不参与）----
    old_catalog = {key for key, row in old_rows.items() if row["in_catalog"] == 1}
    new_catalog = {key for key, row in new_rows.items() if row["in_catalog"] == 1}
    added = new_catalog - old_catalog
    removed = old_catalog - new_catalog
    identity_lhs = len(new_catalog) - len(old_catalog)
    identity_rhs = len(added) - len(removed)
    if identity_lhs != identity_rhs:
        errors.append(
            f"❌ 目录增删恒等式不成立: new_catalog-old_catalog={identity_lhs} != added-removed={identity_rhs}"
        )
    else:
        logs.append(
            f"✅ 目录增删恒等式成立: catalog {len(old_catalog)}->{len(new_catalog)} "
            f"(added={len(added)}, removed={len(removed)})"
        )

    # ---- 9. 分组标签与分组金额守恒 ----
    group_mismatch: list[tuple[str, str]] = []
    group_drift: list[tuple[str, float, float]] = []
    if group_col:
        for key in sorted(old_universe & new_universe):
            if old_rows[key]["group"] != new_rows[key]["group"]:
                group_mismatch.append(key)
        if group_mismatch:
            errors.append(
                f"❌ 分组标签跨版本漂移 {len(group_mismatch)} 组: {_format_sample(group_mismatch)}"
            )
        else:
            logs.append("✅ 分组标签跨版本一致")
        old_group_amount: dict[str, float] = {}
        new_group_amount: dict[str, float] = {}
        for row in old_rows.values():
            old_group_amount[row["group"]] = old_group_amount.get(row["group"], 0.0) + row["amount"]
        for row in new_rows.values():
            new_group_amount[row["group"]] = new_group_amount.get(row["group"], 0.0) + row["amount"]
        group_drift = [
            (group, old_group_amount.get(group, 0.0), new_group_amount.get(group, 0.0))
            for group in sorted(set(old_group_amount) | set(new_group_amount))
            if abs(old_group_amount.get(group, 0.0) - new_group_amount.get(group, 0.0))
            > amount_tolerance
        ]
        if group_drift:
            errors.append(
                f"❌ 分组金额守恒失败 {len(group_drift)} 组: "
                f"{_format_sample([f'{g} old={o:.2f} new={n:.2f}' for g, o, n in group_drift])}"
            )
        else:
            logs.append(f"✅ 分组金额守恒: {len(old_group_amount)} 个分组")

    # ---- 10. forecast 独立核验 ----
    forecast_summary: dict[str, Any] = {}
    if forecast_version:
        forecast_rows = by_version.get(forecast_version, {})
        forecast_keys = set(forecast_rows)
        outside_new = sorted(forecast_keys - new_universe)
        if outside_new:
            errors.append(
                f"❌ forecast 有 {len(outside_new)} 个店品不在 new 全集中: {_format_sample(outside_new)}"
            )
        else:
            logs.append(f"✅ forecast 是 new 的子集: {len(forecast_keys)} 个店品")
        forecast_summary = {
            "version": forecast_version,
            "rows": len(forecast_rows),
            "keys_outside_new": len(outside_new),
        }

    # ---- 11. 汇总 ----
    summary = {
        "mode": "eight_cell",
        "old_version": old_version,
        "new_version": new_version,
        "forecast_version": forecast_version,
        "rows": len(rows),
        "universe": len(old_universe),
        "cells": cells,
        "group_cells": group_cells,
        "added": len(added),
        "removed": len(removed),
        "old_catalog": len(old_catalog),
        "new_catalog": len(new_catalog),
        "amount_drifts": len(amount_drifts),
        "non_target_broken": len(non_target_broken),
        "expectation_checked": expectation_checked,
        "expectation_mismatch": len(expectation_mismatch),
        "group_mismatch": len(group_mismatch),
        "group_drift": len(group_drift),
        "forecast": forecast_summary,
    }
    return not errors, logs + errors, summary
