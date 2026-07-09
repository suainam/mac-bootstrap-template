from __future__ import annotations

from pathlib import Path

import sys

CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR.parent / "agent" / "data-hub"))

from llm_wiki_context import build_llm_wiki_context


class FakeClient:
    def search(self, query: str, *, limit: int = 8):
        assert query == "weekly focus"
        assert limit == 8
        return [{"path": "10_Periodic/Daily/2026-07-09.md", "title": "2026-07-09", "score": 0.91}]

    def graph(self, path=None):
        return {"neighbors": [{"path": "wiki/projects/data-hub.md", "score": 0.77}]}

    def reviews(self, limit: int = 10):
        assert limit == 10
        return [{"id": "review-1", "title": "Check summary drift"}]


def test_build_llm_wiki_context_merges_search_graph_and_reviews():
    packet = build_llm_wiki_context(FakeClient(), query="weekly focus", include_daily=True)

    assert packet["source"] == "llm_wiki"
    assert packet["query"] == "weekly focus"
    assert packet["results"][0]["path"] == "10_Periodic/Daily/2026-07-09.md"
    assert packet["graph_neighbors"][0]["path"] == "wiki/projects/data-hub.md"
    assert packet["reviews"][0]["id"] == "review-1"
