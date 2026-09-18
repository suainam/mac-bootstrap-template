"""DataWorks 数据血缘与工作流拉取工具.

支持：
1. 递归查询 MaxCompute / DataWorks 表的上下游数据血缘 (Upstream / Downstream)。
2. 生成 Markdown 依赖列表与 Mermaid 流程图。
3. CLI 快速查询：python dataworks_lineage.py --table <table_name> [--direction up|down] [--depth N]
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Dict, List, Set

from alibabacloud_dataworks_public20200518 import models as dataworks_models
from alibabacloud_dataworks_public20200518.client import Client
from alibabacloud_tea_openapi import models as open_api_models


def load_env_credentials() -> tuple[str, str, str, str]:
    """从环境变量或已知 .env 文件加载阿里云 AK/SK 与 DataWorks / ODPS Endpoints."""
    ak = os.environ.get("ODPS_ACCESS_ID") or os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID")
    sk = (
        os.environ.get("ODPS_SECRET_KEY")
        or os.environ.get("ODPS_SECRET_ACCESS_KEY")
        or os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
    )
    dw_ep = os.environ.get("DATAWORKS_ENDPOINT") or "dataworks.cn-shenzhen.aliyuncs.com"
    odps_ep = os.environ.get("ODPS_ENDPOINT")

    env_paths = [
        Path.cwd() / ".env",
        Path.home() / ".env",
        Path.home() / "work/projects/www/marimo/merchandise/.env",
    ]
    for ep in env_paths:
        if ep.exists():
            for line in ep.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k_str = k.strip()
                    val = v.strip().strip('"').strip("'")
                    if k_str in ("ODPS_ACCESS_ID", "ALIBABA_CLOUD_ACCESS_KEY_ID") and not ak:
                        ak = val
                    elif k_str in ("ODPS_SECRET_KEY", "ODPS_SECRET_ACCESS_KEY", "ALIBABA_CLOUD_ACCESS_KEY_SECRET") and not sk:
                        sk = val
                    elif k_str == "ODPS_ENDPOINT" and not odps_ep:
                        odps_ep = val
                    elif k_str == "DATAWORKS_ENDPOINT" and not os.environ.get("DATAWORKS_ENDPOINT"):
                        dw_ep = val

    if not ak or not sk:
        raise RuntimeError("未找到有效的 ODPS/DataWorks 访问密钥 (ODPS_ACCESS_ID / ODPS_SECRET_KEY)")

    return ak, sk, dw_ep, odps_ep or "https://service.cn-shenzhen.maxcompute.aliyun.com/api"


def get_dataworks_client(
    ak: str | None = None,
    sk: str | None = None,
    endpoint: str | None = None,
) -> Client:
    """初始化 DataWorks OpenAPI 客户端."""
    if not ak or not sk or not endpoint:
        default_ak, default_sk, default_endpoint, _odps = load_env_credentials()
        ak = ak or default_ak
        sk = sk or default_sk
        endpoint = endpoint or default_endpoint

    config = open_api_models.Config(
        access_key_id=ak,
        access_key_secret=sk,
        endpoint=endpoint,
    )
    return Client(config)


def normalize_table_guid(table_name_or_guid: str, default_project: str = "dsl_ai") -> str:
    """将多种格式的表名规范化为 DataWorks TableGuid (odps.<project>.<table_name>)."""
    table_str = table_name_or_guid.strip()
    if table_str.startswith("odps."):
        return table_str

    parts = table_str.split(".")
    if len(parts) == 1:
        return f"odps.{default_project}.{parts[0]}"
    if len(parts) == 2:
        return f"odps.{parts[0]}.{parts[1]}"
    return table_str


class LineageTracer:
    """递归追踪表级血缘并生成依赖图."""

    def __init__(self, client: Client | None = None):
        self.client = client or get_dataworks_client()

    def get_direct_lineage(self, table_guid: str, direction: str = "up") -> List[Dict[str, Any]]:
        """获取单个表的直接上游或下游节点."""
        req = dataworks_models.GetMetaTableLineageRequest(
            table_guid=table_guid,
            direction=direction.lower(),
            page_size=100,
        )
        try:
            resp = self.client.get_meta_table_lineage(req)
            data_block = resp.body.to_map().get("Data", {})
            entities = data_block.get("DataEntityList", []) or []
            return [
                {
                    "table_name": ent.get("TableName"),
                    "table_guid": ent.get("TableGuid"),
                }
                for ent in entities
                if ent.get("TableGuid")
            ]
        except Exception:
            return []

    def trace_lineage_recursive(
        self,
        root_table: str,
        direction: str = "up",
        max_depth: int = 3,
    ) -> Dict[str, Any]:
        """递归追踪指定深度的血缘关系."""
        root_guid = normalize_table_guid(root_table)
        visited: Set[str] = set()
        edges: List[tuple[str, str]] = []
        nodes: Set[str] = {root_guid}

        def _traverse(current_guid: str, current_depth: int):
            if current_depth >= max_depth or current_guid in visited:
                return
            visited.add(current_guid)

            direct_nodes = self.get_direct_lineage(current_guid, direction=direction)
            for node in direct_nodes:
                target_guid = node["table_guid"]
                nodes.add(target_guid)
                if direction == "up":
                    edges.append((target_guid, current_guid))  # target -> current
                else:
                    edges.append((current_guid, target_guid))  # current -> target
                _traverse(target_guid, current_depth + 1)

        _traverse(root_guid, 0)

        return {
            "root_guid": root_guid,
            "direction": direction,
            "max_depth": max_depth,
            "nodes": sorted(list(nodes)),
            "edges": list(dict.fromkeys(edges)),  # 去重保持顺序
        }

    @staticmethod
    def to_mermaid(lineage_data: Dict[str, Any]) -> str:
        """将血缘拓扑转换为 Mermaid 流程图代码."""
        root = lineage_data["root_guid"]
        edges = lineage_data["edges"]
        nodes = lineage_data["nodes"]

        def _clean_id(guid: str) -> str:
            return guid.replace(".", "_").replace("-", "_")

        def _short_label(guid: str) -> str:
            parts = guid.split(".")
            if len(parts) == 3 and parts[0] == "odps":
                return f"{parts[1]}.{parts[2]}"
            return guid

        lines = ["```mermaid", "flowchart LR"]
        for node in nodes:
            nid = _clean_id(node)
            nlabel = _short_label(node)
            if node == root:
                lines.append(f'    {nid}["★ {nlabel}"]:::highlight')
            else:
                lines.append(f'    {nid}["{nlabel}"]')

        for src, dst in edges:
            lines.append(f"    {_clean_id(src)} --> {_clean_id(dst)}")

        lines.append("    classDef highlight fill:#f96,stroke:#333,stroke-width:2px;")
        lines.append("```")
        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="DataWorks MaxCompute 表血缘查询工具")
    parser.add_argument("--table", required=True, help="表名，支持 project.table 或完整 guid")
    parser.add_argument("--direction", choices=["up", "down"], default="up", help="追踪方向: up (上游), down (下游)")
    parser.add_argument("--depth", type=int, default=2, help="递归追踪深度，默认为 2")
    parser.add_argument("--mermaid", action="store_true", help="是否输出 Mermaid 流程图")

    args = parser.parse_args()
    tracer = LineageTracer()
    result = tracer.trace_lineage_recursive(
        root_table=args.table,
        direction=args.direction,
        max_depth=args.depth,
    )

    print(f"\n==================== 表血缘追踪结果 [{args.direction.upper()}] ====================")
    print(f"目标表: {result['root_guid']}")
    print(f"涉及表总数: {len(result['nodes'])}")
    print(f"依赖关系数: {len(result['edges'])}")
    print("\n--- 依赖关系列表 ---")
    for src, dst in result["edges"]:
        print(f"  {src}  --->  {dst}")

    if args.mermaid or True:
        print("\n--- Mermaid 拓扑图 ---")
        print(LineageTracer.to_mermaid(result))


if __name__ == "__main__":
    main()
