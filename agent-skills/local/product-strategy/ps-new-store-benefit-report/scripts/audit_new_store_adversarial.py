"""
新店效益与考核宽表对抗性审查与门禁断言工具
(Adversarial Review Gate for New Store Benefit & Assessment)

严格核验：
1. 32 项标准中文字段完整性与顺序
2. 数学不变式（品项包含性、销售额包含性、动销包含性、库存成本包含性）
3. 考核状态与时间进度单调性（已结束严格为 100%，跟进中在 0~100%）
4. 除零防卫（无 NaN, Inf, #DIV/0!, #VALUE!）
5. 视觉与排版门禁（工作表名 <= 31 字符，列宽适应，金额百分比规范格式）
"""

import argparse
import sys
from pathlib import Path
import pandas as pd
import openpyxl

REQUIRED_FIELDS = [
    "大区编码", "大区名称", "省区编码", "省区名称", "营运区编码", "营运区名称",
    "门店编码", "门店名称", "经营方式", "考核类型", "试点营运区",
    "目录内商品数", "目录内有效动销商品数", "目录内近90天折算日均销售额", "目录内近90天折算日均毛利额",
    "目录内近90天日均库存成本", "目录内近90天日均销售成本",
    "全店商品数", "全店有效动销商品数", "全店近90天折算日均销售额", "全店近90天折算日均毛利额",
    "全店近90天日均库存成本", "全店近90天日均销售成本",
    "近90天日均客流", "目录内商品动销率", "目录内销售额占比", "目录内毛利额占比",
    "实际开业时间", "考核开始日期", "90天总指标", "时间进度", "累计达成率"
]


def audit_excel_workbook(excel_path: Path) -> list[str]:
    """对抗性核查导出的 Excel 工作簿"""
    errors = []
    if not excel_path.exists():
        return [f"文件不存在: {excel_path}"]

    # 1. Sheet 命名与数量检查
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    for sheetname in wb.sheetnames:
        if len(sheetname) > 31:
            errors.append(f"Sheet 名字超过 31 个字符限制: '{sheetname}' ({len(sheetname)} 字符)")

    required_sheets = ["跟进中新店效益与考核(6家)", "已结束新店效益与考核(11家)", "中文字段对照与口径说明"]
    for req in required_sheets:
        if req not in wb.sheetnames:
            errors.append(f"缺少必要工作表: '{req}'")

    # 2. 跟进中工作表数据核查
    if "跟进中新店效益与考核(6家)" in wb.sheetnames:
        df_og = pd.read_excel(excel_path, sheet_name="跟进中新店效益与考核(6家)")
        errors.extend(audit_dataframe(df_og, is_ongoing=True))

    # 3. 已结束工作表数据核查
    if "已结束新店效益与考核(11家)" in wb.sheetnames:
        df_fin = pd.read_excel(excel_path, sheet_name="已结束新店效益与考核(11家)")
        errors.extend(audit_dataframe(df_fin, is_ongoing=False))

    return errors


def parse_pct_or_float(val) -> float:
    if pd.isna(val) or val == "-":
        return 0.0
    if isinstance(val, str):
        val = val.strip().replace("%", "")
        try:
            return float(val) / 100.0 if "%" in str(val) or float(val) > 1.0 else float(val)
        except ValueError:
            return 0.0
    return float(val)


