"""Behavioural tests for template/scripts/ai-memory-mcp-bridge.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import importlib.util
spec = importlib.util.spec_from_file_location("ai_memory_bridge", ROOT / "scripts" / "ai-memory-mcp-bridge.py")
assert spec and spec.loader
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def test_normalize_remote():
    assert bridge.normalize_remote("git@github.com:owner/repo.git") == "owner-repo"
    assert bridge.normalize_remote("https://github.com/owner/repo") == "owner-repo"
    assert bridge.normalize_remote("https://gitlab.com/group/subgroup/project.git") == "group-subgroup-project"
    assert bridge.normalize_remote("") is None


def test_resolve_scope_explicit_marker(tmp_path: Path):
    marker = tmp_path / ".ai-memory.toml"
    marker.write_text('workspace = "ws1"\nproject = "proj1"\n', encoding="utf-8")
    assert bridge.resolve_scope(tmp_path) == ("ws1", "proj1")


def test_resolve_scope_fails_when_no_marker_and_no_git(tmp_path: Path):
    assert bridge.resolve_scope(tmp_path) is None


def test_rewrite_injects_missing_scope():
    scope = ("my-ws", "my-proj")
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "memory_status",
            "arguments": {}
        }
    }
    line = json.dumps(req).encode() + b"\n"
    forwarded, error = bridge.rewrite(line, scope)
    assert error is None
    payload = json.loads(forwarded)
    args = payload["params"]["arguments"]
    assert args["workspace"] == "my-ws"
    assert args["project"] == "my-proj"


def test_rewrite_preserves_explicit_scope():
    scope = ("my-ws", "my-proj")
    req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "memory_status",
            "arguments": {"workspace": "explicit-ws", "project": "explicit-proj"}
        }
    }
    line = json.dumps(req).encode() + b"\n"
    forwarded, error = bridge.rewrite(line, scope)
    assert error is None
    assert forwarded == line  # unchanged


def test_rewrite_preserves_global_scope():
    scope = ("my-ws", "my-proj")
    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "memory_query",
            "arguments": {"query": "test", "global": True}
        }
    }
    line = json.dumps(req).encode() + b"\n"
    forwarded, error = bridge.rewrite(line, scope)
    assert error is None
    assert forwarded == line  # unchanged


def test_rewrite_fails_closed_when_no_scope():
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "memory_status",
            "arguments": {}
        }
    }
    line = json.dumps(req).encode() + b"\n"
    forwarded, error = bridge.rewrite(line, None)
    assert forwarded == b""
    assert error is not None
    assert error["id"] == 4
    assert error["error"]["code"] == -32602
    assert "refusing unscoped" in error["error"]["message"]


def test_rewrite_passes_through_non_tool_calls():
    scope = ("my-ws", "my-proj")
    notif = b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
    forwarded, error = bridge.rewrite(notif, scope)
    assert error is None
    assert forwarded == notif
