#!/usr/bin/env python3
"""
O2O Store Benefit Report Automation Helper Script.
Executes end-to-end MaxCompute ETL pipeline and exports structured executive cards to Excel.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

_script_path = Path(__file__).absolute()
_candidates = [Path.cwd(), _script_path.parent, *_script_path.parents]
_env_root = os.environ.get("PRODUCT_STRATEGY_ROOT")
if _env_root:
    _candidates.append(Path(_env_root))
REPO_ROOT = next((c for c in _candidates if (c / "shared").is_dir()), Path.cwd())
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
O2O_SCRIPTS = REPO_ROOT / "topics/o2o_store/03_analysis/scripts"
if str(O2O_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(O2O_SCRIPTS))

from run_city_top2500_phase1 import load_env_file  # noqa: E402
from shared.config import ODPSConfig  # noqa: E402
from shared.odps_connector import ODPSConnector  # noqa: E402
from sql_builder import render_dws_and_ads_sql  # noqa: E402


def format_card_summary(
    *,
    card_idx: int,
    store_group: str,
    strategy_tag: str,
    source_suffix: str,
    items: list[dict[str, Any]],
) -> str:
    """Format the executive summary while preserving metric units."""
    by_metric = {item["metric_name"]: item for item in items}
    sales_row = by_metric.get("销售额")
    margin_row = by_metric.get("毛利额")
    dx_row = next(
        (
            value
            for metric_name, value in by_metric.items()
            if metric_name.endswith("动销率") and metric_name != "目录内动销率"
        ),
        None,
    )
    cata_dx_row = by_metric.get("目录内动销率")

    def _ratio(row: dict[str, Any] | None) -> str:
        if row is None or row.get("all_diff_ratio") is None:
            return "-"
        return f"{row['all_diff_ratio'] * 100:+.2f}%"

    def _percentage_points(row: dict[str, Any] | None) -> str:
        if row is None or row.get("all_diff") is None:
            return "-"
        return f"{row['all_diff']:+.2f}个百分点"

    return (
        f"【卡片 {card_idx}】{store_group} - {strategy_tag}{source_suffix} 结果呈现：\n"
        f"通过将「{strategy_tag}」纳入{store_group}组货，"
        f"销售额变化 {_ratio(sales_row)}，毛利额变化 {_ratio(margin_row)}，"
        f"标签动销率变化 {_percentage_points(dx_row)}，"
        f"全店目录内动销率变化 {_percentage_points(cata_dx_row)}"
    )


class O2OStoreBenefitRunner:
    def __init__(
        self,
        cutoff_date: str,
        version_date: str | None = None,
        baseline_type: str = "H",
        tag_source: str | None = None,
        target_project: str = "dsl_analysis",
        export_dir: Path | None = None,
        card_scope: str = "raw_all_stores",
    ) -> None:
        self.cutoff_date = str(cutoff_date)
        self.version_date = str(version_date) if version_date else None
        for field_name, field_value in (
            ("cutoff_date", self.cutoff_date),
            ("version_date", self.version_date),
        ):
            if field_value is None:
                continue
            try:
                date.fromisoformat(
                    f"{field_value[:4]}-{field_value[4:6]}-{field_value[6:]}"
                )
            except ValueError as exc:
                raise ValueError(f"{field_name} must be a valid YYYYMMDD date") from exc
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", target_project):
            raise ValueError("target_project must be a safe MaxCompute identifier")
        self.baseline_type = baseline_type.upper()  # 'H' for YoY, 'L' for MoM
        if self.baseline_type not in {"H", "L"}:
            raise ValueError("baseline_type must be 'H' or 'L'")
        requested_scope = card_scope.lower()
        if tag_source is not None:
            legacy_scopes = {"new": "restored_11", "raw": "raw_all_stores"}
            try:
                legacy_scope = legacy_scopes[tag_source.lower()]
            except KeyError as exc:
                raise ValueError("tag_source must be 'new' or 'raw'") from exc
            if requested_scope not in {"raw_all_stores", legacy_scope}:
                raise ValueError(
                    "tag_source and card_scope select conflicting card scopes"
                )
            requested_scope = legacy_scope
        self.card_scope = requested_scope
        if self.card_scope not in {"raw_all_stores", "restored_11", "all"}:
            raise ValueError(
                "card_scope must be 'raw_all_stores', 'restored_11', or 'all'"
            )
        self.target_project = target_project
        self.export_dir = export_dir or (
            REPO_ROOT / "topics/o2o_store/04_outputs/tables"
        )
        self.export_dir.mkdir(parents=True, exist_ok=True)

        env_path = os.environ.get("ODPS_ENV_FILE") or str(
            Path.home() / "work/projects/www/marimo/merchandise/.env"
        )
        load_env_file(env_path)
        self.connector = ODPSConnector(
            ODPSConfig(project=os.environ.get("ODPS_PROJECT", "dsl_ads"))
        )
        self.odps: Any = self.connector.connect()

    def log(self, msg: str) -> None:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

    def execute_sql(self, sql: str, step_name: str) -> None:
        self.log(f"Starting: {step_name}...")
        start_t = time.time()
        # Enable 2.0 type system and script mode
        hints = {
            "odps.sql.type.system.odps2": "true",
            "odps.sql.submit.mode": "script",
        }
        inst = self.odps.execute_sql(sql, hints=hints)
        inst.wait_for_success()
        elapsed = time.time() - start_t
        self.log(f"Finished: {step_name} in {elapsed:.1f}s (Instance: {inst.id})")

    def run_date_dimension(self) -> dict[str, Any]:
        """Step 1: Compute C, L, H date windows and populate tmp_special_date."""
        # Detect latest version date if not specified
        if not self.version_date:
            sql_ver = f"""
            select max(online_date) as latest_ver
            from dsl_analysis.ads_item_store_catelogue_version_online_date
            where online_date < {self.cutoff_date}
            """
            with self.odps.execute_sql(sql_ver).open_reader() as reader:
                rec = next(iter(reader), None)
                if not rec or rec[0] is None:
                    raise ValueError(
                        f"Cannot auto-detect version online date prior to {self.cutoff_date}"
                    )
                self.version_date = str(rec[0])
            self.log(f"Auto-detected version online date: {self.version_date}")

        sql = f"""
        create table if not exists {self.target_project}.tmp_special_date_for_o2o_channel_to_cata_info_df_2604 (
            day_id        bigint  comment '日期ID(yyyyMMdd)',
            day_date      string  comment '日期(yyyy-MM-dd)',
            c_s_date      date    comment 'C期起始(组货版本上线日)',
            c_e_date      date    comment 'C期截止(昨天)',
            c_s_date_id   bigint  comment 'C期起始日期ID(最新版本上线日yyyyMMdd)',
            c_days        int     comment 'C期天数(含首尾)',
            period_type   string  comment '周期类型:C上线后/L上线前/H去年同期'
        )
        comment 'O2O效益分析-特殊日期区间映射表(日粒度)'
        partitioned by (pt bigint comment '跑批日期(yyyyMMdd)')
        ;

        insert overwrite table {self.target_project}.tmp_special_date_for_o2o_channel_to_cata_info_df_2604 partition (pt = {self.cutoff_date})
        with base as (
            select 
                to_date('{self.version_date}', 'yyyyMMdd') as c_s_date,
                to_date('{self.cutoff_date}', 'yyyyMMdd') as c_e_date,
                cast('{self.version_date}' as bigint) as c_s_date_id
        )
        , cfg as (
            select 
                c_s_date,
                c_e_date,
                c_s_date_id,
                datediff(c_e_date, c_s_date, 'dd') + 1 as c_days,
                dateadd(c_s_date, -(datediff(c_e_date, c_s_date, 'dd') + 1), 'dd') as l_s_date,
                dateadd(c_s_date, -1, 'dd') as l_e_date,
                to_date(add_months(c_s_date, -12), 'yyyy-MM-dd') as h_s_date,
                to_date(add_months(c_e_date, -12), 'yyyy-MM-dd') as h_e_date
            from base
        )
        select /*+ mapjoin(c) */ cast(t.day_id as bigint) as day_id, t.day_date, c.c_s_date, c.c_e_date, c.c_s_date_id, c.c_days, 'C' as period_type
        from cfg c join dsl_dim.dim_day t on to_date(t.day_date, 'yyyy-mm-dd') between c.c_s_date and c.c_e_date
        union all
        select /*+ mapjoin(c) */ cast(t.day_id as bigint) as day_id, t.day_date, c.c_s_date, c.c_e_date, c.c_s_date_id, c.c_days, 'L' as period_type
        from cfg c join dsl_dim.dim_day t on to_date(t.day_date, 'yyyy-mm-dd') between c.l_s_date and c.l_e_date
        union all
        select /*+ mapjoin(c) */ cast(t.day_id as bigint) as day_id, t.day_date, c.c_s_date, c.c_e_date, c.c_s_date_id, c.c_days, 'H' as period_type
        from cfg c join dsl_dim.dim_day t on to_date(t.day_date, 'yyyy-mm-dd') between c.h_s_date and c.h_e_date
        ;
        """
        self.execute_sql(sql, f"Date Dimension Ingestion (pt={self.cutoff_date})")

        # Query back bounds for offline between-and query
        bounds_sql = f"""
        select period_type, min(day_id) as min_d, max(day_id) as max_d, max(c_s_date_id) as ver_id
        from {self.target_project}.tmp_special_date_for_o2o_channel_to_cata_info_df_2604
        where pt = {self.cutoff_date}
        group by period_type
        """
        bounds = {}
        with self.odps.execute_sql(bounds_sql).open_reader() as reader:
            for rec in reader:
                bounds[rec.period_type] = (rec.min_d, rec.max_d)
                bounds["ver_id"] = rec.ver_id
        return bounds

    def run_merchandise_tags(self) -> None:
        """Step 2: Extract merchandise tags with restored priority is_3he1_fl, excluding monthly updates."""
        sql = f"""
        insert overwrite table {self.target_project}.tmp_o2o_mttop500_city_detail_df_2604 partition (pt = {self.cutoff_date})
        select store_code, cast(item_code as bigint) as item_code, reason_zfl, is_3he1_fl
        from (
            select store_code, item_code,
                   case when t0.reason_zfl in ('城市top500品','城市top200','跨渠道top80','o2o中心店品')
                        then reason_zfl else '其他' end as reason_zfl,
                   case when coalesce(is_3he1_list,0) = 0 then ''
                        when is_o2o_key_item = 1 then o2o_key_reason
                        when is_o2o_store_item = 1 and is_city_top200 = 1 then '城市top200'
                        when is_o2o_store_item = 1 and is_online_mttbtop80 = 1 then '跨渠道top80'
                        when is_o2o_store_item = 1 then 'o2o中心店品'
                        else '其他' end as is_3he1_fl
            from dsl_ads.ads_item_3he1_db_1_6_store_item_list_df t0
            left semi join (
                select store_code
                from dsl_dwd.dwd_item_3he1_gray_scale_list_df
                where stat_date = {self.cutoff_date}
            ) t1 on t0.store_code = t1.store_code
            where stat_date = {self.cutoff_date}
              and is_store_o2o = 1
              and is_3he1_list = 1
              and version_num not like '%月度%'
        ) dt
        where not (reason_zfl = '其他' and is_3he1_fl = '其他')
        ;
        """
        self.execute_sql(sql, f"Merchandise Tag Ingestion (pt={self.cutoff_date})")

    def run_channel_sales(self, bounds: dict[str, Any]) -> None:
        """Step 3: Run online and offline sub-tables with between-and static pruning."""
        ver_id = bounds["ver_id"]
        key_store_month = ver_id // 100

        # 3.1 Online
        h_min, _ = bounds["H"]
        _, c_max = bounds["C"]
        sql_on = f"""
        insert overwrite table {self.target_project}.tmp_o2o_channel_sales_online_df_2604 partition (pt = {self.cutoff_date})
        with key_store as (
            select store_code, max(case when store_level = 'A' then 1 else 0 end) as is_key_store
            from dsl_dwd.dwd_ti_ec_key_stores_business_capacity
            where stat_date = {key_store_month}
            group by store_code
        )
        , ds as (
            select region_man_code, store_code from dsl_dim.dim_store where stat_date = {self.cutoff_date}
        )
        select /*+ mapjoin(re, b, toci, t1) */
               t1.region_man_code, a.store_code, a.item_code, re.is_key_store, 'online' as platform_name, toci.period_type,
               sum(a.item_sale_cnt) as item_sale_cnt,
               sum(a.pay_amt) as pay_amt,
               sum(a.margin_account) as margin_account,
               sum(a.forward_passenger_flow) as passenger_flow
        from dsl_ads.ads_ec_platform_store_item_subsidy_sum_d a
        inner join dsl_dim.dim_ec_platform b on a.platform_id = b.platform_id and b.business_type_tmp = 'O2O'
        inner join key_store re on a.store_code = re.store_code
        inner join {self.target_project}.tmp_special_date_for_o2o_channel_to_cata_info_df_2604 toci on a.stat_date = toci.day_id and toci.pt = {self.cutoff_date}
        left join ds t1 on a.store_code = t1.store_code
        where a.stat_date between {h_min} and {c_max}
        group by t1.region_man_code, a.store_code, a.item_code, re.is_key_store, toci.period_type
        ;
        """
        self.execute_sql(sql_on, "Online Sales Ingestion")

        # 3.2 Offline C/L/H sub-tables
        for period in ["C", "L", "H"]:
            p_min, p_max = bounds[period]
            sub_tbl = f"tmp_o2o_sales_off_{period.lower()}_2604"
            sql_off_sub = f"""
            insert overwrite table {self.target_project}.{sub_tbl} partition (pt = {self.cutoff_date})
            with key_store as (
                select store_code, max(case when store_level = 'A' then 1 else 0 end) as is_key_store
                from dsl_dwd.dwd_ti_ec_key_stores_business_capacity
                where stat_date = {key_store_month}
                group by store_code
            )
            , ds as (
                select region_man_code, store_code from dsl_dim.dim_store where stat_date = {self.cutoff_date}
            )
            select /*+ mapjoin(re, t1) */
                   t1.region_man_code, b.store_code, cast(b.item_code as bigint) as item_code, re.is_key_store, 'offline' as platform_name, '{period}' as period_type,
                   sum(b.item_sale_cnt) as item_sale_cnt,
                   sum(b.pay_amt) as pay_amt,
                   sum(b.total_profit_amt) as margin_account,
                   sum(b.passenger_flow) as passenger_flow
            from dsl_ads.ads_sale_store_channel_mem_item_metrics_sum_di b
            inner join key_store re on b.store_code = re.store_code
            left join ds t1 on b.store_code = t1.store_code
            where b.stat_date between {p_min} and {p_max}
              and not (coalesce(b.channel_type,0) in (1, 2) or b.channel_id in ('30', '21') or b.store_code = 1022018002)
            group by t1.region_man_code, b.store_code, cast(b.item_code as bigint), re.is_key_store
            ;
            """
            self.execute_sql(
                sql_off_sub, f"Offline Sub-table Ingestion (Period {period})"
            )

        # 3.3 Merge offline and detail
        cols = "region_man_code, store_code, item_code, is_key_store, platform_name, period_type, item_sale_cnt, pay_amt, margin_account, passenger_flow"
        sql_merge_off = f"""
        insert overwrite table {self.target_project}.tmp_o2o_channel_sales_offline_df_2604 partition (pt = {self.cutoff_date})
        select {cols} from {self.target_project}.tmp_o2o_sales_off_c_2604 where pt = {self.cutoff_date}
        union all
        select {cols} from {self.target_project}.tmp_o2o_sales_off_l_2604 where pt = {self.cutoff_date}
        union all
        select {cols} from {self.target_project}.tmp_o2o_sales_off_h_2604 where pt = {self.cutoff_date}
        ;
        """
        self.execute_sql(sql_merge_off, "Merge Offline Sales Total")

        sql_merge_all = f"""
        insert overwrite table {self.target_project}.tmp_o2o_channel_sales_detail_df_2604 partition (pt = {self.cutoff_date})
        select {cols} from {self.target_project}.tmp_o2o_channel_sales_online_df_2604 where pt = {self.cutoff_date}
        union all
        select {cols} from {self.target_project}.tmp_o2o_channel_sales_offline_df_2604 where pt = {self.cutoff_date}
        ;
        """
        self.execute_sql(sql_merge_all, "Merge Channel Sales Detail Total")

    def run_goals(self) -> None:
        """Step 4: Build goals wide table with both lx_new and lx_raw."""
        sql = f"""
        insert overwrite table {self.target_project}.analysis_analysis_assortment_o2_store_cata_items_goals_df partition (pt = {self.cutoff_date})
        with sales as (
            select store_code, item_code, is_key_store, platform_name, period_type,
                   pay_amt, margin_account, passenger_flow
            from {self.target_project}.tmp_o2o_channel_sales_detail_df_2604
            where pt = {self.cutoff_date}
              and period_type in ('C', 'L', 'H')
        )
        , tags as (
            select store_code, item_code, reason_zfl as lx_raw, is_3he1_fl as lx_new
            from {self.target_project}.tmp_o2o_mttop500_city_detail_df_2604
            where pt = {self.cutoff_date}
        )
        select s.store_code, s.item_code, s.is_key_store, s.period_type, s.platform_name,
               coalesce(t.lx_new, '其他标签') as lx_new,
               s.pay_amt, s.margin_account, s.passenger_flow,
               coalesce(t.lx_raw, '其他标签') as lx_raw
        from sales s
        left join tags t on s.store_code = t.store_code and s.item_code = t.item_code
        ;
        """
        self.execute_sql(sql, "Build Goals Wide Table")

    def run_dws_and_ads(self, bounds: dict[str, Any]) -> None:
        """Step 5 & 6: render and execute DWS/ADS benefit-card SQL."""
        sql_dws, sql_ads = render_dws_and_ads_sql(
            bounds,
            cutoff_date=self.cutoff_date,
            baseline_type=self.baseline_type,
            target_project=self.target_project,
        )
        self.execute_sql(sql_dws, "DWS Diagnostic Summary Ingestion")
        self.execute_sql(sql_ads, "ADS Executive Card Table Ingestion")

    def export_excel(self) -> str:
        """Step 7: Pull from ADS card table and format into executive Excel workbooks."""
        scope_filters = {
            "raw_all_stores": (
                "tag_source = 'raw' and store_group = '所有重点门店' "
                "and strategy_tag in "
                "('城市top500品','城市top200','跨渠道top80','o2o中心店品')"
            ),
            "restored_11": "tag_source = 'restored'",
            "all": "1 = 1",
        }
        scope_descriptions = {
            "raw_all_stores": "reason_zfl × 所有重点门店（4卡）",
            "restored_11": "is_3he1_fl × 三层门店（11卡）",
            "all": "全部已聚合卡片",
        }
        scope_filter = scope_filters[self.card_scope]
        scope_description = scope_descriptions[self.card_scope]
        sql = f"""
        select 
            store_group, strategy_tag, order_seq, metric_name,
            all_post, all_pre, all_diff, all_diff_ratio,
            o2o_post, o2o_pre, o2o_diff, o2o_diff_ratio,
            offline_post, offline_pre, offline_diff, offline_diff_ratio,
            c_avg_tag_items, l_avg_tag_items, c_avg_tag_dx, l_avg_tag_dx,
            c_avg_cata_items, l_avg_cata_items, c_avg_cata_dx, l_avg_cata_dx,
            remark, tag_source
        from {self.target_project}.ads_o2o_key_store_benefit_card_df
        where pt = {self.cutoff_date}
          and {scope_filter}
        order by 
            case when tag_source = 'raw' then 1 else 2 end,
            case when store_group = '所有重点门店' then 1
                 when store_group = '中心店' then 2
                 when store_group = 'O2O其他重点店' then 3 else 4 end,
            case when strategy_tag = '城市top500品' then 1
                 when strategy_tag = '城市top200' then 2
                 when strategy_tag = '跨渠道top80' then 3
                 when strategy_tag = 'o2o中心店品' then 4 else 5 end,
            order_seq
        """
        rows = []
        with self.odps.execute_sql(sql).open_reader() as reader:
            cols = [c.name for c in reader._schema.columns]
            for rec in reader:
                rows.append({cols[i]: rec[i] for i in range(len(cols))})

        if not rows:
            raise ValueError(
                f"No data returned from ads card table for pt={self.cutoff_date}"
            )

        out_path = (
            self.export_dir / f"o2o_key_store_benefit_cards_{self.cutoff_date}.xlsx"
        )
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "O2O效益评估卡片"

        # Styling
        font_title = Font(name="Microsoft YaHei", size=14, bold=True, color="FFFFFF")
        font_card_head = Font(
            name="Microsoft YaHei", size=11, bold=True, color="FFFFFF"
        )
        font_tbl_head = Font(name="Microsoft YaHei", size=9, bold=True, color="FFFFFF")
        font_data = Font(name="Microsoft YaHei", size=9)
        font_note = Font(name="Microsoft YaHei", size=8, color="7F8C8D")

        fill_title = PatternFill(
            start_color="1F4E78", end_color="1F4E78", fill_type="solid"
        )
        fill_card_head = PatternFill(
            start_color="2F5597", end_color="2F5597", fill_type="solid"
        )
        fill_tbl_head = PatternFill(
            start_color="41719C", end_color="41719C", fill_type="solid"
        )
        fill_evidence_head = PatternFill(
            start_color="5B7065", end_color="5B7065", fill_type="solid"
        )

        border_thin = Side(border_style="thin", color="D9D9D9")
        border_cell = Border(
            left=border_thin, right=border_thin, top=border_thin, bottom=border_thin
        )

        align_center = Alignment(horizontal="center", vertical="center")
        align_right = Alignment(horizontal="right", vertical="center")

        # Title block
        baseline_desc = "去年同期" if self.baseline_type == "H" else "上线前窗口"
        ws.merge_cells("A1:P1")
        title_cell = ws["A1"]
        title_cell.value = (
            f"O2O重点门店/中心店组货策略效益评估报告 "
            f"(基期: {baseline_desc} | 卡片范围: {scope_description} "
            f"| 评估截止: {self.cutoff_date})"
        )
        title_cell.font = font_title
        title_cell.fill = fill_title
        title_cell.alignment = align_center
        ws.row_dimensions[1].height = 36

        # Group data into cards
        cards: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for r in rows:
            key = (r["tag_source"], r["store_group"], r["strategy_tag"])
            cards.setdefault(key, []).append(r)

        curr_row = 3
        card_idx = 1
        for (tag_source, s_group, s_tag), items in cards.items():
            source_suffix = (
                f"（{'reason_zfl' if tag_source == 'raw' else 'is_3he1_fl'}）"
                if self.card_scope == "all"
                else ""
            )
            # Card Banner
            ws.merge_cells(
                start_row=curr_row, start_column=1, end_row=curr_row, end_column=10
            )
            c_cell = ws.cell(
                row=curr_row,
                column=1,
                value=f"【卡片 {card_idx}】{s_group}「{s_tag}」{source_suffix}效益评估",
            )
            c_cell.font = font_card_head
            c_cell.fill = fill_card_head
            c_cell.alignment = align_center

            # Summary Sentence Row (auto-generated from card metrics)
            summary_text = format_card_summary(
                card_idx=card_idx,
                store_group=s_group,
                strategy_tag=s_tag,
                source_suffix=source_suffix,
                items=items,
            )
            summary_row_idx = curr_row + 1
            ws.merge_cells(
                start_row=summary_row_idx,
                start_column=1,
                end_row=summary_row_idx,
                end_column=16,
            )
            s_cell = ws.cell(
                row=summary_row_idx,
                column=1,
                value=summary_text,
            )
            s_cell.font = font_note
            s_cell.alignment = Alignment(
                horizontal="left", vertical="center", wrap_text=True
            )
            ws.row_dimensions[summary_row_idx].height = 30
            curr_row += 2

            # Evidence Banner (Columns 11 to 16, no store count columns)
            ws.merge_cells(
                start_row=curr_row, start_column=11, end_row=curr_row, end_column=16
            )
            e_cell = ws.cell(
                row=curr_row, column=11, value="【店均规模量化证据栏】(防误判)"
            )
            e_cell.font = font_card_head
            e_cell.fill = PatternFill(
                start_color="34495E", end_color="34495E", fill_type="solid"
            )
            e_cell.alignment = align_center
            curr_row += 1

            # Table Header Row 1
            ws.merge_cells(
                start_row=curr_row, start_column=1, end_row=curr_row + 1, end_column=1
            )
            ws.cell(row=curr_row, column=1, value="指标类型").alignment = align_center

            ws.merge_cells(
                start_row=curr_row, start_column=2, end_row=curr_row, end_column=4
            )
            ws.cell(row=curr_row, column=2, value="整体").alignment = align_center

            ws.merge_cells(
                start_row=curr_row, start_column=5, end_row=curr_row, end_column=7
            )
            ws.cell(row=curr_row, column=5, value="O2O渠道").alignment = align_center

            ws.merge_cells(
                start_row=curr_row, start_column=8, end_row=curr_row, end_column=10
            )
            ws.cell(row=curr_row, column=8, value="线下渠道").alignment = align_center

            # Evidence Headers (Only store averages)
            ws.merge_cells(
                start_row=curr_row, start_column=11, end_row=curr_row, end_column=12
            )
            ws.cell(
                row=curr_row, column=11, value="标签店均品数"
            ).alignment = align_center

            ws.merge_cells(
                start_row=curr_row, start_column=13, end_row=curr_row, end_column=14
            )
            ws.cell(
                row=curr_row, column=13, value="标签店均动销品数"
            ).alignment = align_center

            ws.merge_cells(
                start_row=curr_row, start_column=15, end_row=curr_row, end_column=16
            )
            ws.cell(
                row=curr_row, column=15, value="全店店均目录品数"
            ).alignment = align_center

            for c in range(1, 17):
                cell = ws.cell(row=curr_row, column=c)
                cell.fill = fill_tbl_head if c <= 10 else fill_evidence_head
                cell.font = font_tbl_head
                cell.border = border_cell

            curr_row += 1

            # Table Header Row 2
            baseline_label = "去年同期" if self.baseline_type == "H" else "上线前"
            sub_headers = [
                "指标类型",
                "上线后",
                baseline_label,
                "差异值",
                "上线后",
                baseline_label,
                "差异值",
                "上线后",
                baseline_label,
                "差异值",
                "上线后",
                baseline_label,
                "上线后",
                baseline_label,
                "上线后",
                baseline_label,
            ]
            for col_idx, sh in enumerate(sub_headers, 1):
                if col_idx > 1:
                    cell = ws.cell(row=curr_row, column=col_idx, value=sh)
                    cell.alignment = align_center
                    cell.fill = fill_tbl_head if col_idx <= 10 else fill_evidence_head
                    cell.font = font_tbl_head
                    cell.border = border_cell
            curr_row += 1

            # Metric Rows
            for item in items:
                m_name = item["metric_name"]
                is_dx = "动销率" in m_name
                unit = "%" if is_dx else "万"

                m_cell = ws.cell(
                    row=curr_row,
                    column=1,
                    value=f"{m_name}({unit})" if not is_dx else m_name,
                )
                m_cell.font = font_data
                m_cell.alignment = align_center
                m_cell.border = border_cell

                c_post = item.get("all_post")
                c_pre = item.get("all_pre")
                c_diff = item.get("all_diff")

                v_post = ws.cell(
                    row=curr_row,
                    column=2,
                    value=f"{c_post:.2f}%"
                    if is_dx and c_post is not None
                    else (f"{c_post:.1f}万" if c_post is not None else "-"),
                )
                v_pre = ws.cell(
                    row=curr_row,
                    column=3,
                    value=f"{c_pre:.2f}%"
                    if is_dx and c_pre is not None
                    else (f"{c_pre:.1f}万" if c_pre is not None else "-"),
                )
                v_diff = ws.cell(
                    row=curr_row,
                    column=4,
                    value=f"{c_diff:+.2f}%"
                    if is_dx and c_diff is not None
                    else (f"{c_diff:+.1f}万" if c_diff is not None else "-"),
                )

                for v_cell in [v_post, v_pre, v_diff]:
                    v_cell.alignment = align_right
                    v_cell.font = font_data
                    v_cell.border = border_cell

                if is_dx:
                    ws.merge_cells(
                        start_row=curr_row,
                        start_column=5,
                        end_row=curr_row,
                        end_column=10,
                    )
                    n_cell = ws.cell(
                        row=curr_row, column=5, value=item.get("remark") or ""
                    )
                    n_cell.alignment = align_center
                    n_cell.font = font_note
                    for c in range(5, 11):
                        ws.cell(row=curr_row, column=c).border = border_cell
                else:
                    o_post = item.get("o2o_post")
                    o_pre = item.get("o2o_pre")
                    o_diff = item.get("o2o_diff")
                    ws.cell(
                        row=curr_row,
                        column=5,
                        value=f"{o_post:.1f}万" if o_post is not None else "-",
                    ).alignment = align_right
                    ws.cell(
                        row=curr_row,
                        column=6,
                        value=f"{o_pre:.1f}万" if o_pre is not None else "-",
                    ).alignment = align_right
                    ws.cell(
                        row=curr_row,
                        column=7,
                        value=f"{o_diff:+.1f}万" if o_diff is not None else "-",
                    ).alignment = align_right

                    f_post = item.get("offline_post")
                    f_pre = item.get("offline_pre")
                    f_diff = item.get("offline_diff")
                    ws.cell(
                        row=curr_row,
                        column=8,
                        value=f"{f_post:.1f}万" if f_post is not None else "-",
                    ).alignment = align_right
                    ws.cell(
                        row=curr_row,
                        column=9,
                        value=f"{f_pre:.1f}万" if f_pre is not None else "-",
                    ).alignment = align_right
                    ws.cell(
                        row=curr_row,
                        column=10,
                        value=f"{f_diff:+.1f}万" if f_diff is not None else "-",
                    ).alignment = align_right

                    for c in range(5, 11):
                        cell = ws.cell(row=curr_row, column=c)
                        cell.font = font_data
                        cell.border = border_cell

                # Append Evidence Columns (11 to 16, store-average only)
                ti_post = item.get("c_avg_tag_items")
                ti_pre = item.get("l_avg_tag_items")
                ws.cell(
                    row=curr_row,
                    column=11,
                    value=f"{ti_post:.1f}" if ti_post is not None else "-",
                ).alignment = align_right
                ws.cell(
                    row=curr_row,
                    column=12,
                    value=f"{ti_pre:.1f}" if ti_pre is not None else "-",
                ).alignment = align_right

                td_post = item.get("c_avg_tag_dx")
                td_pre = item.get("l_avg_tag_dx")
                ws.cell(
                    row=curr_row,
                    column=13,
                    value=f"{td_post:.1f}" if td_post is not None else "-",
                ).alignment = align_right
                ws.cell(
                    row=curr_row,
                    column=14,
                    value=f"{td_pre:.1f}" if td_pre is not None else "-",
                ).alignment = align_right

                ci_post = item.get("c_avg_cata_items")
                ci_pre = item.get("l_avg_cata_items")
                ws.cell(
                    row=curr_row,
                    column=15,
                    value=f"{ci_post:.1f}" if ci_post is not None else "-",
                ).alignment = align_right
                ws.cell(
                    row=curr_row,
                    column=16,
                    value=f"{ci_pre:.1f}" if ci_pre is not None else "-",
                ).alignment = align_right

                for c in range(11, 17):
                    cell = ws.cell(row=curr_row, column=c)
                    cell.font = font_data
                    cell.border = border_cell

                curr_row += 1

            curr_row += 2
            card_idx += 1

        col_widths = [22, 13, 13, 13, 13, 13, 13, 13, 13, 13, 14, 14, 15, 15, 15, 15]
        for col_idx, w in enumerate(col_widths, 1):
            ws.column_dimensions[get_column_letter(col_idx)].width = w

        wb.save(str(out_path))
        self.log(f"Excel report successfully written to: {out_path}")
        return str(out_path)

    def run_pipeline(self) -> str:
        """Run all steps sequentially."""
        bounds = self.run_date_dimension()
        self.run_merchandise_tags()
        self.run_channel_sales(bounds)
        self.run_goals()
        self.run_dws_and_ads(bounds)
        excel_file = self.export_excel()
        return excel_file


def main() -> None:
    parser = argparse.ArgumentParser(
        description="O2O Store Benefit Report Automation Runner"
    )
    parser.add_argument(
        "--cutoff",
        required=True,
        help="Evaluation cutoff date yyyyMMdd (e.g., yesterday 20260907)",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Assortment version online date yyyyMMdd (default: auto-detected)",
    )
    parser.add_argument(
        "--baseline",
        default="H",
        choices=["H", "L"],
        help="Baseline period type: H (default YoY baseline) or L (optional pre-launch window)",
    )
    parser.add_argument(
        "--tag-source",
        default=None,
        choices=["new", "raw"],
        help=(
            "Legacy source selector: new maps to restored_11; "
            "raw maps to raw_all_stores. Prefer --card-scope."
        ),
    )
    parser.add_argument(
        "--card-scope",
        default="raw_all_stores",
        choices=["raw_all_stores", "restored_11", "all"],
        help=(
            "Excel scope: raw_all_stores (reason_zfl, 4 cards, default), "
            "restored_11 (is_3he1_fl, 11 cards), or all"
        ),
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Directly export formatted Excel after pipeline execution",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Only export formatted Excel from existing ADS partition without re-running ETL",
    )

    args = parser.parse_args()
    runner = O2OStoreBenefitRunner(
        cutoff_date=args.cutoff,
        version_date=args.version,
        baseline_type=args.baseline,
        tag_source=args.tag_source,
        card_scope=args.card_scope,
    )
    if args.export_only:
        runner.export_excel()
    else:
        runner.run_pipeline()


if __name__ == "__main__":
    main()
