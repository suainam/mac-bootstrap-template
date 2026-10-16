"""桑基图引擎：流转数据聚合、资金与品数 Ledger 流量守恒校验，以及高保真 SVG/PNG/HTML 渲染。

核心业务契约：
1. 节点与流向规范词表（8大流动）：
   - 稳定目录内 / 稳定目录外
   - 目录外转目录内 / 目录内转目录外
   - 新增目录内 / 新增目录外
   - 目录内汰换 / 目录外汰换
2. 严禁使用"损耗"，统一使用"汰换"；占比统一使用"%"。
3. 渲染前先执行 Ledger 闭环校验（源端流出总额 = 源端节点总额，终端流入总额 = 终端节点总额）。
"""

from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

logger = logging.getLogger(__name__)

SANKEY_STANDARD_FLOW_NAMES = [
    "稳定目录内",
    "稳定目录外",
    "目录外转目录内",
    "目录内转目录外",
    "新增目录内",
    "新增目录外",
    "目录内汰换",
    "目录外汰换",
]

FLOW_COLOR_MAP = {
    "stableInner": "#256f7d",
    "stableOuter": "#7a8896",
    "outerToInner": "#2a9d8f",
    "innerToOuter": "#c84c31",
    "newInner": "#7ecf9f",
    "newOuter": "#9b6ef3",
    "goneInner": "#e9a06b",
    "goneOuter": "#b97a5d",
}

# 布局几何常量
WIDTH = 1320
HEIGHT = 860
LEFT_X = 230
RIGHT_X = 1050
NODE_WIDTH = 30
TOP = 108
BOTTOM = 88
GAP = 28


def validate_sankey_ledger(dataset: dict[str, Any], tolerance: float = 1e-2) -> bool:
    """校验桑基图资金流向的 Ledger 守恒闭环。
    
    若提供 nodes 字典，则断言：
      - 每个源端节点的流出总量 == 节点定义金额 (误差 <= tolerance)
      - 每个终端节点的流入总量 == 节点定义金额 (误差 <= tolerance)
    """
    flows = dataset.get("flows", [])
    nodes = dataset.get("nodes")
    if not nodes:
        # 若未显式传入 nodes，从 flows 自身验证非空与正负方向
        for f in flows:
            if f.get("left", 0.0) < -tolerance or f.get("right", 0.0) < -tolerance:
                raise ValueError(f"Ledger flow value cannot be negative: {f}")
        return True

    left_sums: dict[str, float] = {}
    right_sums: dict[str, float] = {}

    for f in flows:
        from_node = f.get("from", "")
        to_node = f.get("to", "")
        l_val = float(f.get("left", 0.0))
        r_val = float(f.get("right", 0.0))
        left_sums[from_node] = left_sums.get(from_node, 0.0) + l_val
        right_sums[to_node] = right_sums.get(to_node, 0.0) + r_val

    for node_name, expected_val in nodes.items():
        exp = float(expected_val)
        if node_name in left_sums:
            actual = left_sums[node_name]
            if abs(actual - exp) > tolerance:
                raise ValueError(
                    f"Ledger imbalance at source node '{node_name}': expected {exp}, sum of flows {actual} (diff {actual - exp})"
                )
        if node_name in right_sums:
            actual = right_sums[node_name]
            if abs(actual - exp) > tolerance:
                raise ValueError(
                    f"Ledger imbalance at target node '{node_name}': expected {exp}, sum of flows {actual} (diff {actual - exp})"
                )

    return True


def _flow_value(summary: Any, year: int, is_content: int, flow_type: str, metric: str) -> float:
    """从分组聚合 DataFrame 中提取流转值。"""
    try:
        matched = summary[
            (summary["year_id"] == year)
            & (summary["is_content_item_1"] == is_content)
            & (summary["fl"] == flow_type)
        ]
        if matched.empty:
            return 0.0
        val = matched.iloc[0].get(metric, 0.0)
        return float(val or 0.0)
    except Exception:
        return 0.0


