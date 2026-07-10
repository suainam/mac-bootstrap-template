#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
DATA_HUB_DIR = CURRENT_DIR.parent
if str(DATA_HUB_DIR) not in sys.path:
    sys.path.insert(0, str(DATA_HUB_DIR))

from data_hub_config import get_runtime_config


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "-", value.strip()).strip("-").lower()
    return slug or "summary-item"


def resolve_vault_root(summary_path: Path) -> Path:
    resolved = summary_path.resolve()
    if "70_Summaries" in resolved.parts:
        index = resolved.parts.index("70_Summaries")
        return Path(*resolved.parts[:index])
    return get_runtime_config().paths.vault_dir


def render_promoted_note(summary_path: Path, vault_root: Path, item: dict[str, str]) -> str:
    candidate_type = item["candidate_type"]
    note_type = "adr" if candidate_type == "adr" else "knowledge-card"
    title = item["title"]
    return "\n".join(
        [
            "---",
            f"type: {note_type}",
            "status: active",
            f"promoted_from: {summary_path.relative_to(vault_root)}",
            f"promotion_reason: {item['promotion_reason']}",
            "---",
            "",
            f"# {title}",
            "",
            item["content"].strip(),
            "",
        ]
    )


def promote_summary_items(summary_path: Path, selections: list[dict[str, str]]) -> list[str]:
    vault_root = resolve_vault_root(summary_path)
    outputs: list[str] = []
    for item in selections:
        candidate_type = item["candidate_type"]
        if candidate_type not in {"adr", "card"}:
            raise ValueError(f"unsupported summary promotion type: {candidate_type}")
        folder = "ADR" if candidate_type == "adr" else "Cards"
        target = vault_root / "40_Knowledge" / folder / f"{summary_path.stem}-{slugify(item['title'])}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text(render_promoted_note(summary_path, vault_root, item), encoding="utf-8")
        outputs.append(str(target.relative_to(vault_root)))
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote human-selected summary items into 40_Knowledge.")
    parser.add_argument("summary_path")
    parser.add_argument("--selections-json", required=True, help="Path to a JSON array of selected promotion items")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    selections = json.loads(Path(args.selections_json).read_text(encoding="utf-8"))
    outputs = promote_summary_items(Path(args.summary_path), selections)
    print(json.dumps({"outputs": outputs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
