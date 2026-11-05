"""案例：PyODPS 高效抽取 15万+ 行数据并导出为标准格式化 Excel.

要点：
1. 从项目配置加载已授权计算项目；
2. open_reader 读取结果，示例在内存汇总；
3. 调用 format_season_months 格式化环形跨年时间；
4. 采用 openpyxl 导出；调用方负责临时文件验证和原子发布。
"""

import sys
from pathlib import Path
import pandas as pd

from shared.odps_connector import ODPSConnector
from shared.config import ODPSConfig


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from format_circular_months import format_season_months


def run_export(sql: str, output_excel_path: Path):
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
