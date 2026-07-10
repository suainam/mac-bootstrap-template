"""Deterministic Markdown projection for immutable structured summaries."""

from __future__ import annotations

from summary_contracts import SummaryDocument


def _item_line(item: dict) -> str:
    tags = " ".join(f"#{dimension}" for dimension in item["dimensions"])
    evidence = ", ".join(item["evidence_group_ids"])
    return f"- **{item['title']}**：{item['conclusion']}（价值：{item['value']}；{tags}；evidence: {evidence}）"


def render_summary_markdown(document: SummaryDocument, *, revision_id: str, input_digest: str) -> str:
    """Render only the document supplied by synthesis; never infer or fetch content."""

    data = document.to_dict()
    frontmatter = [
        "---",
        f"summary_level: {data['level']}",
        f"period: {data['period']}",
        f"revision_id: {revision_id}",
        f"input_digest: {input_digest}",
        "---",
        "",
        f"# {data['level'].title()} Summary · {data['period']}",
        "",
        data["headline"],
        "",
    ]
    sections = [
        ("工作进展", [item for item in data["items"] if item["item_type"] != "insight"]),
        ("知识洞察", [item for item in data["items"] if item["item_type"] == "insight"]),
    ]
    lines = frontmatter
    for heading, items in sections:
        lines.extend([f"## {heading}", ""])
        if items:
            lines.extend(_item_line(item) for item in items)
        elif heading == "知识洞察":
            lines.append("今日无新增高价值洞察。")
        else:
            lines.append("无可验证的新增工作进展。")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
