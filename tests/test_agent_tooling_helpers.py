"""Unit tests for Python helpers extracted from install-agent-tooling.sh."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load_module(name: str, rel_path: str):
    path = ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


check_python_syntax = load_module("check_python_syntax", "scripts/check-python-syntax.py")
render_codex_mcp_block = load_module("render_codex_mcp_block", "scripts/render-codex-mcp-block.py")
run_doctor_checks = load_module("run_doctor_checks", "scripts/run-doctor-checks.py")
sync_codex_mcp_config = load_module("sync_codex_mcp_config", "scripts/sync-codex-mcp-config.py")


def test_strip_managed_sections_removes_managed_tables_only():
    text = """
model = "gpt-5"

[mcp_servers.context-mode]
command = "old"

[mcp_servers.context-mode.tools.ctx_search]
approval_mode = "approve"

[other]
value = 1
""".strip()
    stripped = sync_codex_mcp_config.strip_managed_sections(text)
    assert '[mcp_servers.context-mode]' not in stripped
    assert '[mcp_servers.context-mode.tools.ctx_search]' not in stripped
    assert 'model = "gpt-5"' in stripped
    assert '[other]' in stripped


def test_build_output_adds_managed_block_after_existing_content():
    out = sync_codex_mcp_config.build_output('model = "gpt-5"\n', "# BLOCK\nvalue = 1\n")
    assert out.startswith('model = "gpt-5"\n\n')
    assert out.endswith("# BLOCK\nvalue = 1\n")


def test_strip_managed_sections_resets_skip_on_next_table():
    text = """
[mcp_servers.context7.env]
HTTP_PROXY = "http://127.0.0.1:7897"

