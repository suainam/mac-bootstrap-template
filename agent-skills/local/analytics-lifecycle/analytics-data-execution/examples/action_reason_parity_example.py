"""同源判定、标记原因互斥闭环与原子交付范例 (Action-Reason Parity & Delivery Example).

本脚本使用纯 Python 标准库编写，零外部依赖、零凭据，展示商品与门店分析中的 5 大工程铁律：
1. 口径与字段同源单点取值：前置 Layer 1 清洗层从权威维表补齐下发属性，消除展示与判定双源割裂；
2. 一次动作判定、原因消费标记：动作标记（is_drop）计算一次，原因严格消费该标记，杜绝 is_drop=0 却标注剔除；
3. 正向收紧白名单判定：严禁 ELSE 兜底判定动作；业务保护标签绝对优先；
4. 明确区分 NULL/空白/未命中/0/负值：缺失销量与未知标签显式隔离为待核验，不伪装为 0 销量；0 与负数策略显式配置；
5. 临时产物验证后同名原子替换与软链接校验：杜绝产物另名生成导致用户在数据湖打开旧文件。
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
import tempfile
from typing import Any


def clean_and_enrich_records(
    raw_records: list[dict[str, Any]],
    master_dim: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Layer 1 前置清洗层：单点对齐权威主数据维表，补齐缺失属性，统一字段来源。"""
    cleaned: list[dict[str, Any]] = []
    for row in raw_records:
        item_id = str(row["item_id"]).strip()
        master_info = master_dim.get(item_id, {})

        # 优先使用权威维表属性补齐，展示与计算同源单点取值
        category = row.get("category")
        if category is None or not str(category).strip():
            category = master_info.get("category")

        # 提取销量与保护标记，严格保留原生类型或 None
        sales_qty = row.get("sales_qty")
        sales_amt = row.get("sales_amt")
        raw_prot = row.get("is_protected")
        is_protected = int(raw_prot) if raw_prot is not None and str(raw_prot).strip() != "" else None

        cleaned.append({
            "item_id": item_id,
            "category": str(category).strip() if category is not None and str(category).strip() else None,
            "sales_qty": sales_qty,
            "sales_amt": sales_amt,
            "is_protected": is_protected,
            "raw_source": row.get("raw_source", "raw_feed"),
        })
    return cleaned


def evaluate_action_and_reasons(
    records: list[dict[str, Any]],
    allow_negative_sales_return: bool = True,
) -> list[dict[str, Any]]:
    """核心判定层：单次正向判定动作标记，原因消费该标记，异常输入显式隔离。"""
    evaluated: list[dict[str, Any]] = []

    for row in records:
        item_id = row["item_id"]
        category = row["category"]
        sales_qty = row["sales_qty"]
        sales_amt = row["sales_amt"]
        is_protected = row["is_protected"]

        # 1. 业务保护标签绝对优先
        if is_protected == 1:
            evaluated.append({
                **row,
                "is_drop": 0,
                "action_status": "RETAIN",
                "drop_reason": None,
                "retain_reason": "protected_item",
            })
            continue

        # 2. 缺失值防卫：品类、销量或保护状态缺失时绝不判定剔除，显式标记待核验
        if category is None or sales_qty is None or is_protected is None:
            evaluated.append({
                **row,
                "is_drop": 0,
                "action_status": "PENDING_AUDIT",
                "drop_reason": None,
                "retain_reason": "missing_data_pending_audit",
            })
            continue

        # 3. 显式区分 0 销量与负数销量（退货冲减）
        is_zero_sales = (sales_qty == 0)
        is_negative_sales = (sales_qty < 0)

        # 4. 正向白名单交集判定：动作标记 is_drop 计算一次
        is_target_cat = (category == "target_category")
        matched_drop_criteria = False
        actual_drop_reason = None

        if is_target_cat and is_zero_sales:
            matched_drop_criteria = True
            actual_drop_reason = "target_cat_zero_sales"
        elif is_target_cat and is_negative_sales and allow_negative_sales_return:
            matched_drop_criteria = True
            actual_drop_reason = "target_cat_negative_sales_return"

        is_drop = 1 if matched_drop_criteria else 0

        # 5. 原因消费标记：标记与原因 100% 互斥闭环
        if is_drop == 1:
            drop_reason = actual_drop_reason
            retain_reason = None
            action_status = "DROP"
        else:
            drop_reason = None
            action_status = "RETAIN"
            if not is_target_cat:
                retain_reason = "non_target_category"
            elif is_negative_sales and not allow_negative_sales_return:
                retain_reason = "negative_sales_needs_manual_review"
            else:
                retain_reason = "active_sales"
        evaluated.append({
            **row,
            "is_drop": is_drop,
            "action_status": action_status,
            "drop_reason": drop_reason,
            "retain_reason": retain_reason,
        })
    return evaluated


