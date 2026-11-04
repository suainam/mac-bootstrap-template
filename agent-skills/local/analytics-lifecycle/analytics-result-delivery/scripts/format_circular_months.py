"""环形跨年时间区间智能解析工具函数."""

from typing import Iterable


def format_season_months(mons: Iterable[int | str] | None) -> str:
    """将月份序列（如 [1, 2, 10, 11, 12]）解析为业务规范区间（如 '10月-次年2月'）。

    规则：
    1. 12 个月全覆盖返回 '全年'；
    2. 空集合返回 '未配置'；
    3. 识别环形跨年起点（12月跨向1月），输出 'X月-次年Y月'；
    4. 年内连续区间输出 'X月-Y月'，单月输出 'X月'；
    5. 多个区间以 ', ' 逗号分隔。
    """
    if not mons:
        return "未配置"

    mons_list = sorted(list(set(int(m) for m in mons)))
    month_set = set(mons_list)

    if len(month_set) == 12:
        return "全年"

    # 在环形表盘 1..12 上寻找断点作为区间起点
    starts = [m for m in mons_list if (12 if m == 1 else m - 1) not in month_set]
    if not starts:
        starts = [mons_list[0]]

    intervals: list[tuple[int, int, int]] = []
    for s in starts:
        curr = s
        length = 0
        while curr in month_set:
            length += 1
            curr = 1 if curr == 12 else curr + 1
            if length > 12:
                break
        end = 12 if curr == 1 else curr - 1
        intervals.append((s, end, length))

    parts: list[str] = []
    for s, e, length in intervals:
        if length == 1:
            parts.append(f"{s}月")
        else:
            if s > e:  # 跨年区间
                parts.append(f"{s}月-次年{e}月")
            else:  # 年内区间
                parts.append(f"{s}月-{e}月")

    return ", ".join(parts)
