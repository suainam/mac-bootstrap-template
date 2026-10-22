"""Tests for the eight-cell catalog migration audit in audit_execution_sanity.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "agent-skills/local/analytics-lifecycle/analytics-data-execution/scripts/audit_execution_sanity.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_execution_sanity", SCRIPT)
    assert spec is not None
    loader = spec.loader
    assert loader is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


audit = _load_module()


def _row(
    version,
    store,
    item,
    amount,
    in_catalog,
    fixed_active,
    *,
    group="g1",
    pure_target=0,
    new_target_hit=0,
    source=None,
    expected_new=None,
):
    row = {
        "version": version,
        "store_code": store,
        "item_code": item,
        "amount": amount,
        "in_catalog": in_catalog,
        "fixed_active": fixed_active,
        "group_code": group,
        "pure_target": pure_target,
        "new_target_hit": new_target_hit,
    }
    if source is not None:
        row["source"] = source
    if expected_new is not None:
        row["expected_new"] = expected_new
    return row


def _run(rows, **kwargs):
    options = {
        "id_cols": ["version", "store_code", "item_code"],
        "amount_col": "amount",
        "state_col": "in_catalog",
        "fixed_active_col": "fixed_active",
        "group_col": "group_code",
        "pure_target_col": "pure_target",
        "new_target_hit_col": "new_target_hit",
        "old_version": "old",
        "new_version": "new",
    }
    options.update(kwargs)
    return audit.run_eight_cell_audit(rows, **options)


def _write_csv(tmp_path, rows):
    path = tmp_path / "eight_cell.csv"
    header = list(rows[0])
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join(str(row.get(column, "")) for column in header))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _cli_args(path):
    return [
        "--data",
        str(path),
        "--id-cols",
        "version,store_code,item_code",
        "--amount-col",
        "amount",
        "--state-col",
        "in_catalog",
        "--fixed-active-col",
        "fixed_active",
        "--group-col",
        "group_code",
        "--pure-target-col",
        "pure_target",
        "--new-target-hit-col",
        "new_target_hit",
        "--old-version",
        "old",
        "--new-version",
        "new",
    ]


def test_migration_passes_with_added_removed_retained_and_negative_rows():
    rows = [
        # pure target loses its hit: removed from catalog, entity retained
        _row("old", "s1", "i1", 100.0, 1, 0, pure_target=1),
        _row("new", "s1", "i1", 100.0, 0, 0),
        # non-target row stays in catalog without a target hit
        _row("old", "s1", "i2", 50.0, 1, 0, source="non_target"),
        _row("new", "s1", "i2", 50.0, 1, 0, source="non_target"),
        # new target hit outside the old catalog
        _row("old", "s1", "i3", 0.0, 0, 0),
        _row("new", "s1", "i3", 0.0, 1, 0, new_target_hit=1),
        # mixed source keeps catalog through the non-target branch, negative amount
        _row("old", "s1", "i4", -5.0, 1, 0, source="target;non_target"),
        _row("new", "s1", "i4", -5.0, 1, 0, source="target;non_target"),
        # fixed active outside the catalog, independent flag
        _row("old", "s1", "i5", 10.0, 0, 1),
        _row("new", "s1", "i5", 10.0, 0, 1),
    ]
    passed, report, summary = _run(rows)
    assert passed, "\n".join(report)
    assert summary["universe"] == 5
    assert summary["added"] == 1
    assert summary["removed"] == 1
    assert summary["amount_drifts"] == 0
    assert summary["cells"]["old"]["in_catalog=0,fixed_active=1"] == 1
    assert summary["group_cells"]["g1"]["new"]["in_catalog=1,fixed_active=0"] == {
        "rows": 3,
        "amount": 45.0,
    }


def test_non_target_row_losing_catalog_fails():
    rows = [
        _row("old", "s1", "i1", 10.0, 1, 0, source="non_target"),
        _row("new", "s1", "i1", 10.0, 0, 0, source="non_target"),
    ]
    passed, report, _ = _run(rows, source_col="source")
    assert not passed
    assert any("非目标来源未保留目录内" in line for line in report)


def test_non_target_outside_catalog_is_not_forced_into_catalog():
    rows = [
        _row("old", "s1", "i1", 10.0, 0, 1, source="non_target"),
        _row("new", "s1", "i1", 10.0, 0, 1, source="non_target"),
    ]
    passed, report, _ = _run(rows, source_col="source")
    assert passed, "\n".join(report)


def test_amount_drift_fails():
    rows = [
        _row("old", "s1", "i1", 100.0, 1, 0, pure_target=1),
        _row("new", "s1", "i1", 100.5, 1, 0, new_target_hit=1),
    ]
    passed, report, _ = _run(rows)
    assert not passed
    assert any("金额跨版本不守恒" in line for line in report)


def test_old_catalog_row_missing_from_new_fails():
    rows = [
        _row("old", "s1", "i1", 10.0, 1, 0),
        _row("old", "s1", "i2", 10.0, 1, 0),
        _row("new", "s1", "i1", 10.0, 1, 0),
    ]
    passed, report, _ = _run(rows)
    assert not passed
    assert any("在 new 中缺失" in line for line in report)


def test_duplicate_composite_key_fails():
    rows = [
        _row("old", "s1", "i1", 10.0, 1, 0),
        _row("old", "s1", "i1", 10.0, 1, 0),
        _row("new", "s1", "i1", 10.0, 1, 0),
    ]
    passed, report, _ = _run(rows)
    assert not passed
    assert any("复合主键" in line for line in report)


def test_missing_required_column_raises():
    rows = [{"version": "old", "store_code": "s1", "item_code": "i1"}]
    with pytest.raises(audit.AuditInputError):
        _run(rows)


def test_nan_amount_raises():
    rows = [
        _row("old", "s1", "i1", float("nan"), 1, 0),
        _row("new", "s1", "i1", float("nan"), 1, 0),
    ]
    with pytest.raises(audit.AuditInputError):
        _run(rows)


def test_unknown_source_token_raises():
    rows = [
        _row("old", "s1", "i1", 1.0, 1, 0, source="promo"),
        _row("new", "s1", "i1", 1.0, 1, 0, source="promo"),
    ]
    with pytest.raises(audit.AuditInputError):
        _run(rows, source_col="source")


def test_group_label_drift_fails():
    rows = [
        _row("old", "s1", "i1", 1.0, 1, 0, group="g1"),
        _row("new", "s1", "i1", 1.0, 1, 0, group="g2"),
    ]
    passed, report, _ = _run(rows)
    assert not passed
    assert any("分组标签跨版本漂移" in line for line in report)


def test_group_amount_drift_fails_when_entities_move_between_groups():
    rows = [
        _row("old", "s1", "i1", 10.0, 1, 0, group="g1"),
        _row("new", "s1", "i1", 10.0, 1, 0, group="g1"),
        _row("old", "s1", "i2", 30.0, 1, 0, group="g1"),
        _row("new", "s1", "i2", 30.0, 1, 0, group="g2"),
    ]
    passed, _report, summary = _run(rows)
    assert not passed
    assert summary["group_mismatch"] == 1


def test_expected_new_mismatch_fails():
    rows = [
        _row("old", "s1", "i1", 1.0, 1, 0),
        _row("new", "s1", "i1", 1.0, 0, 0),
    ]
    passed, report, _ = _run(rows)
    assert not passed
    assert any("预测与实绩不一致" in line for line in report)


def test_supplied_expected_new_must_match_derivation():
    rows = [
        _row("old", "s1", "i1", 1.0, 0, 0, expected_new=0),
        _row("new", "s1", "i1", 1.0, 1, 0, new_target_hit=1),
    ]
    passed, report, _ = _run(rows, expected_new_col="expected_new")
    assert not passed
    assert any("given=0" in line for line in report)


def test_forecast_must_be_subset_of_new():
    rows = [
        _row("old", "s1", "i1", 1.0, 1, 0),
        _row("new", "s1", "i1", 1.0, 1, 0),
        _row("forecast", "s1", "i2", 3.0, 1, 0),
    ]
    passed, report, summary = _run(rows, forecast_version="forecast")
    assert not passed
    assert summary["forecast"]["keys_outside_new"] == 1
    assert any("不在 new 全集中" in line for line in report)


def test_empty_cell_is_reported_and_only_fails_in_strict_mode():
    rows = [
        _row("old", "s1", "i1", 1.0, 1, 0),
        _row("new", "s1", "i1", 1.0, 1, 0),
    ]
    passed, report, summary = _run(rows)
    assert passed, "\n".join(report)
    assert summary["cells"]["old"]["in_catalog=0,fixed_active=0"] == 0

    passed_strict, report_strict, _ = _run(rows, strict_cells=True)
    assert not passed_strict
    assert any("八格存在空格" in line for line in report_strict)


def test_cli_emits_json_and_exit_code(tmp_path):
    rows = [
        _row("old", "s1", "i1", 1.0, 1, 0),
        _row("new", "s1", "i1", 1.0, 1, 0),
    ]
    path = _write_csv(tmp_path, rows)
    assert audit.main(_cli_args(path) + ["--json"]) == 0


def test_cli_requires_group_and_three_boolean_columns(tmp_path):
    rows = [
        _row("old", "s1", "i1", 1.0, 1, 0),
        _row("new", "s1", "i1", 1.0, 1, 0),
    ]
    path = _write_csv(tmp_path, rows)
    args = _cli_args(path)
    index = args.index("--group-col")
    assert audit.main(args[:index] + args[index + 2 :]) == 1


def test_cli_rejects_illegal_flag_value(tmp_path):
    rows = [
        _row("old", "s1", "i1", 1.0, 2, 0),
        _row("new", "s1", "i1", 1.0, 1, 0),
    ]
    path = _write_csv(tmp_path, rows)
    assert audit.main(_cli_args(path)) == 1
