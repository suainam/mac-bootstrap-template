"""自动化测试套件：验证 ps-analytics 核心工具函数与解析算法."""

import pytest
from format_circular_months import format_season_months


def test_empty_months():
    assert format_season_months([]) == "未配置"
    assert format_season_months(None) == "未配置"


def test_full_year():
    assert format_season_months(list(range(1, 13))) == "全年"


def test_cross_year_circular_months():
    # 典型秋冬跨年: [1, 2, 10, 11, 12] -> 10月-次年2月
    assert format_season_months([1, 2, 10, 11, 12]) == "10月-次年2月"
    # 跨至 1 月: [1, 9, 10, 11, 12] -> 9月-次年1月
    assert format_season_months([1, 9, 10, 11, 12]) == "9月-次年1月"
    # 跨至 3 月: [1, 2, 3, 10, 11, 12] -> 10月-次年3月
    assert format_season_months([1, 2, 3, 10, 11, 12]) == "10月-次年3月"


def test_within_year_months():
    # 夏季连续: [5, 6, 7, 8] -> 5月-8月
    assert format_season_months([5, 6, 7, 8]) == "5月-8月"
    # 秋冬未跨年: [10, 11, 12] -> 10月-12月
    assert format_season_months([10, 11, 12]) == "10月-12月"
    # 初春未跨年: [1, 2, 3] -> 1月-3月
    assert format_season_months([1, 2, 3]) == "1月-3月"


def test_multiple_intervals():
    # 两个不连续区间
    assert format_season_months([1, 2, 5, 6, 11, 12]) == "5月-6月, 11月-次年2月"


if __name__ == "__main__":
    pytest.main([__file__])
