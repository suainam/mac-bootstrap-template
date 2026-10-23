"""Behavioural tests for template/scripts/memos-mcp-bridge.py."""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("memos_bridge", ROOT / "scripts" / "memos-mcp-bridge.py")
assert spec and spec.loader
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def test_normalize_remote():
    assert bridge.normalize_remote("git@github.com:owner/repo.git") == "owner-repo"
    assert bridge.normalize_remote("https://github.com/owner/repo") == "owner-repo"
    assert bridge.normalize_remote("https://gitlab.com/group/subgroup/project.git") == "group-subgroup-project"
    assert bridge.normalize_remote("") is None
    assert bridge.normalize_remote("   ") is None


def test_private_env_value_parses_exported_and_quoted(monkeypatch, tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text('# comment\nexport MEMOS_API_KEY="k-secret"\nOTHER=x\n', encoding="utf-8")
    monkeypatch.setattr(bridge, "PRIVATE_ENV", env)
    assert bridge.private_env_value("MEMOS_API_KEY") == "k-secret"
    assert bridge.private_env_value("MISSING") is None


def test_marker_values_parses_project(tmp_path: Path):
    marker = tmp_path / ".ai-memory.toml"
    marker.write_text('workspace = "ws1"\nproject = "proj1"\n', encoding="utf-8")
    assert bridge.marker_values(marker)["project"] == "proj1"


def test_resolve_user_id_prefers_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MEMOS_USER_ID", "from-env")
    assert bridge.resolve_user_id(tmp_path) == "from-env"


def test_resolve_user_id_falls_back_to_marker(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("MEMOS_USER_ID", raising=False)
    marker = tmp_path / ".ai-memory.toml"
    marker.write_text('project = "proj-marker"\n', encoding="utf-8")
    assert bridge.resolve_user_id(tmp_path) == "proj-marker"


def test_resolve_user_id_falls_back_to_workname(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("MEMOS_USER_ID", raising=False)
    assert bridge.resolve_user_id(tmp_path) == tmp_path.name


def test_main_fails_closed_without_key(monkeypatch, tmp_path: Path):
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)}
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "memos-mcp-bridge.py")],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
        check=False,
    )
    assert proc.returncode == 2
    assert "no API key" in proc.stderr


def test_no_private_address_is_hardcoded():
    source = (ROOT / "scripts" / "memos-mcp-bridge.py").read_text()
    assert not re.search(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d+\.\d+\.\d+\b", source)
