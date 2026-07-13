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
    }
    values.update(overrides)
    return runtime.RuntimeInputs(**values)


def test_desired_servers_has_one_normalized_catalog():
    servers = runtime.desired_servers(inputs())
    assert list(servers) == [
        "context-mode",
        "codebase-memory-mcp",
        "agent-prompt-library",
        "context7",
    ]
    assert servers["context7"].command == "npx"
    assert servers["context7"].args == ("-y", "@upstash/context7-mcp")
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


def test_optional_devspace_server_is_resolved_from_runtime_inputs():
    servers = runtime.desired_servers(
        inputs(
            devspace_enabled=True,
            devspace_url="https://devspace.example/mcp",
        )
    )
    assert servers["devspace"].url == "https://devspace.example/mcp"


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


def test_audit_ignores_context7_secret_and_proxy_environment_drift():
    installed = runtime.desired_servers(
        inputs(context7_key="installed-secret", http_proxy="http://install-proxy")
    )
    audited = runtime.desired_servers(inputs())
    config = runtime.render_json_config("claude", {}, installed)
    assert runtime.audit_config("claude", config, audited) == []


@pytest.mark.parametrize(
    "bad_env",
    [
        {"MALICIOUS": "1"},
        {
            "NODE_USE_ENV_PROXY": "0",
            "HTTP_PROXY": "http://proxy",
            "HTTPS_PROXY": "http://proxy",
            "http_proxy": "http://proxy",
            "https_proxy": "http://proxy",
            "ALL_PROXY": "http://proxy",
            "all_proxy": "http://proxy",
            "NO_PROXY": "localhost",
            "no_proxy": "localhost",
        },
    ],
)
def test_audit_rejects_invalid_context7_proxy_environment(bad_env):
    desired = runtime.desired_servers(inputs())
    config = runtime.render_json_config("claude", {}, desired)
    config["mcpServers"]["context7"]["env"] = bad_env
    assert [(issue.code, issue.server) for issue in runtime.audit_config("claude", config, desired)] == [
        ("server_mismatch", "context7")
    ]


def test_audit_rejects_malformed_context7_api_key_argument():
    desired = runtime.desired_servers(inputs())
    config = runtime.render_json_config("claude", {}, desired)
    config["mcpServers"]["context7"]["args"].append("--api-key")
    assert [(issue.code, issue.server) for issue in runtime.audit_config("claude", config, desired)] == [
        ("server_mismatch", "context7")
    ]


def test_runtime_inputs_from_env_supports_lowercase_proxy_and_devspace():
    parsed = runtime.RuntimeInputs.from_env(
        bootstrap=Path("/repo"),
        context7_command="context7-mcp",
        environ={
            "HOME": "/home/bob",
            "http_proxy": "http://proxy",
            "DEVSPACE_MCP_ENABLE": "1",
            "DEVSPACE_MCP_URL": "https://devspace.example/mcp",
        },
    )
    assert parsed.home == Path("/home/bob")
    assert parsed.https_proxy == "http://proxy"
    assert parsed.all_proxy == "http://proxy"
    assert parsed.devspace_enabled is True


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
    assert "x-docs" not in result["mcpServers"]
    assert "context-mode" not in result["mcpServers"]


@pytest.mark.parametrize("host,root_key", [("claude", "mcpServers"), ("opencode", "mcp")])
def test_render_removes_retired_server_aliases(host, root_key):
    current = {
        root_key: {
            "code-review-graph": {"command": "old"},
            "codebase-memory": {"command": "older"},
        }
    }
    desired = runtime.desired_servers(inputs())
    result = runtime.render_json_config(host, current, desired)
    assert "code-review-graph" not in result[root_key]
    assert "codebase-memory" not in result[root_key]


def test_audit_reports_retired_server_alias():
    desired = runtime.desired_servers(inputs())
    config = runtime.render_json_config("claude", {}, desired)
    config["mcpServers"]["code-review-graph"] = {"command": "old"}
    assert [(issue.code, issue.server) for issue in runtime.audit_config("claude", config, desired)] == [
        ("retired_server", "code-review-graph")
    ]


@pytest.mark.parametrize("existing,expected", [({}, False), ({"skipSetup": True}, True), ({"skipSetup": False}, False)])
def test_reasonix_preserves_or_initializes_skip_setup(existing, expected):
    result = runtime.render_json_config("reasonix", existing, runtime.desired_servers(inputs()))
    assert result["skipSetup"] is expected


def test_opencode_adapter_uses_local_and_remote_shapes():
    result = runtime.render_json_config(
        "opencode", {"mcp": {}}, runtime.desired_servers(inputs())
    )
    assert result["mcp"]["codebase-memory-mcp"] == {
        "enabled": True,
        "type": "local",
        "command": ["codebase-memory-mcp"],
    }


