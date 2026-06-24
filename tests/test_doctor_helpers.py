"""Unit tests for doctor helper functions."""

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


run_doctor_checks = load_module("run_doctor_checks", "scripts/run-doctor-checks.py")


def test_parse_brewfile_groups_entries(tmp_path):
    brewfile = tmp_path / "Brewfile"
    brewfile.write_text('brew "git"\ncask "ghostty"\nnpm "context-mode"\n')
    parsed = run_doctor_checks.parse_brewfile(brewfile)
    assert parsed == {"brew": ["git"], "cask": ["ghostty"], "npm": ["context-mode"]}


def test_run_stdout_and_brew_list(monkeypatch):
    assert run_doctor_checks.run_stdout(PYTHON, "-c", "print('alpha')") == "alpha"
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


def test_expected_symlink_targets_expands_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    manifest = {"managed_symlinks": {"~/.zprofile": "shell/zprofile"}}
    targets = run_doctor_checks.expected_symlink_targets(tmp_path, manifest)
    assert targets == {tmp_path / ".zprofile": tmp_path / "shell" / "zprofile"}


def test_run_doctor_checks_main_symlink_failure(monkeypatch, tmp_path, capsys):
    brewfile = tmp_path / "Brewfile"
    manifest = tmp_path / "manifest.json"
    brewfile.write_text("")
    manifest.write_text(json.dumps({"managed_symlinks": {"~/.zprofile": "shell/zprofile"}}))

    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "shell").mkdir()
    (tmp_path / "shell" / "zprofile").write_text("export TEST=1\n")
    (tmp_path / ".zprofile").symlink_to(tmp_path / "old-zprofile")
    (tmp_path / "old-zprofile").write_text("stale\n")

    monkeypatch.setattr(run_doctor_checks, "brew_list", lambda kind: set())

    rc = run_doctor_checks.main(["run-doctor-checks.py", str(brewfile), str(manifest)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "stale symlink:" in out


def test_run_doctor_checks_main_symlink_success(monkeypatch, tmp_path, capsys):
    brewfile = tmp_path / "Brewfile"
    manifest = tmp_path / "manifest.json"
    brewfile.write_text("")
    manifest.write_text(json.dumps({"managed_symlinks": {"~/.zprofile": "shell/zprofile"}}))

    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "shell").mkdir()
    (tmp_path / "shell" / "zprofile").write_text("export TEST=1\n")
    (tmp_path / ".zprofile").symlink_to(tmp_path / "shell" / "zprofile")

    monkeypatch.setattr(run_doctor_checks, "brew_list", lambda kind: set())

    rc = run_doctor_checks.main(["run-doctor-checks.py", str(brewfile), str(manifest)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ok symlink:" in out


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