def build_sankey_dataset_from_summary(
    flow_summary: Any,
    previous_year: int,
    current_year: int,
    project_et_str: str,
) -> dict[str, Any]:
    """从流转明细聚合 DataFrame 生成标准格式的桑基图数据集。"""
    def make_flow(flow_id: str, name: str, from_node: str, to_node: str, values: tuple[float, float], color: str):
        return {
            "id": flow_id,
            "name": name,
            "from": from_node,
            "to": to_node,
            "left": round(values[0], 4),
            "right": round(values[1], 4),
            "color": color,
        }

    flows = [
        make_flow(
            "stableInner", "稳定目录内", f"{previous_year}目录内", f"{current_year}目录内",
            (_flow_value(flow_summary, previous_year, 1, "稳定", "sale_amt"), _flow_value(flow_summary, current_year, 1, "稳定", "sale_amt")),
            FLOW_COLOR_MAP["stableInner"],
        ),
        make_flow(
            "stableOuter", "稳定目录外", f"{previous_year}目录外", f"{current_year}目录外",
            (_flow_value(flow_summary, previous_year, 0, "稳定", "sale_amt"), _flow_value(flow_summary, current_year, 0, "稳定", "sale_amt")),
            FLOW_COLOR_MAP["stableOuter"],
        ),
        make_flow(
            "outerToInner", "目录外转目录内", f"{previous_year}目录外", f"{current_year}目录内",
            (_flow_value(flow_summary, previous_year, 0, "内外切换", "sale_amt"), _flow_value(flow_summary, current_year, 1, "内外切换", "sale_amt")),
            FLOW_COLOR_MAP["outerToInner"],
        ),
        make_flow(
            "innerToOuter", "目录内转目录外", f"{previous_year}目录内", f"{current_year}目录外",
            (_flow_value(flow_summary, previous_year, 1, "内外切换", "sale_amt"), _flow_value(flow_summary, current_year, 0, "内外切换", "sale_amt")),
            FLOW_COLOR_MAP["innerToOuter"],
        ),
        make_flow(
            "newInner", "新增目录内", f"{previous_year}新增目录内", f"{current_year}目录内",
            (0.0, _flow_value(flow_summary, current_year, 1, "新增", "sale_amt")),
            FLOW_COLOR_MAP["newInner"],
        ),
        make_flow(
            "newOuter", "新增目录外", f"{previous_year}新增目录外", f"{current_year}目录外",
            (0.0, _flow_value(flow_summary, current_year, 0, "新增", "sale_amt")),
            FLOW_COLOR_MAP["newOuter"],
        ),
        make_flow(
            "goneInner", "目录内汰换", f"{previous_year}目录内", f"{current_year}目录内汰换",
            (_flow_value(flow_summary, previous_year, 1, "消失", "sale_amt"), 0.0),
            FLOW_COLOR_MAP["goneInner"],
        ),
        make_flow(
            "goneOuter", "目录外汰换", f"{previous_year}目录外", f"{current_year}目录外汰换",
            (_flow_value(flow_summary, previous_year, 0, "消失", "sale_amt"), 0.0),
            FLOW_COLOR_MAP["goneOuter"],
        ),
    ]

    item_counts = {}
    for key, f_type, is_ct, yr in [
        ("new_inner", "新增", 1, current_year),
        ("new_outer", "新增", 0, current_year),
        ("gone_inner", "消失", 1, previous_year),
        ("gone_outer", "消失", 0, previous_year),
    ]:
        cnt = _flow_value(flow_summary, yr, is_ct, f_type, "item_cnt")
        item_counts[key] = int(cnt)

    dataset = {
        "flows": flows,
        "title": f"加盟店目录结构变化销售桑基图（{project_et_str}）",
        "amount_unit": "yi",
        "item_counts": item_counts,
    }
    return dataset


def _format_yi(value: float) -> str:
    yi = value / 100000000.0
    return f"{yi:.2f}亿"


def _format_flow_metric(value: float, total: float) -> str:
    pct = (value / total * 100) if total else 0
    return f"{_format_yi(value)} ({pct:.1f}%)"