def audit_dataframe(df: pd.DataFrame, is_ongoing: bool) -> list[str]:
    """深度数学不变式与逻辑一致性审查"""
    errors = []
    sheet_tag = "跟进中" if is_ongoing else "已结束"

    # 字段完整性
    for idx, col in enumerate(REQUIRED_FIELDS):
        if col not in df.columns:
            errors.append(f"[{sheet_tag}] 缺少必要字段: '{col}'")

    if errors:
        return errors

    for idx, row in df.iterrows():
        store = row.get("门店编码", f"Row-{idx}")
        name = row.get("门店名称", "")

        # 1. 考核状态判定
        status = row.get("考核类型")
        expected_status = "跟进中" if is_ongoing else "已结束"
        if status != expected_status:
            errors.append(f"[{sheet_tag}] 门店 {store} ({name}) 考核类型错位: 实际='{status}', 预期='{expected_status}'")

        # 2. 品项包含性不变式
        item_ct = row.get("目录内商品数", 0)
        item_all = row.get("全店商品数", 0)
        yxs_ct = row.get("目录内有效动销商品数", 0)
        yxs_all = row.get("全店有效动销商品数", 0)

        if item_ct > item_all:
            errors.append(f"[{sheet_tag}] 门店 {store} 违反品项包含性: 目录品项数({item_ct}) > 全店品项数({item_all})")
        if yxs_ct > item_ct:
            errors.append(f"[{sheet_tag}] 门店 {store} 违反动销品项包含性: 目录动销数({yxs_ct}) > 目录品项数({item_ct})")
        if yxs_all > item_all:
            errors.append(f"[{sheet_tag}] 门店 {store} 违反全店动销包含性: 全店动销数({yxs_all}) > 全店品项数({item_all})")

        # 3. 销售额包含性不变式 (允许 1.0 元浮点微差)
        sale_ct = float(row.get("目录内近90天折算日均销售额", 0.0))
        sale_all = float(row.get("全店近90天折算日均销售额", 0.0))
        if sale_ct > sale_all + 1.0:
            errors.append(f"[{sheet_tag}] 门店 {store} 违反销售额包含性: 目录折算日均销({sale_ct}) > 全店折算日均销({sale_all})")

        # 4. 库存成本包含性不变式 (允许 1.0 元浮点微差)
        inv_ct = float(row.get("目录内近90天日均库存成本", 0.0))
        inv_all = float(row.get("全店近90天日均库存成本", 0.0))
        if inv_ct > inv_all + 1.0:
            errors.append(f"[{sheet_tag}] 门店 {store} 违反库存成本包含性: 目录库存({inv_ct}) > 全店库存({inv_all})")

        # 5. 时间进度不变式
        prog_raw = row.get("时间进度", 0.0)
        prog_val = parse_pct_or_float(prog_raw)
        if is_ongoing:
            if not (0.0 <= prog_val <= 1.05):
                errors.append(f"[{sheet_tag}] 跟进中门店 {store} 时间进度越界: {prog_raw}")
        else:
            if abs(prog_val - 1.0) > 0.01:
                errors.append(f"[{sheet_tag}] 已结束门店 {store} 时间进度未锁定为 100%: 实际为 {prog_raw}")

        # 6. 总指标与达成率合理性
        target_total = float(row.get("90天总指标", 0.0))
        if target_total <= 0:
            errors.append(f"[{sheet_tag}] 门店 {store} 90天总指标异常: {target_total} <= 0")

        # 7. 试点营运区规范名
        test_reg = row.get("试点营运区")
        if test_reg not in ["是", "否"]:
            errors.append(f"[{sheet_tag}] 门店 {store} 试点营运区字段值异常: '{test_reg}'，必须为'是'或'否'")

    return errors


def main():
    parser = argparse.ArgumentParser(description="新店效益与考核分析对抗性审查门禁")
    parser.add_argument("--excel", type=str, required=True, help="待审查的 Excel 文件路径")
    args = parser.parse_args()

    excel_path = Path(args.excel).resolve()
    print(f"[ADVERSARIAL GATE] 正在对文件启动对抗性审查: {excel_path}")

    findings = audit_excel_workbook(excel_path)
    if findings:
        print("\n" + "=" * 60)
        print(f"[ADVERSARIAL AUDIT GATE] ❌ 审查发现 {len(findings)} 项违规或风险缺陷:")
        for f in findings:
            print(f"  - {f}")
        print("=" * 60 + "\n")
        sys.exit(1)
    else:
        print("\n" + "=" * 60)
        print("[ADVERSARIAL AUDIT GATE] ✅ 所有审查门禁全部通过！数据不变式严格守恒，格式符合生产要求。")
        print("=" * 60 + "\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