[user]
name = "alice"
""".strip()
    stripped = sync_codex_mcp_config.strip_managed_sections(text)
    assert '[mcp_servers.context7.env]' not in stripped
    assert '[user]' in stripped


def test_sync_codex_main_writes_from_cli_args(tmp_path):
    config = tmp_path / "config.toml"
    block = tmp_path / "block.toml"
    config.write_text('model = "gpt-5"\n')
    block.write_text("# BEGIN\nx = 1\n# END\n")
    old_argv = sys.argv
    try:
        sys.argv = ["sync-codex-mcp-config.py", str(config), str(block)]
        rc = sync_codex_mcp_config.main()
    finally:
        sys.argv = old_argv
    assert rc == 0
    assert "# BEGIN\nx = 1\n# END\n" in config.read_text()


def test_proxy_block_empty_without_proxy(monkeypatch):
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    assert render_codex_mcp_block.proxy_block() == ""


def test_proxy_block_prefers_explicit_env(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:7897")
    monkeypatch.setenv("NO_PROXY", "localhost")
    block = render_codex_mcp_block.proxy_block()
    assert 'HTTP_PROXY = "http://127.0.0.1:7897"' in block
    assert 'ALL_PROXY = "socks5://127.0.0.1:7897"' in block
    assert 'NO_PROXY = "localhost"' in block


def test_render_codex_main_npx_with_api_key(monkeypatch, capsys):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7897")
    old_argv = sys.argv
    try:
        sys.argv = [
            "render-codex-mcp-block.py",
            "--context7-command",
            "npx",
            "--context7-api-key",
            "abc",
        ]
        rc = render_codex_mcp_block.main()
    finally:
        sys.argv = old_argv
    out = capsys.readouterr().out
    assert rc == 0
    assert 'command = "npx"' in out
    assert 'args = ["-y", "@upstash/context7-mcp", "--api-key", "abc"]' in out
    assert '[mcp_servers.context7.env]' in out


def test_parse_brewfile_groups_entries(tmp_path):
    brewfile = tmp_path / "Brewfile"
    brewfile.write_text('brew "git"\ncask "ghostty"\nnpm "context-mode"\n')
    parsed = run_doctor_checks.parse_brewfile(brewfile)
    assert parsed == {"brew": ["git"], "cask": ["ghostty"], "npm": ["context-mode"]}


def test_run_stdout_and_brew_list(monkeypatch):
    assert run_doctor_checks.run_stdout("python3", "-c", "print('alpha')") == "alpha"
    monkeypatch.setattr(run_doctor_checks, "run_stdout", lambda *args: "git\njq")
    assert run_doctor_checks.brew_list("--formula") == {"git", "jq"}


def test_has_app_and_has_npm(monkeypatch, tmp_path):
    monkeypatch.setattr(run_doctor_checks.Path, "home", classmethod(lambda cls: tmp_path))
    app_dir = tmp_path / "Applications" / "Ghostty.app"
    app_dir.mkdir(parents=True)
    assert run_doctor_checks.has_app("Ghostty.app")

    monkeypatch.setattr(
        run_doctor_checks.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0),
    )
    assert run_doctor_checks.has_npm("context-mode")


def test_run_doctor_checks_main_success(monkeypatch, tmp_path, capsys):
    brewfile = tmp_path / "Brewfile"
    manifest = tmp_path / "manifest.json"
    brewfile.write_text('brew "git"\ncask "ghostty"\nnpm "context-mode"\n')
    manifest.write_text(json.dumps({"cask_overrides": {"ghostty": {"app": "Ghostty.app"}}}))

    monkeypatch.setattr(run_doctor_checks, "brew_list", lambda kind: {"git"} if kind == "--formula" else set())
    monkeypatch.setattr(run_doctor_checks, "has_command", lambda name: False)
    monkeypatch.setattr(run_doctor_checks, "has_app", lambda name: name == "Ghostty.app")
    monkeypatch.setattr(run_doctor_checks, "has_npm", lambda name: name == "context-mode")

    rc = run_doctor_checks.main(["run-doctor-checks.py", str(brewfile), str(manifest)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Doctor passed." in out


def test_run_doctor_checks_main_failure(monkeypatch, tmp_path, capsys):
    brewfile = tmp_path / "Brewfile"
    manifest = tmp_path / "manifest.json"
    brewfile.write_text('brew "git"\n')
    manifest.write_text("{}")

    monkeypatch.setattr(run_doctor_checks, "brew_list", lambda kind: set())
    monkeypatch.setattr(run_doctor_checks, "has_command", lambda name: False)

    rc = run_doctor_checks.main(["run-doctor-checks.py", str(brewfile), str(manifest)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "missing formula: git" in out


def test_run_doctor_checks_usage(capsys):
    rc = run_doctor_checks.main(["run-doctor-checks.py"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "Usage:" in err


def test_run_doctor_checks_optional_and_command_branches(monkeypatch, tmp_path, capsys):
    brewfile = tmp_path / "Brewfile"
    manifest = tmp_path / "manifest.json"
    brewfile.write_text('cask "claude-code"\ncask "cc-switch"\n')
    manifest.write_text(
        json.dumps(
            {
                "cask_overrides": {
                    "claude-code": {"app": "Claude Code.app", "command": "claude"},
                    "cc-switch": {"app": "cc-switch.app", "command": "cc-switch", "optional": True},
                }
            }
        )
    )

    monkeypatch.setattr(run_doctor_checks, "brew_list", lambda kind: set())
    monkeypatch.setattr(run_doctor_checks, "has_app", lambda name: False)
    monkeypatch.setattr(run_doctor_checks, "has_npm", lambda name: True)
    monkeypatch.setattr(run_doctor_checks, "has_command", lambda name: name == "claude")

    rc = run_doctor_checks.main(["run-doctor-checks.py", str(brewfile), str(manifest)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ok command: claude (cask: claude-code)" in out
    assert "skip optional cask/app: cc-switch (cc-switch.app)" in out


def test_check_python_syntax_usage(capsys):
    rc = check_python_syntax.main(["check-python-syntax.py"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "Usage:" in err


def test_check_python_syntax_ok(tmp_path, capsys):
    target = tmp_path / "ok.py"
    target.write_text("x = 1\n")
    rc = check_python_syntax.main(["check-python-syntax.py", str(target)])
    out = capsys.readouterr().out
    assert rc == 0
    assert f"ok {target}" in out