def test_claude_remote_adapter_uses_http_transport_shape():
    result = runtime.render_json_config(
        "claude",
        {"mcpServers": {}},
        runtime.desired_servers(
            inputs(devspace_enabled=True, devspace_url="https://devspace.example/mcp")
        ),
    )
    assert result["mcpServers"]["devspace"] == {
        "type": "http",
        "url": "https://devspace.example/mcp",
    }


def test_managed_server_names_include_optional_names():
    assert runtime.managed_server_names() == (
        "context-mode",
        "codebase-memory-mcp",
        "agent-prompt-library",
        "context7",
        "devspace",
    )


def test_codex_toml_is_rendered_from_normalized_specs():
    desired = runtime.desired_servers(
        inputs(
            context7_key='a"b',
            http_proxy="http://127.0.0.1:7897",
            devspace_enabled=True,
            devspace_url="https://devspace.example/mcp",
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
    assert '[mcp_servers.x-docs]' not in rendered
    assert '[mcp_servers.xapi]' not in rendered


def test_policy_disables_optional_codex_servers_and_renders_profiles(tmp_path):
    policy_path = tmp_path / "mcp-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "version": 1,
                "default_enabled": {
                    "context-mode": True,
                    "context7": False,
                    "devspace": False,
                },
                "profiles": {"docs": ["context7"], "devspace": ["devspace"]},
            }
        )
    )
    policy = runtime.load_mcp_policy(policy_path)
    desired = runtime.apply_default_policy(
        runtime.desired_servers(
            inputs(devspace_enabled=True, devspace_url="https://devspace.example/mcp")
        ),
        policy,
    )
    assert desired["context-mode"].enabled is True
    assert desired["context7"].enabled is False
    assert desired["devspace"].enabled is False


def test_policy_rejects_unknown_managed_server(tmp_path):
    policy_path = tmp_path / "mcp-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "version": 1,
                "default_enabled": {"unknown": False},
                "profiles": {},
            }
        )
    )
    with pytest.raises(ValueError, match="unknown MCP names"):
        runtime.load_mcp_policy(policy_path)


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


def test_atomic_json_writer_replaces_target(tmp_path):
    target = tmp_path / "nested" / "config.json"
    runtime._write_json_atomically(target, {"value": "ok"})
    assert json.loads(target.read_text()) == {"value": "ok"}
    assert not list(target.parent.glob("*.tmp"))


def test_atomic_json_writer_cleans_temp_file_on_serialization_error(monkeypatch, tmp_path):
    target = tmp_path / "config.json"

    def fail_dump(*args, **kwargs):
        raise TypeError("cannot serialize")

    monkeypatch.setattr(runtime.json, "dump", fail_dump)
    with pytest.raises(TypeError, match="cannot serialize"):
        runtime._write_json_atomically(target, {"bad": object()})
    assert not target.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_main_render_codex_and_missing_audit(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent_mcp_runtime.py",
            "render-codex",
            "--bootstrap",
            "/repo",
            "--context7-command",
            "npx",
        ],
    )
    assert runtime.main() == 0
    assert "# BEGIN MAC-BOOTSTRAP MANAGED MCPS" in capsys.readouterr().out

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent_mcp_runtime.py",
            "audit",
            "--host",
            "codex",
            "--path",
            str(tmp_path / "missing.toml"),
            "--bootstrap",
            "/repo",
            "--context7-command",
            "npx",
        ],
    )
    assert runtime.main() == 1
    assert "missing_config host=codex" in capsys.readouterr().out


def test_main_audits_valid_and_duplicate_hook_codex(monkeypatch, capsys, tmp_path):
    desired = runtime.desired_servers(inputs())
    config = tmp_path / "config.toml"
    hooks = tmp_path / "hooks.json"
    hooks.write_text("{}\n")
    config.write_text(runtime.render_codex_toml(desired))
    argv = [
        "agent_mcp_runtime.py",
        "audit",
        "--host",
        "codex",
        "--path",
        str(config),
        "--hooks-path",
        str(hooks),
        "--bootstrap",
        "/repo",
        "--context7-command",
        "npx",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setenv("HOME", "/home/alice")
    for name in (
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "CONTEXT7_KEY",
        "DEVSPACE_MCP_ENABLE",
        "DEVSPACE_MCP_URL",
        "X_MCP_ENABLE",
    ):
        monkeypatch.delenv(name, raising=False)
    assert runtime.main() == 0
    assert capsys.readouterr().out == ""

    config.write_text(
        config.read_text()
        + '\n[[hooks.SessionStart]]\nmatcher = "startup"\n'
        + '[[hooks.SessionStart.hooks]]\ntype = "command"\ncommand = "echo ready"\n'
    )
    assert runtime.main() == 1
    assert "duplicate_hook_representation host=codex" in capsys.readouterr().out


def test_main_render_json_rejects_non_object_root(monkeypatch, tmp_path):
    target = tmp_path / "config.json"
    target.write_text("[]\n")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent_mcp_runtime.py",
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
    )
    with pytest.raises(ValueError, match="root must be an object"):
        runtime.main()
