from __future__ import annotations

from typing import Any


def build_llm_wiki_context(client, *, query: str, include_daily: bool = True) -> dict[str, Any]:
    results = client.search(query, limit=8)
    if include_daily:
        filtered = results
    else:
        filtered = [
            row for row in results if not str(row.get("path", "")).startswith("10_Periodic/Daily/")
        ]
    return {
        "source": "llm_wiki",
        "query": query,
        "results": filtered,
        "graph_neighbors": client.graph().get("neighbors", []),
        "reviews": client.reviews(limit=10),
        "warnings": [],
    }
