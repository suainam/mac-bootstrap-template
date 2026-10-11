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


def write_ownership_manifest(root: Path, zb_formulas: list[str] | None = None) -> Path:
    scripts_dir = root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    path = scripts_dir / "package-ownership.json"
    path.write_text(json.dumps({"version": 1, "zerobrew_formulas": zb_formulas or []}))
    return path


def test_evaluate_brewfile_respects_ruby_conditionals_options_and_profiles(tmp_path):
    private_dir = tmp_path / "private"
    for profile, extra_pkg in (("home", "fd"), ("work", "tree")):
        prof_dir = private_dir / "profiles" / profile
        prof_dir.mkdir(parents=True)
        (prof_dir / "Brewfile").write_text(f'brew "{extra_pkg}"\n')

    brewfile = tmp_path / "Brewfile"
    brewfile.write_text(
        'brew "jq", link: false\n'
        'if false\n'
        '  brew "not-installed-example"\n'
        'end\n'
        'cask "ghostty"\n'
        'npm "context-mode"\n'
        'private_dir = ENV["HOMEBREW_MAC_BOOTSTRAP_PRIVATE_DIR"]\n'
        'profile = ENV["HOMEBREW_MAC_BOOTSTRAP_PROFILE"]\n'
        'extra = File.join(private_dir, "profiles", profile, "Brewfile")\n'
        'instance_eval(File.read(extra)) if File.exist?(extra)\n'
    )

    home_env = run_doctor_checks.os.environ.copy()
    home_env["HOMEBREW_MAC_BOOTSTRAP_PRIVATE_DIR"] = str(private_dir)
    home_env["HOMEBREW_MAC_BOOTSTRAP_PROFILE"] = "home"
    home_declared = run_doctor_checks.evaluate_brewfile(brewfile, env=home_env)
    assert home_declared == {
        "brew": ["jq", "fd"],
        "cask": ["ghostty"],
        "npm": ["context-mode"],
    }

    work_env = run_doctor_checks.os.environ.copy()
    work_env["HOMEBREW_MAC_BOOTSTRAP_PRIVATE_DIR"] = str(private_dir)
    work_env["HOMEBREW_MAC_BOOTSTRAP_PROFILE"] = "work"
    work_declared = run_doctor_checks.evaluate_brewfile(brewfile, env=work_env)
    assert work_declared == {
        "brew": ["jq", "tree"],
        "cask": ["ghostty"],
        "npm": ["context-mode"],
    }


