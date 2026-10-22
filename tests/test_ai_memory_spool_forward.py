"""Behavioural tests for template/scripts/ai-memory-spool-forward.py."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ai_memory_spool", ROOT / "scripts" / "ai-memory-spool-forward.py")
assert spec and spec.loader
spool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spool)


def test_retarget_rewrites_only_the_authority():
    entry = {"url": "http://127.0.0.1:49375/hook?event=stop&ingest_key=abc"}
    fixed, changed = spool.retarget(entry, "http://primary:30025")
    assert changed is True
    assert fixed["url"] == "http://primary:30025/hook?event=stop&ingest_key=abc"


def test_retarget_is_a_noop_on_the_canonical_authority():
    entry = {"url": "http://primary:30025/hook?event=stop"}
    fixed, changed = spool.retarget(entry, "http://primary:30025")
    assert changed is False
    assert fixed is entry


def test_retarget_ignores_entries_without_a_url():
    entry = {"body": "{}"}
    fixed, changed = spool.retarget(entry, "http://primary:30025")
    assert changed is False
    assert fixed is entry


def test_server_url_prefers_env_over_private_file(monkeypatch, tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("AI_MEMORY_SERVER_URL=http://from-file:1\n")
    monkeypatch.setattr(spool, "PRIVATE_ENV", env)
    monkeypatch.setenv("AI_MEMORY_SERVER_URL", "http://from-env:2/")
    assert spool.canonical_server() == "http://from-env:2"


def test_server_url_falls_back_to_private_file(monkeypatch, tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text('export AI_MEMORY_SERVER_URL="http://from-file:1"\n')
    monkeypatch.setattr(spool, "PRIVATE_ENV", env)
    monkeypatch.delenv("AI_MEMORY_SERVER_URL", raising=False)
    assert spool.canonical_server() == "http://from-file:1"


def test_server_url_fails_closed_without_config(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(spool, "PRIVATE_ENV", tmp_path / "absent.env")
    monkeypatch.delenv("AI_MEMORY_SERVER_URL", raising=False)
    with pytest.raises(SystemExit) as exc:
        spool.canonical_server()
    assert "no server URL configured" in str(exc.value)


def test_no_private_address_is_hardcoded():
    source = (ROOT / "scripts" / "ai-memory-spool-forward.py").read_text()
    assert not re.search(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d+\.\d+\.\d+\b", source)


def test_spool_dirs_accepts_a_data_dir_and_a_spool_dir(tmp_path: Path):
    data_dir = tmp_path / "data"
    (data_dir / "hook-spool").mkdir(parents=True)
    assert spool.spool_dirs([str(data_dir)]) == [data_dir / "hook-spool"]
    assert spool.spool_dirs([str(data_dir / "hook-spool")]) == [data_dir / "hook-spool"]


def test_spool_dirs_skips_missing_dirs(tmp_path: Path):
    assert spool.spool_dirs([str(tmp_path / "absent")]) == []


def test_delivery_keeps_the_file_on_a_4xx(monkeypatch, tmp_path: Path):
    """A rejected event must never be dropped: losing memory beats a growing backlog."""
    data_dir = tmp_path / "data"
    spool_dir = data_dir / "hook-spool"
    spool_dir.mkdir(parents=True)
    entry = spool_dir / "1.json"
    entry.write_text(json.dumps({"url": "http://primary:30025/hook", "body": "{}"}))

    monkeypatch.setattr(spool, "canonical_server", lambda: "http://primary:30025")
    monkeypatch.setattr(spool, "proxy_url", lambda: None)
    monkeypatch.setattr(spool, "deliver", lambda entry, proxy: 401)


    import sys

    argv = sys.argv
    sys.argv = ["spool", "--data-dir", str(data_dir), "--json"]
    try:
        rc = spool.main()
    finally:
        sys.argv = argv
    assert rc == 1
    assert entry.exists(), "a 4xx must keep the entry"


def test_delivery_consumes_the_file_on_2xx(monkeypatch, tmp_path: Path):
    data_dir = tmp_path / "data"
    spool_dir = data_dir / "hook-spool"
    spool_dir.mkdir(parents=True)
    entry = spool_dir / "1.json"
    entry.write_text(json.dumps({"url": "http://primary:30025/hook", "body": "{}"}))

    monkeypatch.setattr(spool, "canonical_server", lambda: "http://primary:30025")
    monkeypatch.setattr(spool, "proxy_url", lambda: None)
    monkeypatch.setattr(spool, "deliver", lambda entry, proxy: 204)

    import sys

    argv = sys.argv
    sys.argv = ["spool", "--data-dir", str(data_dir), "--json"]
    try:
        rc = spool.main()
    finally:
        sys.argv = argv
    assert rc == 0
    assert not entry.exists(), "a 2xx consumes the entry"


def test_dry_run_reports_without_touching_files(monkeypatch, tmp_path: Path):
    data_dir = tmp_path / "data"
    spool_dir = data_dir / "hook-spool"
    spool_dir.mkdir(parents=True)
    entry = spool_dir / "1.json"
    original = {"url": "http://127.0.0.1:49375/hook", "body": "{}"}
    entry.write_text(json.dumps(original))

    monkeypatch.setattr(spool, "canonical_server", lambda: "http://primary:30025")
    monkeypatch.setattr(spool, "proxy_url", lambda: None)
    monkeypatch.setattr(spool, "deliver", lambda entry, proxy: pytest.fail("dry-run must not deliver"))

    import sys

    argv = sys.argv
    sys.argv = ["spool", "--data-dir", str(data_dir), "--dry-run", "--json"]
    try:
        rc = spool.main()
    finally:
        sys.argv = argv
    assert rc == 1, "stale entries make the read-only gate fail"
    assert json.loads(entry.read_text()) == original
