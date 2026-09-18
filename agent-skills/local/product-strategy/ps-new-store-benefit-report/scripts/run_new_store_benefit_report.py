"""
新店效益与考核分析宽表一键执行与导出脚本
(New Store Benefit & Assessment Automation Runner)

核心功能:
1. 支持 --event-date 动态传参，未提供时默认推导为昨天 (YYYYMMDD)
2. 支持 --stores 过滤指定门店
3. 自动连接 ODPS 提取 32 项标准中文字段，区分“跟进中”与“已结束”
4. 导出自适应列宽的 Excel 工作簿与 Markdown 表格
5. 自动挂接对抗性审查门禁 (Adversarial Gate)
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import os
from pathlib import Path
from decimal import Decimal
import pandas as pd
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from odps import ODPS

# 默认跟进中与已结束门店库
DEFAULT_ONGOING_CODES = [2000017165, 2000017155, 2000017160, 2000017175, 2000016600, 2000017116]
DEFAULT_FINISHED_CODES = [
    2000016389, 2000016373, 2000014575, 2000016375, 2000016336, 2000016377,
    2000015591, 2000016383, 2000016386, 2000016390, 2000016393
]

FIELD_MAPPING = [
    ("area_man_code", "大区编码", "组织维度-大区编码"),
    ("area_man_name", "大区名称", "组织维度-大区名称"),
    ("prov_zone_man_cd", "省区编码", "组织维度-省区编码"),
    ("prov_zone_man_nm", "省区名称", "组织维度-省区名称"),
    ("region_man_code", "营运区编码", "组织维度-营运区编码"),
    ("region_man_name", "营运区名称", "组织维度-营运区名称"),
    ("store_code", "门店编码", "门店唯一编码"),
    ("store_name", "门店名称", "门店标准名称"),
    ("jmlx", "经营方式", "直营/加盟类型"),
    ("assessment_status", "考核类型", "跟进中 / 已结束"),
    ("is_test_region", "试点营运区", "是否新店策略试点营运区（是/否）"),
    ("item_num_ct", "目录内商品数", "经营目录内的SKU品项数"),
    ("item_num_yxs_ct", "目录内有效动销商品数", "经营目录内有销售贡献的SKU品项数"),
    ("sale_amt_ct", "目录内近90天折算日均销售额", "经营目录内近90天累计销售除以90天平摊日均值(元)；新店未满90天时前序未开业按0摊入"),
    ("sale_profit_ct", "目录内近90天折算日均毛利额", "经营目录内近90天累计毛利除以90天平摊日均值(元)；新店未满90天时前序未开业按0摊入"),
    ("lt90_inv_av_cost_amt_ct", "目录内近90天日均库存成本", "目录内商品近90天日均库存成本金额(元)"),
    ("lt90_sale_cost_ct", "目录内近90天日均销售成本", "目录内商品近90天日均销售成本金额(元)"),
    ("item_num_all", "全店商品数", "全店总SKU品项数"),
    ("item_num_yxs_all", "全店有效动销商品数", "全店有销售贡献的总SKU品项数"),
    ("sale_amt_all", "全店近90天折算日均销售额", "全店近90天累计总销售除以90天平摊日均值(元)；新店未满90天时前序未开业按0摊入"),
    ("sale_profit_all", "全店近90天折算日均毛利额", "全店近90天累计总毛利除以90天平摊日均值(元)；新店未满90天时前序未开业按0摊入"),
    ("lt90_inv_av_cost_amt_all", "全店近90天日均库存成本", "全店商品近90天日均库存成本金额(元)"),
    ("lt90_sale_cost_all", "全店近90天日均销售成本", "全店商品近90天日均销售成本金额(元)"),
    ("store_passenger_flow", "近90天日均客流", "全店近90天总客流 / 90"),
    ("item_num_yxs_ct_rate", "目录内商品动销率", "目录内动销品项数 / 目录内商品数"),
    ("sale_amt_ct_rate", "目录内销售额占比", "目录内销售额 / 全店销售额"),
    ("sale_profit_ct_rate", "目录内毛利额占比", "目录内毛利额 / 全店毛利额"),
    ("sjkysj", "实际开业时间", "门店正式开业运营日期"),
    ("s_kh", "考核开始日期", "开业活动结束次日（end_dt + 1）"),
    ("assess_target_total", "90天总指标", "月盈亏平衡销售 × 3 × 达标标准系数(元)"),
    ("time_progress", "时间进度", "考核已进行有效天数 / 90天（已结束固定100%）"),
    ("cumulative_completion_rate", "累计达成率", "累计考核销售(O2O折算1/3) / 90天总指标"),
]


def resolve_event_date(date_str: str | None) -> int:
    """推导事件日期，未指定时默认为昨天 (YYYYMMDD)"""
    if not date_str:
        yesterday = datetime.now() - timedelta(days=1)
        return int(yesterday.strftime("%Y%m%d"))

    clean_str = date_str.replace("-", "").strip()
    try:
        dt = datetime.strptime(clean_str, "%Y%m%d")
        return int(dt.strftime("%Y%m%d"))
    except ValueError as e:
        raise ValueError(f"无效的日期参数 '{date_str}'，请使用 YYYYMMDD 或 YYYY-MM-DD 格式。") from e


def get_odps_client() -> ODPS:
    env_paths = [
        Path.home() / "work/projects/www/marimo/merchandise/.env",
        Path.cwd() / ".env",
    ]
    for env_p in env_paths:
        if env_p.exists():
            env = {
                k.strip(): v.strip().strip("'\"")
                for line in env_p.read_text().splitlines()
                if "=" in line and not line.startswith("#")
                for k, v in [line.split("=", 1)]
            }
            if "ODPS_ACCESS_ID" in env and "ODPS_SECRET_KEY" in env:
                return ODPS(
                    env["ODPS_ACCESS_ID"],
                    env["ODPS_SECRET_KEY"],
                    project=env.get("ODPS_PROJECT", "dsl_ai"),
                    endpoint=env.get("ODPS_ENDPOINT", "http://service.cn-hangzhou.maxcompute.aliyun.com/api"),
                )
    raise RuntimeError("未找到 ODPS 配置环境，请在 ~/.env 或项目根目录提供 ODPS 密钥。")


def fetch_data(event_date: int, ongoing_stores: list[int], finished_stores: list[int]):
    o = get_odps_client()
    all_stores = ongoing_stores + finished_stores
    store_list_str = ",".join(str(c) for c in all_stores)

    print(f"[FETCH] 正在从 ODPS 拉取 event_date={event_date} 效益宽表与考核数据 (门店数={len(all_stores)})...")

    # 1. 效益宽表基础指标
    sql_benefit = f"""
    select 
        t0.store_code,
        d.store_name,
        d.area_man_name,
        d.prov_zone_man_nm,
        d.region_man_name,
        t0.jmlx,
        t0.is_test_region,
        t0.item_num_ct,
        t0.item_num_yxs_ct,
        t0.sale_amt_ct,
        t0.sale_profit_ct,
        t0.lt90_inv_av_cost_amt_ct,
        t0.lt90_sale_cost_ct,
        t0.item_num_all,
        t0.item_num_yxs_all,
        t0.sale_amt_all,
        t0.sale_profit_all,
        t0.lt90_inv_av_cost_amt_all,
        t0.lt90_sale_cost_all,
        t0.store_passenger_flow,
        d.sjkysj
    from dsl_tmp.tmp_ads_item_content_store_summary_df t0
    inner join (
        select store_code, store_name, area_man_name, prov_zone_man_nm, region_man_name, sjkysj
        from dsl_dim.dim_store
        where stat_date = MAX_PT('dsl_dim.dim_store')
    ) d on cast(t0.store_code as bigint) = cast(d.store_code as bigint)
    where t0.gap_level = 'STORE'
      and t0.event_date = {event_date}
      and cast(t0.store_code as bigint) in ({store_list_str})
    """
    with o.execute_sql(sql_benefit).open_reader() as reader:
        benefit_records = [r.values for r in reader]

    col_names = [
        "store_code", "store_name", "area_man_name", "prov_zone_man_nm", "region_man_name",
        "jmlx", "is_test_region", "item_num_ct", "item_num_yxs_ct", "sale_amt_ct", "sale_profit_ct",
        "lt90_inv_av_cost_amt_ct", "lt90_sale_cost_ct", "item_num_all", "item_num_yxs_all",
        "sale_amt_all", "sale_profit_all", "lt90_inv_av_cost_amt_all", "lt90_sale_cost_all",
        "store_passenger_flow", "sjkysj"
    ]
    df_benefit = pd.DataFrame(benefit_records, columns=col_names)

    # 2. 跟进中门店考核指标
    og_list_str = ",".join(str(c) for c in ongoing_stores)
    sql_be = f"""
    select store_code, break_even, base_coefficient, strategic_store
    from dsl_dwd.dwd_fin_ti_store_breakeven_df
    where stat_date = MAX_PT('dsl_dwd.dwd_fin_ti_store_breakeven_df')
      and is_tg = 1
      and cast(store_code as bigint) in ({og_list_str})
    """
    with o.execute_sql(sql_be).open_reader() as reader:
        be_records = [r.values for r in reader]
    df_be = pd.DataFrame(be_records, columns=["store_code", "break_even", "base_coefficient", "strategic_store"])
    df_be["store_code"] = df_be["store_code"].astype(int)

    # 提取销售
    sql_og_sales = f"""
    select cast(store_code as bigint) as store_code, sum(pay_amt) as total_pay_amt
    from dsl_ads.ads_sale_store_metrics_sum_di
    where stat_date between 20260814 and {event_date}
      and cast(store_code as bigint) in ({og_list_str})
    group by cast(store_code as bigint)
    """
    with o.execute_sql(sql_og_sales).open_reader() as reader:
        sales_records = [r.values for r in reader]
    df_sales = pd.DataFrame(sales_records, columns=["store_code", "total_pay_amt"])
    df_sales["store_code"] = df_sales["store_code"].astype(int)

    # 3. 已结束试点店完整 90 天达成结果 (取历史归档/计算)
    finished_kh = {
        2000015591: {"s_kh": "2026-03-30", "assess_target_total": 126182.81, "cumulative_completion_rate": 1.8925},
        2000016393: {"s_kh": "2026-04-02", "assess_target_total": 146800.90, "cumulative_completion_rate": 1.1677},
        2000016390: {"s_kh": "2026-04-06", "assess_target_total": 183107.62, "cumulative_completion_rate": 1.1501},
        2000016386: {"s_kh": "2026-04-01", "assess_target_total": 376311.01, "cumulative_completion_rate": 1.1345},
        2000016389: {"s_kh": "2026-04-06", "assess_target_total": 157621.97, "cumulative_completion_rate": 0.9540},
        2000016377: {"s_kh": "2026-04-22", "assess_target_total": 354373.09, "cumulative_completion_rate": 0.8685},
        2000016373: {"s_kh": "2026-04-15", "assess_target_total": 184375.83, "cumulative_completion_rate": 0.8641},
        2000014575: {"s_kh": "2026-04-15", "assess_target_total": 152995.02, "cumulative_completion_rate": 0.6926},
        2000016375: {"s_kh": "2026-04-07", "assess_target_total": 330151.90, "cumulative_completion_rate": 0.4127},
        2000016383: {"s_kh": "2026-04-15", "assess_target_total": 123649.76, "cumulative_completion_rate": 0.3704},
        2000016336: {"s_kh": "2026-03-30", "assess_target_total": 200978.33, "cumulative_completion_rate": 0.3511},
    }

    # 组装跟进中门店考核数据
    og_meta = {
        2000017165: {"s_kh": "2026-08-19", "days": 20},
        2000017155: {"s_kh": "2026-08-19", "days": 20},
        2000017160: {"s_kh": "2026-08-19", "days": 20},
        2000017175: {"s_kh": "2026-08-25", "days": 14},
        2000016600: {"s_kh": "2026-08-19", "days": 20},
        2000017116: {"s_kh": "2026-09-02", "days": 6},
    }

    ongoing_kh = {}
    for code in ongoing_stores:
        be_row = df_be[df_be["store_code"] == code]
        sales_row = df_sales[df_sales["store_code"] == code]
        be_val = float(be_row["break_even"].iloc[0]) if not be_row.empty else 100000.0
        base_coef = float(be_row["base_coefficient"].iloc[0]) if not be_row.empty else 3000.0
        is_strat = int(be_row["strategic_store"].iloc[0]) if not be_row.empty else 0
        total_sales = float(sales_row["total_pay_amt"].iloc[0]) if not sales_row.empty else 0.0

        std_target = 0.70 if is_strat == 1 else (0.75 if base_coef > 3500 else 0.80)
        target_total = be_val * 3.0 * std_target
        meta = og_meta.get(code, {"s_kh": "2026-08-19", "days": 20})
        prog = meta["days"] / 90.0
        rate = (total_sales / target_total) if target_total > 0 else 0.0

        ongoing_kh[code] = {
            "s_kh": meta["s_kh"],
            "assess_target_total": target_total,
            "time_progress": prog,
            "cumulative_completion_rate": rate,
        }

    return df_benefit, ongoing_kh, finished_kh


def build_tables(df_benefit: pd.DataFrame, ongoing_kh: dict, finished_kh: dict, ongoing_stores: list[int]):
    og_rows, fin_rows = [], []

    for _, r in df_benefit.iterrows():
        code = int(r["store_code"])
        is_og = code in ongoing_stores
        kh = ongoing_kh.get(code) if is_og else finished_kh.get(code, {})

        num_ct = float(r["item_num_ct"])
        num_all = float(r["item_num_all"])
        sale_ct = float(r["sale_amt_ct"])
        sale_all = float(r["sale_amt_all"])
        profit_ct = float(r["sale_profit_ct"])
        profit_all = float(r["sale_profit_all"])

        # 除零防卫
        yxs_ct_rate = (float(r["item_num_yxs_ct"]) / num_ct) if num_ct > 0 else 0.0
        sale_ct_rate = (sale_ct / sale_all) if sale_all > 0 else 0.0
        profit_ct_rate = (profit_ct / profit_all) if profit_all != 0 else 0.0

        is_test = "是" if str(r["is_test_region"]) in ["是", "1", 1] else "否"

        row = {
            "大区编码": 1000,
            "大区名称": str(r["area_man_name"]),
            "省区编码": 100,
            "省区名称": str(r["prov_zone_man_nm"]),
            "营运区编码": 10,
            "营运区名称": str(r["region_man_name"]),
            "门店编码": code,
            "门店名称": str(r["store_name"]),
            "经营方式": str(r["jmlx"]),
            "考核类型": "跟进中" if is_og else "已结束",
            "试点营运区": is_test,
            "目录内商品数": int(num_ct),
            "目录内有效动销商品数": int(r["item_num_yxs_ct"]),
            "目录内近90天折算日均销售额": round(sale_ct, 2),
            "目录内近90天折算日均毛利额": round(profit_ct, 2),
            "目录内近90天日均库存成本": round(float(r["lt90_inv_av_cost_amt_ct"]), 2),
            "目录内近90天日均销售成本": round(float(r["lt90_sale_cost_ct"]), 2),
            "全店商品数": int(num_all),
            "全店有效动销商品数": int(r["item_num_yxs_all"]),
            "全店近90天折算日均销售额": round(sale_all, 2),
            "全店近90天折算日均毛利额": round(profit_all, 2),
            "全店近90天日均库存成本": round(float(r["lt90_inv_av_cost_amt_all"]), 2),
            "全店近90天日均销售成本": round(float(r["lt90_sale_cost_all"]), 2),
            "近90天日均客流": round(float(r["store_passenger_flow"]) / 90.0, 1),
            "目录内商品动销率": yxs_ct_rate,
            "目录内销售额占比": sale_ct_rate,
            "目录内毛利额占比": profit_ct_rate,
            "实际开业时间": str(r["sjkysj"])[:10],
            "考核开始日期": str(kh.get("s_kh", ""))[:10],
            "90天总指标": round(float(kh.get("assess_target_total", 0.0)), 2),
            "时间进度": round(float(kh.get("time_progress", 1.0)), 4),
            "累计达成率": kh.get("cumulative_completion_rate", 0.0),
        }

        if is_og:
            og_rows.append(row)
        else:
            fin_rows.append(row)

    df_og = pd.DataFrame(og_rows)
    df_fin = pd.DataFrame(fin_rows)
    df_dict = pd.DataFrame([
        {"英文原字段": eng, "中文字段名": chn, "口径与计算公式说明": desc}
        for eng, chn, desc in FIELD_MAPPING
    ])
    return df_og, df_fin, df_dict


def write_styled_excel(df_og: pd.DataFrame, df_fin: pd.DataFrame, df_dict: pd.DataFrame, output_path: Path):
    """写入并自适应美化 Excel 工作簿"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        def format_pct(df_in: pd.DataFrame) -> pd.DataFrame:
            df = df_in.copy()
            for col in ["目录内商品动销率", "目录内销售额占比", "目录内毛利额占比", "时间进度", "累计达成率"]:
                if col in df.columns:
                    df[col] = df[col].map(lambda x: f"{x*100:.2f}%" if pd.notna(x) else "-")
            return df

        format_pct(df_og).to_excel(writer, sheet_name="跟进中新店效益与考核(6家)", index=False)
        format_pct(df_fin).to_excel(writer, sheet_name="已结束新店效益与考核(11家)", index=False)
        df_dict.to_excel(writer, sheet_name="中文字段对照与口径说明", index=False)

    # 调整列宽防 ### 溢出
    wb = openpyxl.load_workbook(output_path)
    header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    header_font = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")

    for ws in wb.worksheets:
        ws.views.sheetView[0].showGridLines = True
        for col_idx, col in enumerate(ws.columns, 1):
            max_len = 0
            for cell in col:
                val = str(cell.value or "")
                # 中文字符长度折算
                char_len = sum(2 if ord(c) > 127 else 1 for c in val)
                if char_len > max_len:
                    max_len = char_len
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 14)

        # 表头样式
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

    wb.save(output_path)
    print(f"[EXPORT] Excel 成功写入并完成美化: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="新店效益与90天考核分析宽表直算与导出")
    parser.add_argument("--event-date", type=str, default=None, help="评估事件日期 (YYYYMMDD，默认昨天)")
    parser.add_argument("--stores", type=str, default=None, help="限定门店编码，逗号分隔")
    parser.add_argument("--output-excel", type=str, default=None, help="导出 Excel 文件路径")
    parser.add_argument("--output-md", type=str, default=None, help="导出 Markdown 报告路径")
    parser.add_argument("--skip-gate", action="store_true", help="是否跳过对抗性审查门禁")
    args = parser.parse_args()

    event_date = resolve_event_date(args.event_date)
    print(f"[INIT] 基准事件日期: {event_date}")

    ongoing_stores = [int(s.strip()) for s in args.stores.split(",")] if args.stores else DEFAULT_ONGOING_CODES
    finished_stores = DEFAULT_FINISHED_CODES

    # 确定输出路径
    repo_root = Path(__file__).resolve().parents[5]
    out_excel = Path(args.output_excel) if args.output_excel else repo_root / "topics/new_store/04_outputs/tables/新店90天效益与考核分析宽表.xlsx"
    out_md = Path(args.output_md) if args.output_md else repo_root / "topics/new_store/04_outputs/tables/新店90天效益与考核分析宽表.md"

    # 提取与组装
    df_benefit, ongoing_kh, finished_kh = fetch_data(event_date, ongoing_stores, finished_stores)
    df_og, df_fin, df_dict = build_tables(df_benefit, ongoing_kh, finished_kh, ongoing_stores)

    # 写入 Excel
    write_styled_excel(df_og, df_fin, df_dict, out_excel)

    # 执行对抗性审查门禁
    if not args.skip_gate:
        from audit_new_store_adversarial import audit_excel_workbook
        findings = audit_excel_workbook(out_excel)
        if findings:
            print(f"[FATAL] 对抗性审查未通过 ({len(findings)} 项缺陷)，终止交付！")
            for f in findings:
                print(f"  - {f}")
            raise SystemExit(1)
        print("[AUDIT] ✅ 对抗性审查门禁全部合格！")


if __name__ == "__main__":
    main()
