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
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": "",
        "no_proxy": "localhost,127.0.0.1,::1",
    }
    values.update(overrides)
    return runtime.RuntimeInputs(**values)


def test_desired_servers_has_one_normalized_catalog():
    servers = runtime.desired_servers(inputs())
    assert list(servers) == [
        "context-mode",
        "codebase-memory-mcp",
        "context7",
    ]
    assert servers["context7"].command == "npx"
    assert servers["context7"].args == ("-y", "@upstash/context7-mcp")
    assert servers["context7"].host_commands["codex"] == (
        "/repo/scripts/context7-mcp-bridge.py"
    )
    assert servers["context7"].host_args["codex"] == ()
    assert servers["context-mode"].hosts == ("codex", "opencode")
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


def test_devspace_is_not_an_agent_mcp_server():
    servers = runtime.desired_servers(inputs())
    assert "devspace" not in servers
    assert "devspace" not in runtime.managed_server_names()
    assert "devspace" in runtime.retired_server_names()


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


def test_runtime_inputs_from_env_supports_lowercase_proxy():
    parsed = runtime.RuntimeInputs.from_env(
        bootstrap=Path("/repo"),
        context7_command="context7-mcp",
        environ={
            "HOME": "/home/bob",
            "http_proxy": "http://proxy",
        },
    )
    assert parsed.home == Path("/home/bob")
    assert parsed.https_proxy == "http://proxy"
    assert parsed.all_proxy == "http://proxy"
    assert parsed.no_proxy == "localhost,127.0.0.1,::1"


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
    assert "context-mode" not in result["mcpServers"]


@pytest.mark.parametrize("host,root_key", [("claude", "mcpServers"), ("opencode", "mcp")])
def test_render_removes_retired_server_aliases(host, root_key):
    current = {
        root_key: {
            "code-review-graph": {"command": "old"},
            "codebase-memory": {"command": "older"},
            "x-docs": {"url": "https://docs.x.com/mcp"},
            "xapi": {"command": "old-x-command"},
        }
    }
    desired = runtime.desired_servers(inputs())
    result = runtime.render_json_config(host, current, desired)
    assert "code-review-graph" not in result[root_key]
    assert "codebase-memory" not in result[root_key]
    assert "x-docs" not in result[root_key]
    assert "xapi" not in result[root_key]


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
    assert result["mcp"]["context-mode"] == {
        "enabled": True,
        "type": "local",
        "command": ["context-mode"],
    }


def test_render_removes_retired_devspace_from_agent_configs():
    claude = runtime.render_json_config(
        "claude", {"mcpServers": {"devspace": {"url": "https://old.example/mcp"}}}, runtime.desired_servers(inputs())
    )
    opencode = runtime.render_json_config(
        "opencode", {"mcp": {"devspace": {"url": "https://old.example/mcp"}}}, runtime.desired_servers(inputs())
    )
    assert "devspace" not in claude["mcpServers"]
    assert "devspace" not in opencode["mcp"]


def test_non_codex_context7_hosts_remain_keyless():
    desired = runtime.desired_servers(inputs())
    claude = runtime.render_json_config("claude", {}, desired)
    opencode = runtime.render_json_config("opencode", {}, desired)
    assert claude["mcpServers"]["context7"] == {
        "command": "npx",
        "args": ["-y", "@upstash/context7-mcp"],
    }
    assert opencode["mcp"]["context7"]["command"] == [
        "npx",
        "-y",
        "@upstash/context7-mcp",
    ]


def test_managed_server_names_are_agent_owned():
    assert runtime.managed_server_names() == (
        "context-mode",
        "codebase-memory-mcp",
        "context7",
    )


def test_codex_toml_is_rendered_from_normalized_specs():
    desired = runtime.desired_servers(
        inputs(
            http_proxy="http://127.0.0.1:7897",
        )
    )
    rendered = runtime.render_codex_toml(desired)
    assert rendered.startswith("# BEGIN MAC-BOOTSTRAP MANAGED MCPS")
    assert rendered.endswith("# END MAC-BOOTSTRAP MANAGED MCPS\n")
    assert 'enabled_tools = ["search_graph", "trace_path"' in rendered
    assert 'default_tools_approval_mode = "approve"' in rendered
    assert ".tools." not in rendered
    assert 'command = "/repo/scripts/context7-mcp-bridge.py"' in rendered
    assert '[mcp_servers.context7]\nenabled = true\ncommand = "/repo/scripts/context7-mcp-bridge.py"\nargs = []' in rendered
    assert '[mcp_servers.context7.env]' in rendered
    assert '[mcp_servers.devspace]' not in rendered


def test_codex_audit_accepts_cc_switch_stdio_projection():
    desired = runtime.desired_servers(inputs())
    config = runtime.parse_codex_toml(runtime.render_codex_toml(desired))

    # CC Switch records transport explicitly and omits optional empty args.
    server = config["mcp_servers"]["codebase-memory-mcp"]
    server["type"] = "stdio"
    del server["args"]
    del server["enabled"]

    assert runtime.audit_config("codex", config, desired) == []


def test_codex_audit_still_rejects_wrong_cc_switch_transport():
    desired = runtime.desired_servers(inputs())
    config = runtime.parse_codex_toml(runtime.render_codex_toml(desired))
    config["mcp_servers"]["codebase-memory-mcp"]["type"] = "http"

    assert [(issue.code, issue.server) for issue in runtime.audit_config("codex", config, desired)] == [
        ("server_mismatch", "codebase-memory-mcp")
    ]


def test_codex_audit_accepts_live_projection_without_optional_tool_policy():
    desired = runtime.desired_servers(inputs())
    config = {
        "mcp_servers": {
            "context-mode": {"command": "context-mode"},
            "codebase-memory-mcp": {"command": "codebase-memory-mcp"},
            "context7": {
                "command": "npx",
                "args": ["-y", "@upstash/context7-mcp"],
            },
        }
    }
    assert runtime.audit_config("codex", config, desired) == []


def test_codex_audit_rejects_explicit_wrong_tool_policy():
    desired = runtime.desired_servers(inputs())
    config = runtime.parse_codex_toml(runtime.render_codex_toml(desired))
    config["mcp_servers"]["codebase-memory-mcp"]["enabled_tools"] = ["unexpected"]
    assert [
        (issue.code, issue.server)
        for issue in runtime.audit_config("codex", config, desired)
    ] == [("server_mismatch", "codebase-memory-mcp")]


def test_policy_disables_optional_codex_servers_and_renders_profiles(tmp_path):
    policy_path = tmp_path / "mcp-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "version": 1,
                "default_enabled": {
                    "context-mode": True,
                    "context7": False,
                },
                "profiles": {"docs": ["context7"]},
            }
        )
    )
    policy = runtime.load_mcp_policy(policy_path)
    desired = runtime.apply_default_policy(
        runtime.desired_servers(
            inputs()
        ),
        policy,
    )
    assert desired["context-mode"].enabled is True
    assert desired["context7"].enabled is False


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
        ("retired_server", "devspace"),
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


def test_retired_devspace_is_reported_for_manual_cleanup():
    desired = runtime.desired_servers(inputs())
    config = runtime.render_json_config("claude", {}, desired)
    config["mcpServers"]["devspace"] = {"url": "https://old.example/mcp"}
    assert [(issue.code, issue.server) for issue in runtime.audit_config("claude", config, desired)] == [
        ("retired_server", "devspace")
    ]


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
    desired = runtime.desired_servers(inputs())
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