def audit_evaluated_records(
    records: list[dict[str, Any]],
    expected_total_count: int,
) -> None:
    """对抗性质量门禁：核验主键唯一性、标记与原因互斥闭环、保护不穿透与集合守恒。"""
    seen_keys: set[str] = set()
    drop_count = 0
    retain_count = 0

    for idx, row in enumerate(records, start=1):
        item_id = row["item_id"]
        is_drop = row["is_drop"]
        drop_reason = row["drop_reason"]
        retain_reason = row["retain_reason"]
        is_protected = row["is_protected"]

        # 断言 1: 主键唯一性
        if item_id in seen_keys:
            raise AssertionError(f"第 {idx} 行主键重复: item_id={item_id}")
        seen_keys.add(item_id)

        # 断言 2: 标记与原因 100% 互斥闭环（核心铁律：防 389 行口径事故）
        if is_drop == 0 and drop_reason is not None:
            raise AssertionError(
                f"第 {idx} 行标记原因矛盾: is_drop=0 但 drop_reason='{drop_reason}'"
            )
        if is_drop == 1 and drop_reason is None:
            raise AssertionError(f"第 {idx} 行标记原因矛盾: is_drop=1 但 drop_reason 为空")
        if is_drop == 1 and retain_reason is not None:
            raise AssertionError(
                f"第 {idx} 行标记原因矛盾: is_drop=1 但 retain_reason='{retain_reason}'"
            )
        if is_drop == 0 and retain_reason is None:
            raise AssertionError(f"第 {idx} 行标记原因矛盾: is_drop=0 但 retain_reason 为空")

        # 断言 3: 业务保护绝对不穿透
        if is_protected == 1 and is_drop == 1:
            raise AssertionError(f"第 {idx} 行业务保护标签被穿透: item_id={item_id} 被标记剔除")

        if is_drop == 1:
            drop_count += 1
        else:
            retain_count += 1

    # 断言 4: 主键集合与行数守恒
    if drop_count + retain_count != expected_total_count:
        raise AssertionError(
            f"集合不守恒: 剔除({drop_count}) + 保留({retain_count}) != 预期总数({expected_total_count})"
        )


def atomic_publish_lake_asset(
    records: list[dict[str, Any]],
    target_lake_path: Path,
    symlink_path: Path,
) -> None:
    """安全物化与同名幂等覆盖：写入临时文件 -> 校验 -> 原子替换物理实体 -> 建立相对软链接。"""
    target_lake_path.parent.mkdir(parents=True, exist_ok=True)
    symlink_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. 写入同目录临时文件
    tmp_path = target_lake_path.with_suffix(".tmp")
    fieldnames = list(records[0].keys())
    with tmp_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    # 2. 回读校验临时文件有效性
    with tmp_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = list(csv.DictReader(fh))
        if len(reader) != len(records):
            tmp_path.unlink(missing_ok=True)
            raise AssertionError(f"临时文件行数校验失败: 写入 {len(records)}, 回读 {len(reader)}")

    # 3. 原子同名覆盖外部数据湖物理文件（保持稳定命名，禁止衍生 _v1/_v2）
    os.replace(tmp_path, target_lake_path)

    # 4. 更新/校验仓库入口相对软链接（严防将已有普通实体文件误当软链 unlink）
    rel_target = os.path.relpath(target_lake_path, symlink_path.parent)
    if symlink_path.is_symlink():
        symlink_path.unlink()
    elif symlink_path.exists():
        raise AssertionError(f"仓库入口已存在非软链的物理实体文件，禁止静默覆盖: {symlink_path}")

    symlink_path.symlink_to(rel_target)

    # 5. 回读验证软链接解析与实际物理文件一致性
    if not symlink_path.resolve().exists():
        raise AssertionError(f"软链接解析失败: {symlink_path} -> {rel_target}")
    if symlink_path.resolve() != target_lake_path.resolve():
        raise AssertionError("软链接解析目标与数据湖实际路径不一致")

