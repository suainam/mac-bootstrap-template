"""Safety regressions for the decrypt-materialize CLI boundary."""

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "decrypt_codex_crossplatform.py"
SPEC = importlib.util.spec_from_file_location("decrypt_codex_crossplatform", SCRIPT)
assert SPEC and SPEC.loader
decrypt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(decrypt)

SCAN_SCRIPT = Path(__file__).parents[1] / "scripts" / "scan_encrypted.py"
SCAN_SPEC = importlib.util.spec_from_file_location("scan_encrypted", SCAN_SCRIPT)
assert SCAN_SPEC and SCAN_SPEC.loader
scan = importlib.util.module_from_spec(SCAN_SPEC)
SCAN_SPEC.loader.exec_module(scan)


def test_sqlite_materialization_preserves_committed_wal_rows(tmp_path: Path):
    source = tmp_path / "source.sqlite"
    output = tmp_path / "output.sqlite"
    connection = sqlite3.connect(source)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("CREATE TABLE events(value INTEGER)")
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.executemany("INSERT INTO events VALUES (?)", [(1,), (2,), (3,)])
    connection.commit()

    result = decrypt.decrypt_sqlite(source, output)

    assert result["status"] == "success"
    with sqlite3.connect(output) as materialized:
        assert materialized.execute("SELECT value FROM events ORDER BY value").fetchall() == [
            (1,),
            (2,),
            (3,),
        ]
    connection.close()


def test_tsd_detection_treats_shell_metacharacters_as_filename(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "payload$(touch${IFS}owned).sqlite"
    source.write_bytes(b"%TSD-Header-###%payload")

    assert decrypt.is_tsd_encrypted(source) is True
    assert not (tmp_path / "owned").exists()


def test_encrypted_scan_treats_shell_metacharacters_as_filename(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "payload$(touch${IFS}owned).sqlite"
    source.write_bytes(b"%TSD-Header-###%" + b"x" * 2048)

    assert scan.check_encryption(source) == (True, "TSD")
    assert not (tmp_path / "owned").exists()


def test_windows_default_codex_dir_uses_user_profile(monkeypatch):
    monkeypatch.setattr(decrypt, "get_platform", lambda: "windows")
    monkeypatch.setenv("USERPROFILE", r"C:\\Users\\codex-user")
    monkeypatch.setenv("APPDATA", r"C:\\Users\\codex-user\\AppData\\Roaming")

    assert decrypt.get_codex_dir() == Path(r"C:\\Users\\codex-user") / ".codex"


def test_stop_daemon_never_kills_arbitrary_matching_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    commands = []
    checks = iter([([4321], ["codex-app"]), ([4321], ["codex-app"])])
    monkeypatch.setattr(decrypt, "check_codex_running", lambda: next(checks))
    monkeypatch.setattr(decrypt, "stop_codex_daemon", lambda: True)
    monkeypatch.setattr(decrypt.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(decrypt.subprocess, "run", lambda command, **_kwargs: commands.append(command))
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), str(tmp_path), "--stop-daemon", "--no-replace"],
    )

    assert decrypt.main() == 1
    assert not any(command and command[0] in {"kill", "taskkill"} for command in commands)
