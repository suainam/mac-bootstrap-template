"""Normalized MCP desired-state and host adapter tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


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
    assert "context-mode" not in result["mcpServers"]


def test_opencode_adapter_uses_local_and_remote_shapes():
    result = runtime.render_json_config(
        "opencode", {"mcp": {}}, runtime.desired_servers(inputs())
    )
    assert result["mcp"]["codebase-memory-mcp"] == {
        "enabled": True,
        "type": "local",
        "command": ["codebase-memory-mcp"],
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


def test_codex_toml_is_rendered_from_normalized_specs():
    desired = runtime.desired_servers(
        inputs(
            context7_key='a"b',
            http_proxy="http://127.0.0.1:7897",
            devspace_enabled=True,
            devspace_url="https://devspace.example/mcp",
            xapi_enabled=True,
        )
    )
    rendered = runtime.render_codex_toml(desired)
    assert rendered.startswith("# BEGIN MAC-BOOTSTRAP MANAGED MCPS")
    assert rendered.endswith("# END MAC-BOOTSTRAP MANAGED MCPS\n")
    assert '[mcp_servers.codebase-memory-mcp.tools.search_graph]' in rendered
    assert 'approval_mode = "approve"' in rendered
    assert 'args = ["-y", "@upstash/context7-mcp", "--api-key", "a\\\"b"]' in rendered
    assert '[mcp_servers.context7.env]' in rendered
    assert '[mcp_servers.devspace]' in rendered
    assert 'startup_timeout_sec = 300' in rendered


def test_render_json_cli_preserves_unmanaged_keys_and_replaces_file(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text(
        json.dumps({"theme": "dark", "mcpServers": {"mine": {"command": "mine"}}})
    )
    result = subprocess.run(
        [
            sys.executable,
            str(MODULE_PATH),
            "render-json",
            "--host",
            "claude",
            "--path",
            str(target),
            "--bootstrap",
            "/repo",
            "--context7-command",
            "npx",
        ],
        capture_output=True,
        text=True,
        env={"HOME": "/home/alice"},
    )
    assert result.returncode == 0, result.stderr
    rendered = json.loads(target.read_text())
    assert rendered["theme"] == "dark"
    assert rendered["mcpServers"]["mine"] == {"command": "mine"}
    assert rendered["mcpServers"]["codebase-memory-mcp"]["command"] == "codebase-memory-mcp"
    assert not list(tmp_path.glob("*.tmp"))


def test_semantic_audit_reports_stable_issue_codes():
    desired = runtime.desired_servers(inputs())
    config = runtime.render_json_config("claude", {}, desired)
    del config["mcpServers"]["codebase-memory-mcp"]
    config["mcpServers"]["context7"]["command"] = "wrong"
    config["mcpServers"]["devspace"] = {"url": "https://stale.example/mcp"}
    config["mcpServers"]["mine"] = {"command": "unmanaged"}
    issues = runtime.audit_config("claude", config, desired)
    assert [(issue.code, issue.server) for issue in issues] == [
        ("missing_server", "codebase-memory-mcp"),
        ("server_mismatch", "context7"),
        ("stale_managed_server", "devspace"),
    ]


def test_audit_distinguishes_missing_executable_from_semantic_drift():
    desired = runtime.desired_servers(inputs())
    config = runtime.parse_codex_toml(runtime.render_codex_toml(desired))
    issues = runtime.audit_config(
        "codex",
        config,
        desired,
        executable_resolver=lambda command: None if command == "context-mode" else command,
    )
    assert [(issue.code, issue.server) for issue in issues] == [
        ("missing_executable", "context-mode")
    ]


def test_remote_oauth_server_is_not_classified_as_broken():
    desired = runtime.desired_servers(
        inputs(devspace_enabled=True, devspace_url="https://devspace.example/mcp")
    )
    config = runtime.render_json_config("claude", {}, desired)
    assert runtime.audit_config("claude", config, desired) == []


def test_codex_audit_detects_duplicate_hook_representation():
    desired = runtime.desired_servers(inputs())
    config = runtime.parse_codex_toml(
        runtime.render_codex_toml(desired)
        + '\n[[hooks.SessionStart]]\nmatcher = "startup|resume"\n'
        + '[[hooks.SessionStart.hooks]]\ntype = "command"\ncommand = "echo ready"\n'
    )
    issues = runtime.audit_config(
        "codex", config, desired, external_hooks_present=True
    )
    assert [issue.code for issue in issues] == ["duplicate_hook_representation"]


@pytest.mark.parametrize("host", ["claude", "opencode", "pi", "reasonix", "antigravity"])
def test_every_json_host_round_trips_through_semantic_audit(host):
    desired = runtime.desired_servers(
        inputs(devspace_enabled=True, devspace_url="https://devspace.example/mcp")
    )
    config = runtime.render_json_config(host, {"unmanaged": True}, desired)
    assert config["unmanaged"] is True
    assert runtime.audit_config(host, config, desired) == []
