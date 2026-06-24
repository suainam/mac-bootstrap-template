#!/usr/bin/env python3
"""Render the managed Codex MCP block."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def proxy_block() -> str:
    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    if not http_proxy:
        return ""

    https_proxy = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or http_proxy
    )
    all_proxy = (
        os.environ.get("ALL_PROXY")
        or os.environ.get("all_proxy")
        or http_proxy
    )
    no_proxy = (
        os.environ.get("NO_PROXY")
        or os.environ.get("no_proxy")
        or "localhost,127.0.0.1,::1"
    )

    return f"""
[mcp_servers.context7.env]
NODE_USE_ENV_PROXY = "1"
HTTP_PROXY = "{http_proxy}"
HTTPS_PROXY = "{https_proxy}"
http_proxy = "{http_proxy}"
https_proxy = "{https_proxy}"
ALL_PROXY = "{all_proxy}"
all_proxy = "{all_proxy}"
NO_PROXY = "{no_proxy}"
no_proxy = "{no_proxy}"
""".strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context7-command", required=True)
    parser.add_argument("--context7-api-key")
    args = parser.parse_args()

    context7_args = []
    if args.context7_command == "npx":
        context7_args.extend(['"-y"', '"@upstash/context7-mcp"'])
    if args.context7_api_key:
        context7_args.extend(['"--api-key"', f'"{args.context7_api_key}"'])

    prompt_mcp_command = str(Path.home() / ".local/bin/agent-prompt-mcp")

    sections = [
        "# BEGIN MAC-BOOTSTRAP MANAGED MCPS",
        """
[mcp_servers.context-mode]
command = "context-mode"
args = []

[mcp_servers.context-mode.tools.ctx_stats]
approval_mode = "approve"

[mcp_servers.context-mode.tools.ctx_search]
approval_mode = "approve"

[mcp_servers.context-mode.tools.ctx_index]
approval_mode = "approve"

[mcp_servers.context-mode.tools.ctx_doctor]
approval_mode = "approve"
""".strip(),
        """
[mcp_servers.code-review-graph]
command = "code-review-graph"
args = ["serve"]

[mcp_servers.code-review-graph.tools.get_minimal_context_tool]
approval_mode = "approve"

[mcp_servers.code-review-graph.tools.traverse_graph_tool]
approval_mode = "approve"

[mcp_servers.code-review-graph.tools.get_review_context_tool]
approval_mode = "approve"

[mcp_servers.code-review-graph.tools.get_impact_radius_tool]
approval_mode = "approve"

[mcp_servers.code-review-graph.tools.get_architecture_overview_tool]
approval_mode = "approve"

[mcp_servers.code-review-graph.tools.list_communities_tool]
approval_mode = "approve"

[mcp_servers.code-review-graph.tools.list_flows_tool]
approval_mode = "approve"

[mcp_servers.code-review-graph.tools.get_hub_nodes_tool]
approval_mode = "approve"

[mcp_servers.code-review-graph.tools.list_graph_stats_tool]
approval_mode = "approve"

[mcp_servers.code-review-graph.tools.get_knowledge_gaps_tool]
approval_mode = "approve"

[mcp_servers.code-review-graph.tools.get_suggested_questions_tool]
approval_mode = "approve"

[mcp_servers.code-review-graph.tools.cross_repo_search_tool]
approval_mode = "approve"
""".strip(),
        f"""
[mcp_servers.agent-prompt-library]
command = "{prompt_mcp_command}"
args = []

[mcp_servers.agent-prompt-library.tools.search_prompts]
approval_mode = "approve"
""".strip(),
    ]

    context7_block = [
        f'[mcp_servers.context7]',
        f'command = "{args.context7_command}"',
        f'args = [{", ".join(context7_args)}]',
    ]
    sections.append("\n".join(context7_block))

    proxy = proxy_block()
    if proxy:
        sections.append(proxy)

    sections.append("# END MAC-BOOTSTRAP MANAGED MCPS")
    print("\n\n".join(sections))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
