#!/usr/bin/env python3
"""DataWorks 批量回刷通用编排（跨专题复用）.

能力：按时间窗切分 + 分区存在性跳过（断点续跑）+ 多表并发 INSERT + 倒序/正序执行。
专题只需提供 `build_sql(stat_date) -> str`（单日纯 CTE Multi-Table INSERT），无需复制并发/跳过逻辑。

用法示例（专题侧）::

    from dataworks_batch_backfill import generate_date_range, get_existing_partitions, run_batch

    QUARTERS = [(\"2026 Q3 (0701~0809)\", \"20260701\", \"20260809\"), ...]

    def build_sql(stat_date: int) -> str:
        return f\"WITH ... INSERT OVERWRITE ... PARTITION(stat_date={stat_date}) ...\"

    # 单批
    run_batch(\"2026 Q3\", \"20260701\", \"20260809\", build_sql,
              partition_tables=[\"ads_prov_region_stat_cata_trend_detail_df\", \"ads_prov_region_stat_cata_detail_df\"],
              odps_project=\"dsl_analysis\", workers=16)

    # 全量倒序
    for q_name, s, e in QUARTERS:
        run_batch(q_name, s, e, build_sql, partition_tables=[...], workers=16)

设计要点：
- 不使用 DataWorks DAG 逐日补数（3min/天），改用 MaxCompute SDK 直接提交，平均 ~6s/天。
- 不做单条 SQL 跨多日动态分区（$N \\times N$ 笛卡尔膨胀易 OOM），保持“单日单 SQL + 线程池并发”。
- 分区存在性通过 MaxCompute `table.partitions` 预检，失败自动重试由调用方决定是否中断。
"""

from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Callable


def generate_date_range(start_str: str, end_str: str) -> list[int]:
    """生成 [start, end] 闭区间的 YYYYMMDD int 列表，倒序（新→旧）返回便于优先验证新分区."""
    start_dt = datetime.strptime(start_str, "%Y%m%d")
    end_dt = datetime.strptime(end_str, "%Y%m%d")
    dates: list[str] = []
    cur = start_dt
    while cur <= end_dt:
        dates.append(cur.strftime("%Y%m%d"))
        # Use manual day increment to avoid importing timedelta at top-level complications
        from datetime import timedelta

        cur += timedelta(days=1)
    return [int(d) for d in reversed(dates)]


def get_existing_partitions(table_name: str, odps_project: str = "dsl_analysis") -> set[int]:
    """读取 MaxCompute 分区键 `stat_date` 的已存在分区集合."""
    from dataworks_snapshot import make_odps

    odps = make_odps(odps_project)
    table = odps.get_table(table_name)
    existing: set[int] = set()
    for p in table.partitions:
        name = getattr(p, "name", str(p))
        # partition name like "stat_date=20260819"
        if "stat_date=" in name:
            try:
                existing.add(int(name.split("stat_date=")[1].split("/")[0].split(",")[0]))
            except ValueError:
                continue
        elif "stat_date" in name and "=" in name:
            # fallback generic parse
            try:
                for kv in name.split("/"):
                    if kv.startswith("stat_date="):
                        existing.add(int(kv.split("=")[1]))
            except ValueError:
                continue
    return existing


def _execute_single_date(
    stat_date: int,
    sql_builder: Callable[[int], str],
    odps_project: str = "dsl_analysis",
    hints: dict | None = None,
) -> tuple[int, bool, float, str]:
    from dataworks_snapshot import make_odps

    odps = make_odps(odps_project)
    sql = sql_builder(stat_date)
    t0 = time.time()
    try:
        inst = odps.execute_sql(sql, hints=hints or {"odps.sql.hive.compatible": "true"})
        inst.wait_for_success()
        t1 = time.time()
        return (stat_date, True, t1 - t0, "OK")
    except Exception as e:
        t1 = time.time()
        return (stat_date, False, t1 - t0, str(e))


def run_batch(
    q_name: str,
    start_str: str,
    end_str: str,
    sql_builder: Callable[[int], str],
    partition_tables: list[str],
    odps_project: str = "dsl_analysis",
    workers: int = 8,
    force: bool = False,
    hints: dict | None = None,
) -> dict[str, int]:
    """执行单个时间窗的批量回刷。

    Args:
        q_name: 批次展示名（如 \"2026 Q3 (0701~0809)\"）。
        start_str/end_str: YYYYMMDD 闭区间。
        sql_builder: 专题提供的单日 SQL 构建函数 `f(stat_date)->sql`。
        partition_tables: 用于存在性预检的分区表列表（需均存在才算已完成）。
        odps_project: MaxCompute 项目名。
        workers: 并发线程数。
        force: 为 True 时不跳过已存在分区。
        hints: MaxCompute hints，默认 hive 兼容。

    Returns:
        {\"total\", \"success\", \"failed\", \"skipped\"} 统计。
    """
    dates = generate_date_range(start_str, end_str)
    print(f"\n{'=' * 70}")
    print(f"开始执行批次: {q_name} (范围: {start_str} ~ {end_str}, 共 {len(dates)} 天)")
    print(f"{'=' * 70}")

    if not force and partition_tables:
        # 取交集：所有表都已存在该分区才算已完成，避免 partial 误跳过
        existing_sets = [get_existing_partitions(t, odps_project) for t in partition_tables]
        existing_both = set.intersection(*existing_sets) if existing_sets else set()
        to_run = [d for d in dates if d not in existing_both]
        skipped = len(dates) - len(to_run)
        if skipped > 0:
            print(f"ℹ️ 自动跳过已存在分区: {skipped} 天 (待跑: {len(to_run)} 天)")
    else:
        to_run = dates
        skipped = 0
        if force:
            print("ℹ️ force 模式：不跳过任何分区")

    if not to_run:
        print(f"✅ 本批次所有 {len(dates)} 个分区均已存在，无需重复执行！")
        return {"total": len(dates), "success": len(dates), "failed": 0, "skipped": skipped}

    print(f"🚀 启动 {workers} 个并发线程向 MaxCompute 异步提交执行...")
    t_start = time.time()
    success_cnt = 0
    failed_cnt = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_execute_single_date, d, sql_builder, odps_project, hints): d for d in to_run
        }
        for f in as_completed(futures):
            d, ok, cost, msg = f.result()
            if ok:
                success_cnt += 1
                print(f"  [SUCCESS] {d} ({cost:.1f}s) - 累计成功: {success_cnt}/{len(to_run)}")
            else:
                failed_cnt += 1
                print(f"  [FAILED]  {d} ({cost:.1f}s) - 错误: {msg}")

    t_cost = time.time() - t_start
    avg = t_cost / len(to_run) if to_run else 0
    print(f"\n批次 {q_name} 完成: 成功 {success_cnt}, 失败 {failed_cnt}, 跳过 {skipped}, 耗时 {t_cost:.1f}s (平均 {avg:.1f}s/天)")
    return {"total": len(dates), "success": success_cnt + skipped, "failed": failed_cnt, "skipped": skipped}


# 可选：通用 CLI（专题可直接 `python shared/dataworks_batch_backfill.py --help` 查看参数说明）
def _cli() -> int:
    parser = argparse.ArgumentParser(description="DataWorks 通用批量回刷（需专题提供 SQL builder，CLI 仅作示例）")
    parser.add_argument("--demo", action="store_true", help="仅演示参数解析，不执行")
    return parser.parse_args() and 0


if __name__ == "__main__":
    raise SystemExit(_cli())
