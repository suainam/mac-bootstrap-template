#!/usr/bin/env python3
"""DataWorks 工作流节点快照拉取脚本（增量/断点续传，可复用于任意工作流）.

用法:
  python dataworks_snapshot.py \
      --project-id 175690 --env PROD \
      --workflow-id 10002569451 \
      --node-ids 10002569455,10002869149 \
      --cache /tmp/wf_cache.json \
      --schemas-cache /tmp/wf_schemas.json \
      --out report.md

特性:
- 断点续传: 每节点拉完立即原子写 cache；中断重跑跳过已完成节点。
- 增量: 远端 ModifyTime 未变则跳过 GetNodeCode/IO 调用。
- 归属表 = 节点内写入的目标表（INSERT / CTAS）。
- 表结构来自 MaxCompute 实际元数据，手工规范化拼装标准 DDL。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alibabacloud_dataworks_public20200518.client import Client
from alibabacloud_dataworks_public20200518 import models as dw
from alibabacloud_tea_openapi import models as open_api_models
from odps import ODPS
from workflow_snapshot_core import (
    NodeTableAnalysis,
    analyze_node,
    build_table_ddl,
    extract_drop_tables,
    render_mermaid_topology,
    sort_owned_by_node,
)

CST = timezone(timedelta(hours=8))


def ts(ms: int | float | None) -> str:
    return datetime.fromtimestamp((ms or 0) / 1000, CST).strftime("%Y-%m-%d %H:%M:%S")


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def make_dw_client() -> Client:
    from dataworks_lineage import load_env_credentials

    ak, sk, dw_ep, _ = load_env_credentials()
    return Client(open_api_models.Config(
        access_key_id=ak, access_key_secret=sk, endpoint=dw_ep))


def make_odps(project: str) -> ODPS:
    from dataworks_lineage import load_env_credentials

    ak, sk, _dw_ep, odps_ep = load_env_credentials()
    return ODPS(ak, sk, project=project, endpoint=odps_ep)


# ---------------------------------------------------------------------------
# DataWorks pulling
# ---------------------------------------------------------------------------

def pull_node(client: Client, node_id: int, env: str) -> dict:
    node = client.get_node(
        dw.GetNodeRequest(node_id=node_id, project_env=env)
    ).body.to_map().get("Data", {})
    code = ""
    try:
        raw = client.get_node_code(
            dw.GetNodeCodeRequest(node_id=node_id, project_env=env)
        ).body.to_map().get("Data", "")
        code = raw if isinstance(raw, str) else ""
    except Exception as e:  # noqa: BLE001 - keep snapshot going on single failure
        code = f"<code error: {e}>"
    ios: dict[str, list] = {}
    for io in ("input", "output"):
        try:
            r = client.list_node_input_or_output(
                dw.ListNodeInputOrOutputRequest(
                    node_id=node_id, project_env=env, io_type=io)
            ).body.to_map()
            ios[io] = [x.get("Data") for x in (r.get("Data") or [])
                       if isinstance(x, dict)]
        except Exception:  # noqa: BLE001
            ios[io] = []
    return {
        "name": node.get("NodeName"),
        "program_type": node.get("ProgramType"),
        "cron": node.get("CronExpress"),
        "owner": node.get("OwnerId"),
        "description": node.get("Description"),
        "create_time": node.get("CreateTime"),
        "modify_time": node.get("ModifyTime"),
        "deploy_date": node.get("DeployDate"),
        "param_values": node.get("ParamValues"),
        "code": code,
        "inputs": ios.get("input", []),
        "outputs": ios.get("output", []),
    }


def pull_nodes_incremental(
    client: Client,
    node_ids: list[int],
    env: str,
    cache: dict,
    force: bool,
    cache_path: Path,
) -> tuple[int, int]:
    """Returns (pulled, skipped). Checkpoints cache after every node."""
    pulled = skipped = 0
    for nid in node_ids:
        key = str(nid)
        cached = cache.get(key)
        if cached and not force:
            try:
                node = client.get_node(
                    dw.GetNodeRequest(node_id=nid, project_env=env)
                ).body.to_map().get("Data", {})
                remote_mt = node.get("ModifyTime")
                if cached.get("modify_time") == remote_mt:
                    print(f"[skip] {nid} unchanged", flush=True)
                    skipped += 1
                    continue
                print(f"[stale] {nid} re-pull "
                      f"({cached.get('modify_time')} -> {remote_mt})", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"[warn] {nid} refresh-check failed ({e}); keep cached",
                      flush=True)
                skipped += 1
                continue
        print(f"[pull] {nid} ...", flush=True)
        cache[key] = pull_node(client, nid, env)
        save_json(cache_path, cache)  # checkpoint after every node
        pulled += 1
        time.sleep(0.1)
    return pulled, skipped


# ---------------------------------------------------------------------------
# MaxCompute schema sidecar
# ---------------------------------------------------------------------------

def fetch_table_schemas(odps_project_map: dict[str, ODPS],
                        tables: set[str]) -> tuple[dict, list]:
    """Fetch real schema per table; returns ({full_name: schema}, errors)."""
    schemas: dict[str, dict] = {}
    errors: list[tuple[str, str]] = []
    for full in sorted(tables):
        proj_name, tbl = full.split(".", 1)
        odps = odps_project_map.get(proj_name)
        if odps is None:
            errors.append((full, f"no credentials/project mapping for {proj_name}"))
            continue
        try:
            t = odps.get_table(tbl)
            s = t.table_schema
            schemas[full] = {
                "project": proj_name,
                "table": tbl,
                "comment": t.comment or "",
                "columns": [
                    {"name": c.name, "type": str(c.type), "comment": c.comment or ""}
                    for c in s.simple_columns
                ],
                "partitions": [
                    {"name": p.name, "type": str(p.type), "comment": p.comment or ""}
                    for p in getattr(s, "partitions", [])
                ],
            }
            print(f"[schema ok] {full}", flush=True)
        except Exception as e:  # noqa: BLE001
            errors.append((full, str(e)[:150]))
            print(f"[schema ERR] {full}: {str(e)[:100]}", flush=True)
    return schemas, errors


def build_schemas_ddl(schemas: dict) -> dict[str, str]:
    """table full name -> assembled CREATE TABLE ddl."""
    ddls: dict[str, str] = {}
    for full in sorted(schemas):
        info = schemas[full]
        ddls[full] = build_table_ddl(
            table_name=full,
            comment=info.get("comment", ""),
            columns=info["columns"],
            partitions=info["partitions"],
        )
    return ddls


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def render_report(cache: dict, meta: dict, out_path: Path,
                  schemas: dict, ddl_map: dict[str, str]) -> None:
    node_ids: list[int] = meta["node_ids"]
    owned_all: set[str] = set()
    analyses: dict[str, NodeTableAnalysis] = {}
    for nid in node_ids:
        a = analyze_node(cache[str(nid)]["code"], owned_all=None)
        owned_all |= a.written_targets
        analyses[str(nid)] = a
    # second pass with global owned set for external classification
    for nid in node_ids:
        analyses[str(nid)] = analyze_node(cache[str(nid)]["code"], owned_all=owned_all)

    lines: list[str] = []
    lines.append(f"# 工作流 {meta['workflow_id']} 生产版本快照 ({meta['date']})")
    lines.append("")
    lines.append(f"> 工作空间 projectId: {meta['project_id']}")
    lines.append(f"> 环境: {meta['env']} / 发布日期: {meta['deploy_date']}")
    lines.append(f"> 拉取时间: {meta['pulled_at']}")
    lines.append("> 数据来源: DataWorks OpenAPI + MaxCompute 实际表结构")
    lines.append("")

    # ---- 一、节点概览 ----
    lines.append("## 一、节点概览")
    lines.append("")
    lines.append("| 序号 | NodeId | 节点名称 | 类型 | 产出表数 | ModifyTime |")
    lines.append("|---|---|---|---|---|---|")
    for idx, nid in enumerate(node_ids, 1):
        e = cache[str(nid)]
        a = analyses[str(nid)]
        lines.append(
            f"| {idx} | {nid} | {e['name']} | {e['program_type']} "
            f"| {len(a.written_targets)} | {ts(e['modify_time'])} |"
        )
    lines.append("")

    # ---- 二、归属表结构（按节点顺序、表名升序）----
    lines.append("## 二、产出表结构（show create table 等价）")
    ordered = sort_owned_by_node(node_ids, {k: v.written_targets for k, v in analyses.items()})
    for key, tables in ordered:
        e = cache[key]
        lines.append(f"\n### 节点 {key}: {e['name']}")
        for t in tables:
            lines.append(f"\n#### {t}")
            if t in ddl_map:
                lines.append("")
                lines.append("```sql")
                lines.append(ddl_map[t])
                lines.append("```")
            else:
                lines.append("\n> 未获取到线上表结构（表不存在或无权限）")
    lines.append("")

    # ---- 三、拓扑图 ----
    lines.append("## 三、工作流拓扑与表血缘")
    lines.append("")
    labels = {str(n): cache[str(n)]["name"] or str(n) for n in node_ids}
    mermaid = render_mermaid_topology(node_ids, analyses, labels)
    lines.append("```mermaid")
    lines.extend(mermaid)
    lines.append("```")
    lines.append("")

    # ---- 四、外部数据源表 ----
    lines.append("## 四、引用的外部数据源表")
    lines.append("")
    lines.append("| 数据库.表名 | 被引用节点 |")
    lines.append("|---|---|")
    ext_usage: dict[str, list[str]] = {}
    for nid in node_ids:
        for s in analyses[str(nid)].external_sources:
            ext_usage.setdefault(s, []).append(str(nid))
    for t in sorted(ext_usage):
        lines.append(f"| {t} | {', '.join(ext_usage[t])} |")
    lines.append("")

    # ---- 五、各节点 SQL 与元数据 ----
    lines.append("## 五、各节点完整 SQL 与元数据")
    for nid in node_ids:
        e = cache[str(nid)]
        a = analyses[str(nid)]
        lines.append(f"\n### 节点 {nid}: {e['name']}\n")
        lines.append(f"- ProgramType: {e['program_type']}")
        if e["description"]:
            lines.append(f"- Description: {e['description']}")
        lines.append(f"- ModifyTime: {ts(e['modify_time'])}")
        lines.append(f"- ParamValues: `{e['param_values']}`")
        if a.written_targets:
            lines.append(f"- 产出表: {', '.join(sorted(a.written_targets))}")
        drops = extract_drop_tables(e["code"]) & owned_all
        if drops:
            lines.append(f"- DROP 的归属表: {', '.join(sorted(drops))}")
        lines.append("\n```sql")
        lines.append(e["code"])
        lines.append("```")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-id", type=int, default=175690)
    ap.add_argument("--env", default="PROD", choices=["PROD", "DEV"])
    ap.add_argument("--workflow-id", type=int, required=True)
    ap.add_argument("--node-ids", required=True, help="逗号分隔节点 ID")
    ap.add_argument("--cache", required=True, help="断点续传缓存 JSON")
    ap.add_argument("--schemas-cache", help="表结构 sidecar JSON（断点续传）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--force-refresh", action="store_true")
    args = ap.parse_args()

    node_ids = [int(x) for x in args.node_ids.split(",") if x.strip()]
    cache = load_json(Path(args.cache))
    schemas_cache = load_json(Path(args.schemas_cache)) if args.schemas_cache else {}

    client = make_dw_client()
    pulled, skipped = pull_nodes_incremental(
        client, node_ids, args.env, cache, args.force_refresh,
        cache_path=Path(args.cache))

    # classify ownership across all nodes
    owned_all: set[str] = set()
    for nid in node_ids:
        inserts = analyze_node(cache[str(nid)]["code"]).written_targets
        owned_all |= inserts

    # fetch schemas for all written tables missing from sidecar
    need = {t for t in owned_all if t not in schemas_cache}
    if need:
        projects: dict[str, ODPS] = {}
        for full in need:
            proj = full.split(".", 1)[0]
            if proj not in projects:
                projects[proj] = make_odps(proj)
        fetched, _errors = fetch_table_schemas(projects, need)
        schemas_cache.update(fetched)
        if args.schemas_cache:
            save_json(Path(args.schemas_cache), schemas_cache)

    ddl_map = build_schemas_ddl(schemas_cache)

    deploy_dates = [cache[str(n)].get("deploy_date") for n in node_ids if cache.get(str(n))]
    deploy_date = max((d for d in deploy_dates if d), default=None)
    meta = {
        "workflow_id": args.workflow_id,
        "project_id": args.project_id,
        "env": args.env,
        "date": datetime.now(CST).strftime("%Y-%m-%d"),
        "pulled_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "deploy_date": ts(deploy_date) if deploy_date else "",
        "node_ids": node_ids,
    }
    render_report(cache, meta, Path(args.out), schemas_cache, ddl_map)
    print(f"done: pulled={pulled} skipped={skipped} total={len(node_ids)}")
    print(f"report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
