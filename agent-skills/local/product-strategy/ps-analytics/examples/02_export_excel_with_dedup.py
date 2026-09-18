"""案例：PyODPS 高效抽取 15万+ 行数据并导出为标准格式化 Excel.

要点：
1. 环境变量加载与项目队列加速 (dsl_ads)；
2. open_reader 流式分块解析，控制内存占用；
3. 调用 format_season_months 格式化环形跨年时间；
4. 采用 openpyxl 引擎一次性原子写入。
"""

import os
import sys
from pathlib import Path
import pandas as pd

from shared.odps_connector import ODPSConnector
from shared.config import ODPSConfig


def format_season_months(mons) -> str:
    if not mons:
        return "未配置"
    mons = sorted(list(set(int(m) for m in mons)))
    month_set = set(mons)
    if len(month_set) == 12:
        return "全年"

    starts = [m for m in mons if (12 if m == 1 else m - 1) not in month_set]
    if not starts:
        starts = [mons[0]]

    intervals = []
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

    parts = []
    for s, e, length in intervals:
        if length == 1:
            parts.append(f"{s}月")
        else:
            if s > e:
                parts.append(f"{s}月-次年{e}月")
            else:
                parts.append(f"{s}月-{e}月")
    return ", ".join(parts)


def run_export(sql: str, output_excel_path: Path):
    # 1. 切换至高性能计算项目
    os.environ["ODPS_PROJECT"] = "dsl_ads"
    cfg = ODPSConfig()
    odps = ODPSConnector(cfg).connect()

    print("Submitting ODPS SQL query...")
    inst = odps.execute_sql(sql)
    print(f"ODPS Instance ID: {inst.id}. Downloading...")

    records = []
    with inst.open_reader() as reader:
        count = 0
        for r in reader:
            records.append({
                "大区名称": r["大区名称"],
                "省区名称": r["省区名称"],
                "营运区名称": r["营运区名称"],
                "门店编码": str(r["门店编码"]) if r["门店编码"] is not None else "",
                "门店名称": r["门店名称"],
                "商品编码": str(r["商品编码"]) if r["商品编码"] is not None else "",
                "商品名称": r["商品名称"],
                "是否目录内": r["是否目录内"],
                "原因大类": r["原因大类"],
                "原因子类": r["原因子类"],
                "季节开始-结束月份": format_season_months(r["在季月份集合"]),
            })
            count += 1
            if count % 50000 == 0:
                print(f"  Processed {count} rows...")

    print(f"Total downloaded: {len(records)} rows.")
    df = pd.DataFrame(records)

    output_excel_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Writing to Excel: {output_excel_path}...")
    with pd.ExcelWriter(output_excel_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="数据明细", index=False)

    size_mb = output_excel_path.stat().st_size / (1024 * 1024)
    print(f"Export successful: {output_excel_path} ({size_mb:.2f} MB)")