def test_run_checked_and_inventory_lists(monkeypatch):
    assert run_doctor_checks.run_checked([PYTHON, "-c", "print('alpha\\nbeta')"]) == ["alpha", "beta"]
    monkeypatch.setattr(run_doctor_checks, "run_checked", lambda args, **kw: ["git", "jq"])
    assert run_doctor_checks.brew_list("--formula") == {"git", "jq"}
    monkeypatch.setattr(run_doctor_checks, "run_checked", lambda args, **kw: ["uv 0.13.0", "fd 10.5.0"])
    assert run_doctor_checks.zb_list("/opt/zerobrew") == {"uv", "fd"}


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
    brewfile.write_text('brew "git"\n')
    manifest.write_text(json.dumps({"cask_overrides": {"ghostty": {"app": "Ghostty.app"}}}))
    write_ownership_manifest(tmp_path, ["uv"])

    monkeypatch.setattr(
        run_doctor_checks,
        "evaluate_brewfile",
        lambda path, env=None: {
            "brew": ["git", "anomalyco/tap/opencode-v2", "uv"],
            "cask": ["ghostty"],
            "npm": ["context-mode"],
        },
    )
    monkeypatch.setattr(
        run_doctor_checks,
        "brew_list",
        lambda kind: {"git", "anomalyco/tap/opencode-v2"} if kind == "--formula" else set(),
    )
    monkeypatch.setattr(run_doctor_checks, "zb_list", lambda root=None: {"uv"})
    monkeypatch.setattr(run_doctor_checks, "has_command", lambda name: False)
    monkeypatch.setattr(run_doctor_checks, "has_app", lambda name: name == "Ghostty.app")
    monkeypatch.setattr(run_doctor_checks, "has_npm", lambda name: name == "context-mode")

    rc = run_doctor_checks.main(["run-doctor-checks.py", str(brewfile), str(manifest), "--strict"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ok formula: git (brew)" in out
    assert "ok formula: anomalyco/tap/opencode-v2 (brew)" in out
    assert "ok formula: uv (zb)" in out
    assert "Doctor passed." in out

def test_chrome_gemini_check_passes_for_eligible_profile(monkeypatch, tmp_path, capsys):
    chrome_root = tmp_path / "Library/Application Support/Google/Chrome"
    profile = chrome_root / "Default"
    profile.mkdir(parents=True)
    (chrome_root / "Local State").write_text(
        json.dumps(
            {
                "glic": {"launcher_enabled": True},
                "profile": {"info_cache": {"Default": {"is_glic_eligible": True}}},
            }
        )
    )
    (profile / "Preferences").write_text(
        json.dumps({"glic": {"completed_fre": 1}, "side_panel": {"id_to_width": {"kGlic": 475}}})
    )

    monkeypatch.setattr(run_doctor_checks.Path, "home", classmethod(lambda cls: tmp_path))

    failed = run_doctor_checks.check_chrome_gemini({"chrome_gemini": {"enabled": True, "profile": "Default"}})
    out = capsys.readouterr().out
    assert failed is False
    assert "ok chrome gemini: launcher enabled" in out


def test_chrome_gemini_check_fails_when_launcher_disabled(monkeypatch, tmp_path, capsys):
    chrome_root = tmp_path / "Library/Application Support/Google/Chrome"
    profile = chrome_root / "Default"
    profile.mkdir(parents=True)
    (chrome_root / "Local State").write_text(
        json.dumps(
            {
                "glic": {"launcher_enabled": False},
                "profile": {"info_cache": {"Default": {"is_glic_eligible": True}}},
            }
        )
    )
    (profile / "Preferences").write_text(json.dumps({"glic": {"completed_fre": 0}}))

    monkeypatch.setattr(run_doctor_checks.Path, "home", classmethod(lambda cls: tmp_path))

    failed = run_doctor_checks.check_chrome_gemini({"chrome_gemini": {"enabled": True, "profile": "Default"}})
    out = capsys.readouterr().out
    assert failed is True
    assert "missing chrome gemini: launcher is disabled" in out
    assert "missing chrome gemini: first-run flow not completed" in out


def test_chrome_gemini_check_skips_ineligible_profile(monkeypatch, tmp_path, capsys):
    chrome_root = tmp_path / "Library/Application Support/Google/Chrome"
    chrome_root.mkdir(parents=True)
    (chrome_root / "Local State").write_text(
        json.dumps({"profile": {"info_cache": {"Default": {"is_glic_eligible": False}}}})
    )

    monkeypatch.setattr(run_doctor_checks.Path, "home", classmethod(lambda cls: tmp_path))

    failed = run_doctor_checks.check_chrome_gemini({"chrome_gemini": {"enabled": True, "profile": "Default"}})
    out = capsys.readouterr().out
    assert failed is False
    assert "skip chrome gemini" in out


def test_run_doctor_checks_missing_formula_not_masked_by_path_command(monkeypatch, tmp_path, capsys):
    brewfile = tmp_path / "Brewfile"
    manifest = tmp_path / "manifest.json"
    brewfile.write_text('brew "git"\n')
    manifest.write_text(json.dumps({"formula_command_overrides": {"git": "git"}}))
    write_ownership_manifest(tmp_path, ["uv"])

    monkeypatch.setattr(
        run_doctor_checks,
        "evaluate_brewfile",
        lambda path, env=None: {"brew": ["git"], "cask": [], "npm": []},
    )
    monkeypatch.setattr(run_doctor_checks, "brew_list", lambda kind: set())
    monkeypatch.setattr(run_doctor_checks, "zb_list", lambda root=None: set())
    monkeypatch.setattr(run_doctor_checks, "has_command", lambda name: True)

    rc = run_doctor_checks.main(["run-doctor-checks.py", str(brewfile), str(manifest)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "missing formula: git (expected brew)" in out


def test_run_doctor_checks_wrong_and_duplicate_ownership_and_custom_tap(monkeypatch, tmp_path, capsys):
    brewfile = tmp_path / "Brewfile"
    manifest = tmp_path / "manifest.json"
    brewfile.write_text("")
    manifest.write_text("{}")
    write_ownership_manifest(tmp_path, ["fd", "uv"])

    monkeypatch.setattr(
        run_doctor_checks,
        "evaluate_brewfile",
        lambda path, env=None: {
            "brew": ["uv", "jq", "fd", "custom/tap/fd"],
            "cask": [],
            "npm": [],
        },
    )
    # uv is in brew (wrong: expected zb); jq is in zb (wrong: expected brew);
    # fd is in both brew and zb (duplicate); custom/tap/fd is not in brew (missing: expected brew, not satisfied by core fd in zb)
    monkeypatch.setattr(
        run_doctor_checks,
        "brew_list",
        lambda kind: {"uv", "fd"} if kind == "--formula" else set(),
    )
    monkeypatch.setattr(run_doctor_checks, "zb_list", lambda root=None: {"jq", "fd"})

    rc = run_doctor_checks.main(["run-doctor-checks.py", str(brewfile), str(manifest)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "wrong formula owner: uv (installed in brew, expected zb)" in out
    assert "wrong formula owner: jq (installed in zb, expected brew)" in out
    assert "duplicate formula owner: fd (installed in both brew and zb, expected zb)" in out


def test_custom_tap_does_not_match_core_zb_ownership(monkeypatch, tmp_path, capsys):
    brewfile = tmp_path / "Brewfile"
    manifest = tmp_path / "manifest.json"
    brewfile.write_text("")
    manifest.write_text("{}")
    write_ownership_manifest(tmp_path, ["fd"])

    monkeypatch.setattr(
        run_doctor_checks,
        "evaluate_brewfile",
        lambda path, env=None: {"brew": ["custom/tap/fd"], "cask": [], "npm": []},
    )
    monkeypatch.setattr(run_doctor_checks, "brew_list", lambda kind: set())
    monkeypatch.setattr(run_doctor_checks, "zb_list", lambda root=None: {"fd"})

    rc = run_doctor_checks.main(["run-doctor-checks.py", str(brewfile), str(manifest)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "missing formula: custom/tap/fd (expected brew)" in out

def test_core_alias_and_custom_tap_inventory_are_distinct(capsys):
    assert run_doctor_checks.check_formulae(["core/uv"], set(), {"uv"}, {"uv"}, {}) is False
    assert run_doctor_checks.check_formulae(["custom/tap/fd"], {"fd"}, set(), {"fd"}, {}) is True
    assert "missing formula: custom/tap/fd" in capsys.readouterr().out



def test_run_doctor_checks_fails_when_ownership_manifest_missing_or_command_fails(monkeypatch, tmp_path, capsys):
    brewfile = tmp_path / "Brewfile"
    manifest = tmp_path / "manifest.json"
    brewfile.write_text("")
    manifest.write_text("{}")

    # 1. Missing ownership manifest fails loudly
    rc = run_doctor_checks.main(["run-doctor-checks.py", str(brewfile), str(manifest)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "missing or invalid ownership manifest" in captured.err

    # 2. Inventory subprocess failure propagates stderr and returns 1
    write_ownership_manifest(tmp_path, ["uv"])
    monkeypatch.setattr(
        run_doctor_checks,
        "evaluate_brewfile",
        lambda path, env=None: {"brew": ["uv"], "cask": [], "npm": []},
    )
    monkeypatch.setattr(run_doctor_checks, "brew_list", lambda kind: set())

    def fail_zb(root=None):
        raise RuntimeError("command failed (zb --root /opt/zerobrew list): store corrupted")

    monkeypatch.setattr(run_doctor_checks, "zb_list", fail_zb)
    rc = run_doctor_checks.main(["run-doctor-checks.py", str(brewfile), str(manifest)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "store corrupted" in captured.err

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
    write_ownership_manifest(tmp_path, [])

    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "shell").mkdir()
    (tmp_path / "shell" / "zprofile").write_text("export TEST=1\n")
    (tmp_path / ".zprofile").symlink_to(tmp_path / "old-zprofile")
    (tmp_path / "old-zprofile").write_text("stale\n")

    monkeypatch.setattr(
        run_doctor_checks,
        "evaluate_brewfile",
        lambda path, env=None: {"brew": [], "cask": [], "npm": []},
    )
    monkeypatch.setattr(run_doctor_checks, "brew_list", lambda kind: set())
    monkeypatch.setattr(run_doctor_checks, "zb_list", lambda root=None: set())

    rc = run_doctor_checks.main(["run-doctor-checks.py", str(brewfile), str(manifest)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "stale symlink:" in out


def test_run_doctor_checks_main_symlink_success(monkeypatch, tmp_path, capsys):
    brewfile = tmp_path / "Brewfile"
    manifest = tmp_path / "manifest.json"
    brewfile.write_text("")
    manifest.write_text(json.dumps({"managed_symlinks": {"~/.zprofile": "shell/zprofile"}}))
    write_ownership_manifest(tmp_path, [])

    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "shell").mkdir()
    (tmp_path / "shell" / "zprofile").write_text("export TEST=1\n")
    (tmp_path / ".zprofile").symlink_to(tmp_path / "shell" / "zprofile")

    monkeypatch.setattr(
        run_doctor_checks,
        "evaluate_brewfile",
        lambda path, env=None: {"brew": [], "cask": [], "npm": []},
    )
    monkeypatch.setattr(run_doctor_checks, "brew_list", lambda kind: set())
    monkeypatch.setattr(run_doctor_checks, "zb_list", lambda root=None: set())

    rc = run_doctor_checks.main(["run-doctor-checks.py", str(brewfile), str(manifest)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ok symlink:" in out


def test_run_doctor_checks_usage(capsys):
    rc = run_doctor_checks.main(["run-doctor-checks.py"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "Usage:" in err

    rc_unknown = run_doctor_checks.main(["run-doctor-checks.py", "Brewfile", "manifest.json", "--unknown"])
    err_unknown = capsys.readouterr().err
    assert rc_unknown == 2
    assert "Usage:" in err_unknown


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
    write_ownership_manifest(tmp_path, [])

    monkeypatch.setattr(
        run_doctor_checks,
        "evaluate_brewfile",
        lambda path, env=None: {"brew": [], "cask": ["claude-code", "cc-switch"], "npm": []},
    )
    monkeypatch.setattr(run_doctor_checks, "brew_list", lambda kind: set())
    monkeypatch.setattr(run_doctor_checks, "zb_list", lambda root=None: set())
    monkeypatch.setattr(run_doctor_checks, "has_app", lambda name: False)
    monkeypatch.setattr(run_doctor_checks, "has_npm", lambda name: True)
    monkeypatch.setattr(run_doctor_checks, "has_command", lambda name: name == "claude")

    rc = run_doctor_checks.main(["run-doctor-checks.py", str(brewfile), str(manifest)])
    out = capsys.readouterr().out
    assert rc == 0


def test_doctor_sh_validates_flags():
    doctor_sh = ROOT / "scripts" / "doctor.sh"
    help_res = subprocess.run([str(doctor_sh), "--help"], capture_output=True, text=True, check=False)
    assert help_res.returncode == 0
    assert "Usage: scripts/doctor.sh [--strict]" in help_res.stdout

    bad_res = subprocess.run([str(doctor_sh), "--unknown-flag"], capture_output=True, text=True, check=False)
    assert bad_res.returncode == 2
    assert "Usage: scripts/doctor.sh [--strict]" in bad_res.stderr