def build_svg_from_dataset(dataset: dict[str, Any]) -> str:
    """将标准流转数据集渲染成高保真双列 SVG 矢量图。"""
    flows = dataset.get("flows", [])
    item_counts = dataset.get("item_counts", {})
    left_total = sum(f.get("left", 0.0) for f in flows if f.get("from", "").endswith("目录内") or f.get("from", "").endswith("目录外"))
    right_total = sum(f.get("right", 0.0) for f in flows if f.get("to", "").endswith("目录内") or f.get("to", "").endswith("目录外"))
    
    # 保证左右布局基准不为 0
    ref_total = max(left_total, right_total, 1.0)
    avail_h = HEIGHT - TOP - BOTTOM - GAP
    scale = avail_h / ref_total

    # 提取关键节点流量高度
    left_h = max(left_total * scale, 10.0)
    right_h = max(right_total * scale, 10.0)
    
    # 简化的精美双列 SVG 渲染器
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="100%" height="100%">',
        '<defs>',
        '  <style>',
        '    .title { font-family: "PingFang SC", "Source Han Sans SC", sans-serif; font-size: 22px; font-weight: bold; fill: #1f2937; }',
        '    .subtitle { font-family: "PingFang SC", sans-serif; font-size: 13px; fill: #6b7280; }',
        '    .node-title { font-family: "PingFang SC", sans-serif; font-size: 15px; font-weight: bold; fill: #111827; }',
        '    .label { font-family: "PingFang SC", sans-serif; font-size: 12px; fill: #374151; }',
        '    .band { fill-opacity: 0.72; transition: fill-opacity 0.2s; }',
        '    .band:hover { fill-opacity: 0.90; }',
        '  </style>',
        '</defs>',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#ffffff"/>',
        f'<text x="50" y="55" class="title">{dataset.get("title", "加盟店目录结构变化销售桑基图")}</text>',
        f'<text x="50" y="80" class="subtitle">口径：按照组货口径统计推广区域可比同比门店销售流转情况（单位：亿元）</text>',
    ]

    # 左侧节点与右侧节点柱体
    svg_parts.append(f'<rect x="{LEFT_X}" y="{TOP}" width="{NODE_WIDTH}" height="{left_h:.1f}" fill="#1F4E78" rx="4"/>')
    svg_parts.append(f'<text x="{LEFT_X - 15}" y="{TOP + 25}" text-anchor="end" class="node-title">基期销售盘</text>')
    svg_parts.append(f'<text x="{LEFT_X - 15}" y="{TOP + 48}" text-anchor="end" class="label">{_format_yi(left_total)}</text>')

    svg_parts.append(f'<rect x="{RIGHT_X}" y="{TOP}" width="{NODE_WIDTH}" height="{right_h:.1f}" fill="#2E75B6" rx="4"/>')
    svg_parts.append(f'<text x="{RIGHT_X + NODE_WIDTH + 15}" y="{TOP + 25}" text-anchor="start" class="node-title">本期销售盘</text>')
    svg_parts.append(f'<text x="{RIGHT_X + NODE_WIDTH + 15}" y="{TOP + 48}" text-anchor="start" class="label">{_format_yi(right_total)}</text>')

    # 绘制流转曲带
    cur_y_l = float(TOP)
    cur_y_r = float(TOP)
    mid_x1 = LEFT_X + NODE_WIDTH + (RIGHT_X - (LEFT_X + NODE_WIDTH)) * 0.45
    mid_x2 = LEFT_X + NODE_WIDTH + (RIGHT_X - (LEFT_X + NODE_WIDTH)) * 0.55

    for f in flows:
        l_amt = float(f.get("left", 0.0))
        r_amt = float(f.get("right", 0.0))
        h_l = l_amt * scale
        h_r = r_amt * scale
        color = f.get("color", "#64748b")
        name = f.get("name", "")

        y_l1 = cur_y_l
        y_l2 = cur_y_l + h_l
        y_r1 = cur_y_r
        y_r2 = cur_y_r + h_r

        if h_l > 0.5 or h_r > 0.5:
            path = (
                f"M {LEFT_X + NODE_WIDTH} {y_l1:.1f} "
                f"C {mid_x1:.1f} {y_l1:.1f}, {mid_x2:.1f} {y_r1:.1f}, {RIGHT_X} {y_r1:.1f} "
                f"L {RIGHT_X} {y_r2:.1f} "
                f"C {mid_x2:.1f} {y_r2:.1f}, {mid_x1:.1f} {y_l2:.1f}, {LEFT_X + NODE_WIDTH} {y_l2:.1f} Z"
            )
            svg_parts.append(f'<path d="{path}" fill="{color}" class="band"><title>{name}: {l_amt:.2f} -> {r_amt:.2f}</title></path>')

        # 标注文本（在中间位置呈现）
        if h_l > 12 or h_r > 12:
            label_y = (y_l1 + y_r1) / 2 + 5
            svg_parts.append(f'<text x="{(LEFT_X + RIGHT_X) / 2:.1f}" y="{label_y:.1f}" text-anchor="middle" class="label" fill="#1e293b" font-weight="500">{name}</text>')

        cur_y_l += h_l
        cur_y_r += h_r

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def render_sankey_html(dataset: dict[str, Any]) -> str:
    """渲染独立可交互的单文件 HTML 桑基汇报卡片。"""
    svg = build_svg_from_dataset(dataset)
    title = dataset.get("title", "加盟店目录结构变化销售桑基图")
    flows = dataset.get("flows", [])
    
    table_rows = []
    for f in flows:
        table_rows.append(
            f"<tr><td><span style='display:inline-block;width:12px;height:12px;border-radius:2px;background:{f.get('color')};margin-right:8px;'></span>{f.get('name')}</td>"
            f"<td>{_format_yi(f.get('left', 0.0))}</td>"
            f"<td>{_format_yi(f.get('right', 0.0))}</td></tr>"
        )
    table_body = "\n".join(table_rows)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", sans-serif; background: #f8fafc; margin: 0; padding: 24px; color: #0f172a; }}
        .card {{ background: #ffffff; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); padding: 24px; max-width: 1360px; margin: 0 auto; }}
        .grid {{ display: grid; grid-template-columns: 1fr 340px; gap: 24px; margin-top: 16px; }}
        .table-wrap {{ background: #f1f5f9; border-radius: 8px; padding: 16px; height: fit-content; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th, td {{ padding: 8px 10px; text-align: left; border-bottom: 1px solid #e2e8f0; }}
        th {{ color: #64748b; font-weight: 600; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="grid">
            <div style="overflow-x: auto;">{svg}</div>
            <div class="table-wrap">
                <h3 style="margin-top:0;font-size:15px;color:#1e293b;">流转明细汇总</h3>
                <table>
                    <thead>
                        <tr><th>流向名称</th><th>基期金额</th><th>本期金额</th></tr>
                    </thead>
                    <tbody>
                        {table_body}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>"""


def render_sankey_png(svg_path: Path) -> Path | None:
    """利用 macOS Swift 原生能力将 SVG 转换为高清 PNG 供 Excel 锚点嵌入。"""
    png_path = svg_path.with_suffix(".png")
    swift_code = (
        "import Cocoa; import Foundation; "
        "let args=CommandLine.arguments; "
        "guard args.count == 3, let image=NSImage(contentsOfFile: args[1]), "
        "let tiff=image.tiffRepresentation, let rep=NSBitmapImageRep(data: tiff), "
        "let data=rep.representation(using: .png, properties: [:]) else { exit(1) }; "
        "try! data.write(to: URL(fileURLWithPath: args[2]))"
    )
    module_cache = Path("/tmp/product_strategy_swift_module_cache")
    module_cache.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["swift", "-e", swift_code, str(svg_path), str(png_path)],
        env={**os.environ, "SWIFT_MODULECACHE_PATH": str(module_cache)},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not png_path.is_file():
        detail = (result.stderr or result.stdout or "unknown swift rendering error").strip()
        logger.warning("Could not embed Sankey PNG: %s", detail)
        return None
    return png_path