def run_self_check() -> None:
    """可运行自检：覆盖异常分支、同名替换与软链接校验。"""
    print("▶ 正在执行同源判定与标记原因一致性自检...")

    master_dim = {
        "SKU_001": {"category": "target_category"},
        "SKU_002": {"category": "target_category"},
        "SKU_003": {"category": "target_category"},
        "SKU_004": {"category": "other_category"},
        "SKU_005": {"category": "target_category"},
        "SKU_006": {"category": "target_category"},
        "SKU_007": {"category": "target_category"},
        "SKU_008": {"category": "target_category"},
    }

    raw_data = [
        # 1. 正常剔除样本：目标品类、销量 0、非保护
        {"item_id": "SKU_001", "category": "", "sales_qty": 0, "sales_amt": 0.0, "is_protected": 0},
        # 2. 正常保留样本：目标品类、有销量
        {"item_id": "SKU_002", "category": "target_category", "sales_qty": 15, "sales_amt": 150.0, "is_protected": 0},
        # 3. 业务保护样本：销量 0 但受保护，绝对不被剔除
        {"item_id": "SKU_003", "category": "target_category", "sales_qty": 0, "sales_amt": 0.0, "is_protected": 1},
        # 4. 非目标品类样本：销量 0 但品类不匹配，保留
        {"item_id": "SKU_004", "category": "other_category", "sales_qty": 0, "sales_amt": 0.0, "is_protected": 0},
        # 5. NULL 销量异常：待核验，绝不能误补 0 剔除
        {"item_id": "SKU_005", "category": "target_category", "sales_qty": None, "sales_amt": None, "is_protected": 0},
        # 6. 空白标签且维表未命中：待核验，保留
        {"item_id": "SKU_006", "category": "   ", "sales_qty": 0, "sales_amt": 0.0, "is_protected": 0},
        # 7. 负销量样本（退货冲减）：显式策略保留待人工核实
        {"item_id": "SKU_007", "category": "target_category", "sales_qty": -2, "sales_amt": -20.0, "is_protected": 0},
        # 8. 属性下发表缺失、维表成功补齐后满足剔除
        {"item_id": "SKU_008", "category": None, "sales_qty": 0, "sales_amt": 0.0, "is_protected": 0},
    ]
    # 清洗掉 SKU_006 在维表中的分类以测试未命中
    del master_dim["SKU_006"]["category"]

    # 1. 前置清洗
    cleaned = clean_and_enrich_records(raw_data, master_dim)
    assert len(cleaned) == 8, "清洗行数必须守恒"

    # 2. 判定与原因派生 (默认不将负销冲减自动视为无销，需显式人工审核)
    evaluated = evaluate_action_and_reasons(cleaned, allow_negative_sales_return=False)
    assert len(evaluated) == 8, "判定行数必须守恒"

    # 3. 门禁审计
    audit_evaluated_records(evaluated, expected_total_count=8)

    # 验证各项判定事实
    by_id = {r["item_id"]: r for r in evaluated}
    assert by_id["SKU_001"]["is_drop"] == 1 and by_id["SKU_001"]["drop_reason"] == "target_cat_zero_sales"
    assert by_id["SKU_002"]["is_drop"] == 0 and by_id["SKU_002"]["retain_reason"] == "active_sales"
    assert by_id["SKU_003"]["is_drop"] == 0 and by_id["SKU_003"]["retain_reason"] == "protected_item"
    assert by_id["SKU_004"]["is_drop"] == 0 and by_id["SKU_004"]["retain_reason"] == "non_target_category"
    assert by_id["SKU_005"]["is_drop"] == 0 and by_id["SKU_005"]["action_status"] == "PENDING_AUDIT"
    assert by_id["SKU_006"]["is_drop"] == 0 and by_id["SKU_006"]["action_status"] == "PENDING_AUDIT"
    assert by_id["SKU_007"]["is_drop"] == 0 and by_id["SKU_007"]["retain_reason"] == "negative_sales_needs_manual_review"
    assert by_id["SKU_008"]["is_drop"] == 1 and by_id["SKU_008"]["drop_reason"] == "target_cat_zero_sales"
    print("  ✓ 正常判定、保护优先级与未知输入隔离断言通过")

    # 4. 人为注入标记与原因不一致故障，断言必须捕获
    inconsistent_records = [dict(r) for r in evaluated]
    inconsistent_records[0]["is_drop"] = 0
    inconsistent_records[0]["drop_reason"] = "target_cat_zero_sales"  # 模拟 389 行错误
    try:
        audit_evaluated_records(inconsistent_records, expected_total_count=8)
        raise RuntimeError("门禁未能拦截标记与原因不一致故障！")
    except AssertionError as err:
        print(f"  ✓ 门禁成功拦截标记与原因矛盾故障: {err}")

    # 5. 原子发布同名替换与软链接校验
    with tempfile.TemporaryDirectory() as tmpdir:
        lake_dir = Path(tmpdir) / "data_lake" / "topics" / "topic_demo"
        repo_outputs_dir = Path(tmpdir) / "repo" / "topics" / "topic_demo" / "04_outputs"
        target_lake_file = lake_dir / "catalog_evaluation_result.csv"
        repo_symlink_file = repo_outputs_dir / "catalog_evaluation_result.csv"

        # 首次物化
        atomic_publish_lake_asset(evaluated, target_lake_file, repo_symlink_file)
        assert target_lake_file.exists() and repo_symlink_file.is_symlink()
        first_mtime = target_lake_file.stat().st_mtime_ns

        # 二次同名幂等覆盖
        atomic_publish_lake_asset(evaluated, target_lake_file, repo_symlink_file)
        assert target_lake_file.exists() and repo_symlink_file.is_symlink()
        assert repo_symlink_file.resolve() == target_lake_file.resolve()
        print("  ✓ 外部数据湖同名幂等原子覆盖与仓库软链接校验通过")

    print("✅ 全部自检用例顺利通过！")


if __name__ == "__main__":
    run_self_check()
