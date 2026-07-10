#!/usr/bin/env python3
"""Normalized desired state for managed agent MCP servers."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Mapping


MANAGED_NAMES = (
    "context-mode",
    "codebase-memory-mcp",
    "agent-prompt-library",
    "x-docs",
    "context7",
    "devspace",
    "xapi",
)

CBM_TOOLS = (
    "search_graph",
    "trace_path",
    "get_code_snippet",
    "get_architecture",
    "query_graph",
    "search_code",
    "detect_changes",
    "index_repository",
    "list_projects",
    "get_graph_schema",
    "index_status",
    "manage_adr",
    "ingest_traces",
)

CONTEXT_MODE_TOOLS = ("ctx_stats", "ctx_search", "ctx_index", "ctx_doctor")


@dataclass(frozen=True)
class RuntimeInputs:
    home: Path
    bootstrap: Path
    context7_command: str
    context7_key: str = ""
    http_proxy: str = ""
    https_proxy: str = ""
    all_proxy: str = ""
    no_proxy: str = "localhost,127.0.0.1,::1"
    devspace_enabled: bool = False
    devspace_url: str = ""
    xapi_enabled: bool = False

    @classmethod
    def from_env(
        cls,
        *,
        bootstrap: Path,
        context7_command: str,
        environ: Mapping[str, str] | None = None,
    ) -> "RuntimeInputs":
        env = os.environ if environ is None else environ
        http_proxy = env.get("HTTP_PROXY") or env.get("http_proxy", "")
        return cls(
            home=Path(env.get("HOME", str(Path.home()))),
            bootstrap=bootstrap,
            context7_command=context7_command,
            context7_key=env.get("CONTEXT7_KEY", ""),
            http_proxy=http_proxy,
            https_proxy=env.get("HTTPS_PROXY") or env.get("https_proxy") or http_proxy,
            all_proxy=env.get("ALL_PROXY") or env.get("all_proxy") or http_proxy,
            no_proxy=env.get("NO_PROXY") or env.get("no_proxy") or "localhost,127.0.0.1,::1",
            devspace_enabled=env.get("DEVSPACE_MCP_ENABLE") == "1",
            devspace_url=env.get("DEVSPACE_MCP_URL", ""),
            xapi_enabled=env.get("X_MCP_ENABLE") == "1",
        )


@dataclass(frozen=True)
class ServerSpec:
    name: str
    transport: str
    command: str = ""
    args: tuple[str, ...] = ()
    url: str = ""
    env: Mapping[str, str] = field(default_factory=dict)
    startup_timeout_sec: int | None = None
    tool_approvals: tuple[str, ...] = ()


def managed_server_names() -> tuple[str, ...]:
    return MANAGED_NAMES


def desired_servers(inputs: RuntimeInputs) -> dict[str, ServerSpec]:
    context7_args: list[str] = []
    if inputs.context7_command == "npx":
        context7_args.extend(("-y", "@upstash/context7-mcp"))
    if inputs.context7_key:
        context7_args.extend(("--api-key", inputs.context7_key))

    context7_env: dict[str, str] = {}
    if inputs.http_proxy:
        context7_env = {
            "NODE_USE_ENV_PROXY": "1",
            "HTTP_PROXY": inputs.http_proxy,
            "HTTPS_PROXY": inputs.https_proxy or inputs.http_proxy,
            "http_proxy": inputs.http_proxy,
            "https_proxy": inputs.https_proxy or inputs.http_proxy,
            "ALL_PROXY": inputs.all_proxy or inputs.http_proxy,
            "all_proxy": inputs.all_proxy or inputs.http_proxy,
            "NO_PROXY": inputs.no_proxy,
            "no_proxy": inputs.no_proxy,
        }

    servers = {
        "context-mode": ServerSpec(
            "context-mode", "local", command="context-mode", tool_approvals=CONTEXT_MODE_TOOLS
        ),
        "codebase-memory-mcp": ServerSpec(
            "codebase-memory-mcp",
            "local",
            command="codebase-memory-mcp",
            tool_approvals=CBM_TOOLS,
        ),
        "agent-prompt-library": ServerSpec(
            "agent-prompt-library",
            "local",
            command=str(inputs.home / ".local/bin/agent-prompt-mcp"),
            tool_approvals=("search_prompts",),
        ),
        "x-docs": ServerSpec("x-docs", "remote", url="https://docs.x.com/mcp"),
        "context7": ServerSpec(
            "context7",
            "local",
            command=inputs.context7_command,
            args=tuple(context7_args),
            env=context7_env,
        ),
    }
    if inputs.devspace_enabled and inputs.devspace_url:
        servers["devspace"] = ServerSpec("devspace", "remote", url=inputs.devspace_url)
    if inputs.xapi_enabled:
        servers["xapi"] = ServerSpec(
            "xapi",
            "local",
            command=str(inputs.bootstrap / "scripts/x-mcp-bridge.sh"),
            startup_timeout_sec=300,
        )
    return servers


def adapt_server(host: str, spec: ServerSpec) -> dict[str, Any]:
    if host == "opencode":
        if spec.transport == "remote":
            return {"enabled": True, "type": "remote", "url": spec.url}
        result: dict[str, Any] = {
            "enabled": True,
            "type": "local",
            "command": [spec.command, *spec.args],
        }
    elif spec.transport == "remote":
        return {"url": spec.url}
    else:
        result = {"command": spec.command, "args": list(spec.args)}

    if spec.env:
        result["env"] = dict(spec.env)
    if spec.startup_timeout_sec is not None:
        result["startup_timeout_sec"] = spec.startup_timeout_sec
    return result


def render_json_config(
    host: str,
    existing: Mapping[str, Any],
    desired: Mapping[str, ServerSpec],
) -> dict[str, Any]:
    root_key = "mcp" if host == "opencode" else "mcpServers"
    result = deepcopy(dict(existing))
    current = result.get(root_key)
    servers = deepcopy(current) if isinstance(current, dict) else {}
    for name in MANAGED_NAMES:
        if name in desired:
            servers[name] = adapt_server(host, desired[name])
        else:
            servers.pop(name, None)
    result[root_key] = servers
    return result
