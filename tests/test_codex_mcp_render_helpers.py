"""Unit tests for Codex MCP block rendering."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from helpers import PYTHON


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, rel_path: str):
    path = ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


render_codex_mcp_block = load_module("render_codex_mcp_block", "scripts/render-codex-mcp-block.py")



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
