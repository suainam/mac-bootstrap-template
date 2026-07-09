from __future__ import annotations

from pathlib import Path

import sys

CURRENT_DIR = Path(__file__).resolve().parent
DATA_HUB_DIR = CURRENT_DIR.parent / "agent" / "data-hub"
SCRIPTS_DIR = DATA_HUB_DIR / "scripts"
sys.path.insert(0, str(DATA_HUB_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

import knowledge_retrieval


def test_build_retrieval_packet_includes_llm_wiki_context(monkeypatch):
    monkeypatch.setattr(
        knowledge_retrieval,
        "build_llm_wiki_context",
        lambda client, *, query, include_daily=True: {
            "source": "llm_wiki",
            "query": query,
            "results": [{"path": "10_Periodic/Daily/2026-07-09.md"}],
            "graph_neighbors": [],
            "reviews": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(knowledge_retrieval, "make_llm_wiki_client", lambda: object())

    packet = knowledge_retrieval.build_retrieval_packet(
        task_goal="build summary",
        keywords=["weekly focus"],
        include_llm_wiki=True,
    )

    assert packet["llm_wiki_context"]["source"] == "llm_wiki"
    assert packet["llm_wiki_context"]["results"][0]["path"] == "10_Periodic/Daily/2026-07-09.md"
