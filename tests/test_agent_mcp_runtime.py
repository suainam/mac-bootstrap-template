"""Normalized MCP desired-state and host adapter tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "agent_mcp_runtime.py"
SPEC = importlib.util.spec_from_file_location("agent_mcp_runtime", MODULE_PATH)
assert SPEC and SPEC.loader
runtime = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runtime
SPEC.loader.exec_module(runtime)


def inputs(**overrides):
    values = {
        "home": Path("/home/alice"),
        "bootstrap": Path("/repo"),
        "context7_command": "npx",
        "context7_key": "",
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": "",
        "no_proxy": "localhost,127.0.0.1,::1",
        "devspace_enabled": False,
        "devspace_url": "",
        "xapi_enabled": False,
    }
    values.update(overrides)
    return runtime.RuntimeInputs(**values)


def test_desired_servers_has_one_normalized_catalog():
    servers = runtime.desired_servers(inputs())
    assert list(servers) == [
        "context-mode",
        "codebase-memory-mcp",
        "agent-prompt-library",
        "x-docs",
        "context7",
    ]
    assert servers["context7"].command == "npx"
    assert servers["context7"].args == ("-y", "@upstash/context7-mcp")
    assert servers["x-docs"].transport == "remote"
    assert servers["codebase-memory-mcp"].tool_approvals == (
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


def test_optional_servers_are_resolved_from_runtime_inputs():
    servers = runtime.desired_servers(
        inputs(
            devspace_enabled=True,
            devspace_url="https://devspace.example/mcp",
            xapi_enabled=True,
        )
    )
    assert servers["devspace"].url == "https://devspace.example/mcp"
    assert servers["xapi"].command == "/repo/scripts/x-mcp-bridge.sh"
    assert servers["xapi"].startup_timeout_sec == 300


def test_context7_proxy_and_key_are_normalized_once():
    server = runtime.desired_servers(
        inputs(
            context7_key="secret",
            http_proxy="http://127.0.0.1:7897",
            https_proxy="http://127.0.0.1:7898",
            all_proxy="socks5://127.0.0.1:7897",
        )
    )["context7"]
    assert server.args[-2:] == ("--api-key", "secret")
    assert server.env["NODE_USE_ENV_PROXY"] == "1"
    assert server.env["HTTPS_PROXY"] == "http://127.0.0.1:7898"
    assert server.env["ALL_PROXY"] == "socks5://127.0.0.1:7897"


def test_json_host_adapter_preserves_unmanaged_state():
    current = {
        "theme": "dark",
        "mcpServers": {
            "unmanaged": {"command": "mine"},
            "devspace": {"url": "https://stale.example/mcp"},
        },
    }
    result = runtime.render_json_config(
        "claude", current, runtime.desired_servers(inputs())
    )
    assert result["theme"] == "dark"
    assert result["mcpServers"]["unmanaged"] == {"command": "mine"}
    assert "devspace" not in result["mcpServers"]
    assert result["mcpServers"]["x-docs"] == {"url": "https://docs.x.com/mcp"}
    assert result["mcpServers"]["context-mode"]["args"] == []


def test_opencode_adapter_uses_local_and_remote_shapes():
    result = runtime.render_json_config(
        "opencode", {"mcp": {}}, runtime.desired_servers(inputs())
    )
    assert result["mcp"]["context-mode"] == {
        "enabled": True,
        "type": "local",
        "command": ["context-mode"],
    }
    assert result["mcp"]["x-docs"] == {
        "enabled": True,
        "type": "remote",
        "url": "https://docs.x.com/mcp",
    }


def test_managed_server_names_include_optional_names():
    assert runtime.managed_server_names() == (
        "context-mode",
        "codebase-memory-mcp",
        "agent-prompt-library",
        "x-docs",
        "context7",
        "devspace",
        "xapi",
    )
