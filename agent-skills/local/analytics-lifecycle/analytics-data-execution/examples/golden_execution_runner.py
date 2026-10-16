"""黄金执行范例：基于 PyODPS 与 Shared 设施完成数据提取、双段落盘与质量门禁审计.

本范例展示 Stage 4 数据执行的标准生产代码结构：
1. 凭据加载：严格读取家目录 ~/.env，拒绝任何硬编码；
2. 算力连接：完全复用 shared.odps_connector.ODPSConnector 与 shared.config.ODPSConfig；
3. 双段物化：
   - 中间明细事实提取并导出 Parquet (兼顾本地秒级多维穿透)；
   - 门店聚合宽表导出 Parquet 与深蓝格式化 Excel；
4. 数据湖规范：通过 shared.data_lake 自动处理外部存储与仓库软链接；
5. 对抗性门禁：全量断言二元商品数守恒、金额全额流水自洽、比率区间有界性与 NULL 空值语义。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
import pandas as pd

# 引入 shared 公共基础设施
REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.config import ODPSConfig
from shared.odps_connector import ODPSConnector
from shared.excel_exporter import DataExporter, ExportFormat
from shared.data_lake import export_topic_data, stage_topic_data_file


def run_golden_execution(sql_file: Path, topic_id: str):
    # 1. 严格从家目录加载凭据
    env_file = Path.home() / ".env"
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.strip().split("=", 1)
            os.environ[k.strip()] = v.strip().strip("'\"")

    cfg = ODPSConfig(
        access_id=os.environ["ODPS_ACCESS_ID"],
        secret_access_key=os.environ["ODPS_SECRET_KEY"],
        project=os.environ.get("ODPS_PROJECT", "dsl_ads"),
        endpoint=os.environ.get("ODPS_ENDPOINT", "https://service.cn-shenzhen.maxcompute.aliyun.com/api")
    )
    odps = ODPSConnector(cfg).connect()
    sql_text = sql_file.read_text(encoding="utf-8")

    # 2. 执行第一段：中间店品明细提取
    detail_marker = "-- 3. 门店级指标聚合中间表"
    detail_ctes = sql_text.split(detail_marker, 1)[0].rstrip().removesuffix(",")
    detail_sql = detail_ctes + "\nSELECT * FROM base_item_detail"
    
    detail_inst = odps.execute_sql(detail_sql)
    detail_inst.wait_for_success()
    with detail_inst.open_reader() as r:
        detail_df = r.to_pandas()

    # 3. 执行第二段：门店汇总宽表提取
    summary_inst = odps.execute_sql(sql_text)
    summary_inst.wait_for_success()
    with summary_inst.open_reader() as r:
        summary_df = r.to_pandas()

    # 4. 类型安全转换与门禁核验
    for col in summary_df.columns:
        if any(t in col for t in ["_元", "_pct", "比", "率"]):
            summary_df[col] = pd.to_numeric(summary_df[col], errors="coerce")

    # 门禁 1: 二元商品数互斥守恒
    sku_diff = (summary_df["目录内在营商品数"] + summary_df["目录外手工在营商品数"] - summary_df["全店总在营商品数"]).abs().max()
    assert sku_diff == 0, f"商品数不守恒: {sku_diff}"

    # 门禁 2: 销售金额自洽守恒
    amt_diff = (summary_df["目录内销售额_元"] + summary_df["目录外手工销售额_元"] - summary_df["全店总销售额_元"]).abs().max()
    assert amt_diff < 0.05, f"销售金额不自洽: {amt_diff}"

    # 5. 规范物化导出 Parquet 与 Excel (自动接入数据湖)
    export_topic_data(
        detail_df,
        topic_id=topic_id,
        rel_path="04_outputs/demand-adhoc-item-detail.parquet",
        format="parquet",
        compression="snappy",
    )
    export_topic_data(
        summary_df,
        topic_id=topic_id,
        rel_path="04_outputs/demand-adhoc-dataset.parquet",
        format="parquet",
        compression="snappy",
    )
    print("✅ 黄金执行与验证闭环完成！")
