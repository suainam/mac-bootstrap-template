"""Deterministic Markdown projection for immutable structured summaries."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Iterable

from summary_contracts import SummaryDocument


ITEM_TYPE_LABELS = {
    "outcome": "成果",
    "decision": "决定",
    "risk": "风险",
    "action": "行动",
    "insight": "洞察",
}


def _wikilink(ref: str) -> str:
    normalized = ref.removesuffix(".md")
    alias = PurePosixPath(normalized).name
    return f"[[{normalized}|{alias}]]"


def _render_item(item: dict) -> list[str]:
    dimensions = " ".join(f"`{dimension}`" for dimension in item["dimensions"]) or "无"
    evidence = "、".join(f"`{group_id}`" for group_id in item["evidence_group_ids"])
    lines = [
        f"### {item['title']}",
        "",
        f"- **类型**：{ITEM_TYPE_LABELS[item['item_type']]}",
        f"- **维度**：{dimensions}",
        f"- **结论**：{item['conclusion']}",
        f"- **价值**：{item['value']}",
    ]
    if item.get("trend"):
        lines.append(f"- **趋势**：{item['trend']}")
    if item.get("period_change"):
        lines.append(f"- **周期变化**：{item['period_change']}")
    lines.extend(
        [
            f"- **证据**：{evidence}",
            f"- **置信度**：{float(item['confidence']):.0%}",
        ]
    )
    if item.get("supporting_item_ids"):
        support = "、".join(f"`{item_id}`" for item_id in item["supporting_item_ids"])
        lines.append(f"- **下层条目**：{support}")
    if item.get("lower_summary_refs"):
        refs = " ".join(_wikilink(ref) for ref in item["lower_summary_refs"])
        lines.append(f"- **下层摘要**：{refs}")
    lines.append("")
    return lines


def _section(lines: list[str], heading: str, items: Iterable[dict], *, empty: str = "无。") -> None:
    selected = list(items)
    lines.extend([f"## {heading}", ""])
    if not selected:
        lines.extend([empty, ""])
        return
    for item in selected:
        lines.extend(_render_item(item))


def _unique_lower_refs(items: Iterable[dict]) -> list[str]:
    return sorted({ref for item in items for ref in item.get("lower_summary_refs", [])})


def _frontmatter(data: dict, revision_id: str, input_digest: str) -> list[str]:
    return [
        "---",
        "type: summary",
        f"summary_level: {data['level']}",
        f"period: {data['period']}",
        "status: draft",
        "generated_by: data-hub",
        "indexing: excluded",
        "promotion_status: not_reviewed",
        f"contract_version: {data['contract_version']}",
        f"taxonomy_version: {data['taxonomy_version']}",
        f"revision_id: {revision_id}",
        f"input_digest: {input_digest}",
        "---",
        "",
        f"# {data['period']} {data['level'].title()} Summary",
        "",
    ]


def _render_daily(data: dict, lines: list[str]) -> None:
    items = data["items"]
    _section(lines, "今日结论", [], empty=data["headline"])
    _section(lines, "工作进展", (item for item in items if item["item_type"] in {"outcome", "decision"}))
    _section(lines, "风险与下一步", (item for item in items if item["item_type"] in {"risk", "action"}))
    _section(
        lines,
        "知识洞察",
        (item for item in items if item["item_type"] == "insight"),
        empty="> 今日无新增高价值洞察。",
    )
    evidence_ids = sorted({group_id for item in items for group_id in item["evidence_group_ids"]})
    lines.extend(["## 来源", "", *[f"- `{group_id}`" for group_id in evidence_ids], ""])


def _render_weekly(data: dict, lines: list[str]) -> None:
    items = data["items"]
    _section(lines, "本周结论", [], empty=data["headline"])
    _section(lines, "关键成果", (item for item in items if item["item_type"] == "outcome"))
    _section(lines, "决策与变化", (item for item in items if item["item_type"] == "decision"))
    _section(lines, "跨日趋势", (item for item in items if item.get("trend")))
    _section(lines, "未解风险", (item for item in items if item["item_type"] == "risk"))
    _section(lines, "下周重点", (item for item in items if item["item_type"] == "action"))
    _section(lines, "知识演进", (item for item in items if item["item_type"] == "insight"))
    dimensions = sorted({dimension for item in items for dimension in item["dimensions"]})
    lines.extend(["## 本周能力维度", "", " ".join(f"#{dimension}" for dimension in dimensions) or "无。", ""])
    lines.extend(["## Daily 索引", ""])
    refs = _unique_lower_refs(items)
    lines.extend([*[f"- {_wikilink(ref)}" for ref in refs], ""] if refs else ["无。", ""])


def _render_higher(data: dict, lines: list[str]) -> None:
    items = data["items"]
    _section(lines, "本期结论", [], empty=data["headline"])
    _section(lines, "跨期成果与关键决定", (item for item in items if item["item_type"] in {"outcome", "decision"}))
    _section(lines, "未解风险与后续重点", (item for item in items if item["item_type"] in {"risk", "action"}))
    _section(lines, "知识演进", (item for item in items if item["item_type"] == "insight"))
    lines.extend(["## 下层摘要索引", ""])
    refs = _unique_lower_refs(items)
    lines.extend([*[f"- {_wikilink(ref)}" for ref in refs], ""] if refs else ["无。", ""])


def render_summary_markdown(document: SummaryDocument, *, revision_id: str, input_digest: str) -> str:
    """Render only the supplied document; never fetch or infer source content."""

    data = document.to_dict()
    lines = _frontmatter(data, revision_id, input_digest)
    if data["level"] == "daily":
        _render_daily(data, lines)
    elif data["level"] == "weekly":
        _render_weekly(data, lines)
    else:
        _render_higher(data, lines)
    return "\n".join(lines).rstrip() + "\n"
