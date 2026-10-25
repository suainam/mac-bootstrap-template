"""Tests for the external-tools freshness audit (issue #53 & #01-profile-drift)."""
import json
import subprocess
import sys
from pathlib import Path
import pytest

TEMPLATE = Path(__file__).resolve().parents[1]
SCRIPT = TEMPLATE / "scripts" / "audit_external_tools.py"


def run_audit(profile, manifest=None, private_dir=None, extra_args=None):
    cmd = [sys.executable, str(SCRIPT), "--profile", profile]
    if manifest:
        cmd += ["--manifest", str(manifest)]
    if private_dir:
        cmd += ["--private-dir", str(private_dir)]
    if extra_args:
        cmd += extra_args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


@pytest.fixture
def isolated_roots(tmp_path):
    bin_root = tmp_path / "bin"
    app_root = tmp_path / "Applications"
    launchd_root = tmp_path / "LaunchAgents"
    bin_root.mkdir()
    app_root.mkdir()
    launchd_root.mkdir()
    return {
        "bin": bin_root,
        "app": app_root,
        "launchd": launchd_root,
        "args": [
            "--skip-brew",
            "--bin-root", str(bin_root),
            "--app-root", str(app_root),
            "--launchd-root", str(launchd_root),
        ],
    }


@pytest.fixture
def minimal_manifest(tmp_path):
    m = {"version": 1, "standalone_binaries": [], "external_apps": [], "daemons": []}
    p = tmp_path / "common.json"
    p.write_text(json.dumps(m))
    return p


@pytest.fixture
def mock_private(tmp_path):
    priv = tmp_path / "private"
    work_dir = priv / "profiles" / "work"
    home_dir = priv / "profiles" / "home"
    work_dir.mkdir(parents=True)
    home_dir.mkdir(parents=True)

    work_manifest = {
        "standalone_binaries": [],
        "external_apps": [],
        "daemons": [
            {
                "name": "work-daemon",
                "plist_paths": ["~/Library/LaunchAgents/io.work.daemon.plist"],
            }
        ],
    }
    (work_dir / "external-tools.json").write_text(json.dumps(work_manifest))
    (home_dir / "external-tools.json").write_text(json.dumps({"standalone_binaries": []}))
    return priv


def test_isolated_clean_manifest_passes(minimal_manifest, isolated_roots, mock_private):
    res = run_audit("home", minimal_manifest, private_dir=mock_private, extra_args=isolated_roots["args"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "no drift" in res.stdout


def test_missing_binary_reported_as_drift(minimal_manifest, isolated_roots, mock_private):
    data = json.loads(minimal_manifest.read_text())
    data["standalone_binaries"] = [
        {"name": "missing-tool", "target": str(isolated_roots["bin"] / "missing-tool")}
    ]
    minimal_manifest.write_text(json.dumps(data))

    res = run_audit("home", minimal_manifest, private_dir=mock_private, extra_args=isolated_roots["args"])
    assert res.returncode == 2
    assert "MISSING target" in res.stdout


def test_unexpected_binary_detected_in_bounded_root(minimal_manifest, isolated_roots, mock_private):
    stray = isolated_roots["bin"] / "stray-script"
    stray.write_text("#!/bin/sh\nexit 0")
    stray.chmod(0o755)

    res = run_audit("home", minimal_manifest, private_dir=mock_private, extra_args=isolated_roots["args"])
    assert res.returncode == 2
    assert "UNEXPECTED" in res.stdout
    assert "stray-script" in res.stdout


def test_unexpected_daemon_cross_profile_leak(minimal_manifest, isolated_roots, mock_private):
    # work daemon placed on home machine must be flagged as UNEXPECTED on home profile
    plist = isolated_roots["launchd"] / "io.work.daemon.plist"
    plist.write_text("<plist></plist>")

    res = run_audit("home", minimal_manifest, private_dir=mock_private, extra_args=isolated_roots["args"])
    assert res.returncode == 2
    assert "UNEXPECTED" in res.stdout
    assert "io.work.daemon.plist" in res.stdout


def test_manifest_not_found_returns_3(minimal_manifest, isolated_roots):
    res = run_audit("work", minimal_manifest.parent / "does-not-exist.json", extra_args=isolated_roots["args"])
    assert res.returncode == 3


def test_arbitrary_profile_adds_to_common_manifest(minimal_manifest, isolated_roots, mock_private):
    common = isolated_roots["bin"] / "common-tool"
    extra = isolated_roots["bin"] / "lab-tool"
    for executable in (common, extra):
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
    key = "target"
    minimal_manifest.write_text(json.dumps({"standalone_binaries": [
        {"name": common.name, key: str(common)}
    ]}))
    profile_dir = mock_private / "profiles" / "lab"
    profile_dir.mkdir()
    (profile_dir / "external-tools.json").write_text(json.dumps({"standalone_binaries": [
        {"name": extra.name, key: str(extra)}
    ]}))
    result = run_audit("lab", minimal_manifest, mock_private, isolated_roots["args"])
    assert result.returncode == 0, result.stdout + result.stderr
    extra.unlink()
    result = run_audit("lab", minimal_manifest, mock_private, isolated_roots["args"])
    assert result.returncode == 2
    assert "lab-tool" in result.stdout and "MISSING" in result.stdout


def test_brew_owned_application_excluded_but_stray_reported(isolated_roots):
    import importlib.util

    spec = importlib.util.spec_from_file_location("external_audit", SCRIPT)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    for name in ("Managed.app", "Stray.app"):
        (isolated_roots["app"] / name).mkdir()
    drift = audit.check_unexpected(
        {}, [isolated_roots["bin"]], [isolated_roots["app"]],
        [isolated_roots["launchd"]], {"Managed.app"}, set(), set(), set(),
        launchd_dir=isolated_roots["launchd"],
    )
    assert drift == [f"  app 'Stray.app': UNEXPECTED in {isolated_roots['app']}"]
