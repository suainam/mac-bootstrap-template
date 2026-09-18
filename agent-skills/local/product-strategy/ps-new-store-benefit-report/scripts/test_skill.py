"""
Skill 自动化单元测试与对抗性边界断言
(Unit Tests and Adversarial Boundary Tests for ps-new-store-benefit-report)
"""

from datetime import datetime, timedelta
import os
from pathlib import Path
import pytest
import pandas as pd

from run_new_store_benefit_report import resolve_event_date, build_tables, FIELD_MAPPING
from audit_new_store_adversarial import (
    audit_dataframe,
    audit_excel_workbook,
    REQUIRED_FIELDS,
    parse_pct_or_float,
)


def test_resolve_event_date_default_yesterday():
    """验证未传参时自动推导为昨天的 YYYYMMDD 整数"""
    yesterday = datetime.now() - timedelta(days=1)
    expected = int(yesterday.strftime("%Y%m%d"))
    assert resolve_event_date(None) == expected
    assert resolve_event_date("") == expected


def test_resolve_event_date_formats():
    """验证传入各种合法日期格式均能规范化"""
    assert resolve_event_date("20260907") == 20260907
    assert resolve_event_date("2026-09-07") == 20260907
    assert resolve_event_date("2026/09/07".replace("/", "-")) == 20260907

    with pytest.raises(ValueError):
        resolve_event_date("invalid-date")


def test_required_fields_contract_completeness():
    """验证 32 项标准字段契约一致性"""
    assert len(REQUIRED_FIELDS) == 32
    assert len(FIELD_MAPPING) == 32
    mapping_chn_names = [chn for _, chn, _ in FIELD_MAPPING]
    assert REQUIRED_FIELDS == mapping_chn_names


def test_zero_division_defensiveness():
    """验证零销售、零品项等极端边界下的除零防卫与安全回退"""
    raw_df = pd.DataFrame([{
        "store_code": 9999999999,
        "store_name": "零数据测试店",
        "area_man_name": "测试大区",
        "prov_zone_man_nm": "测试省区",
        "region_man_name": "测试营运区",
        "jmlx": "直营",
        "is_test_region": "是",
        "item_num_ct": 0,
        "item_num_yxs_ct": 0,
        "sale_amt_ct": 0.0,
        "sale_profit_ct": 0.0,
        "lt90_inv_av_cost_amt_ct": 0.0,
        "lt90_sale_cost_ct": 0.0,
        "item_num_all": 0,
        "item_num_yxs_all": 0,
        "sale_amt_all": 0.0,
        "sale_profit_all": 0.0,
        "lt90_inv_av_cost_amt_all": 0.0,
        "lt90_sale_cost_all": 0.0,
        "store_passenger_flow": 0.0,
        "sjkysj": "2026-08-01",
    }])

    ongoing_kh = {
        9999999999: {
            "s_kh": "2026-08-06",
            "assess_target_total": 100000.0,
            "time_progress": 0.1,
            "cumulative_completion_rate": 0.0,
        }
    }

    df_og, _, _ = build_tables(raw_df, ongoing_kh, {}, ongoing_stores=[9999999999])
    assert len(df_og) == 1
    row = df_og.iloc[0]

    # 除零安全回退验证
    assert row["目录内商品动销率"] == 0.0
    assert row["目录内销售额占比"] == 0.0
    assert row["目录内毛利额占比"] == 0.0
    assert row["近90天日均客流"] == 0.0


def test_adversarial_audit_detects_violations():
    """验证对抗性审查门禁能准确拦截数学违规、时间进度错位等缺陷"""
    bad_data = pd.DataFrame([{
        "大区编码": 1000,
        "大区名称": "测试大区",
        "省区编码": 100,
        "省区名称": "测试省区",
        "营运区编码": 10,
        "营运区名称": "测试营运区",
        "门店编码": 123456,
        "门店名称": "违规样本店",
        "经营方式": "直营",
        "考核类型": "跟进中",
        "试点营运区": "是",
        "目录内商品数": 2000,
        "目录内有效动销商品数": 2100,  # 违规1：动销 > 品项数
        "目录内近90天折算日均销售额": 3000.0,
        "目录内近90天折算日均毛利额": 800.0,
        "目录内近90天日均库存成本": 10000.0,
        "目录内近90天日均销售成本": 2000.0,
        "全店商品数": 1800,           # 违规2：目录商品数 > 全店商品数
        "全店有效动销商品数": 1700,
        "全店近90天折算日均销售额": 2500.0,      # 违规3：目录销售额 > 全店销售额
        "全店近90天折算日均毛利额": 700.0,
        "全店近90天日均库存成本": 8000.0, # 违规4：目录库存成本 > 全店库存成本
        "全店近90天日均销售成本": 1800.0,
        "近90天日均客流": 150.0,
        "目录内商品动销率": 1.05,
        "目录内销售额占比": 1.20,
        "目录内毛利额占比": 1.14,
        "实际开业时间": "2026-08-01",
        "考核开始日期": "2026-08-06",
        "90天总指标": -100.0,         # 违规5：总指标 <= 0
        "时间进度": 1.5,              # 违规6：跟进中时间进度 > 1.05
        "累计达成率": 0.5,
    }])

    findings = audit_dataframe(bad_data, is_ongoing=True)
    assert len(findings) >= 5
    assert any("违反品项包含性" in f for f in findings)
    assert any("违反动销品项包含性" in f for f in findings)
    assert any("违反销售额包含性" in f for f in findings)
    assert any("违反库存成本包含性" in f for f in findings)
    assert any("90天总指标异常" in f for f in findings)
    assert any("时间进度越界" in f for f in findings)
