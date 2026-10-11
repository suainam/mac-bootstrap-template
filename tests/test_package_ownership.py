"""Behavior tests for package manager ownership and migration (Issue #164)."""

import json
import os
import subprocess
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = TEMPLATE / "scripts"
OWNERSHIP_SCRIPT = SCRIPTS_DIR / "package-ownership.sh"
OWNERSHIP_MANIFEST = SCRIPTS_DIR / "package-ownership.json"
BREW_BUNDLE_SCRIPT = SCRIPTS_DIR / "brew-bundle.sh"


def test_manifest_declares_21_stable_zerobrew_formulas():
    assert OWNERSHIP_MANIFEST.exists(), f"Missing {OWNERSHIP_MANIFEST}"
    data = json.loads(OWNERSHIP_MANIFEST.read_text())
    formulas = data.get("zerobrew_formulas", [])
    assert len(formulas) == 21
    assert "uv" in formulas
    assert "docker-compose" in formulas
    assert "docker-buildx" in formulas
    assert "gh" in formulas
    assert "ast-grep" in formulas
    assert "rclone" in formulas
    assert "rustic" in formulas


def test_package_ownership_script_queries():
    # Test list-zb
    res = subprocess.run(
        [str(OWNERSHIP_SCRIPT), "list-zb"],
        capture_output=True,
        text=True,
        check=True,
    )
    zb_list = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    assert len(zb_list) == 21
    assert "uv" in zb_list
    assert "git" not in zb_list

    # Test owner for zb package
    res = subprocess.run(
        [str(OWNERSHIP_SCRIPT), "owner", "uv"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout.strip() == "zb"

    # Test owner for brew package (default fallback)
    res = subprocess.run(
        [str(OWNERSHIP_SCRIPT), "owner", "git"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout.strip() == "brew"

    # Test owner with tap prefix
    res = subprocess.run(
        [str(OWNERSHIP_SCRIPT), "owner", "anomalyco/tap/opencode-v2"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout.strip() == "brew"


def test_ownership_is_independent_of_upstream_metadata(tmp_path):
    # Verify that changing metadata does not dynamically change ownership
    # The authority is strictly the manifest, not brew info or bottle relocation attributes
    fake_manifest = tmp_path / "fake-manifest.json"
    fake_manifest.write_text(json.dumps({"zerobrew_formulas": ["custom-tool"]}))

    env = os.environ.copy()
    env["PACKAGE_OWNERSHIP_MANIFEST"] = str(fake_manifest)

    res = subprocess.run(
        [str(OWNERSHIP_SCRIPT), "owner", "custom-tool"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert res.stdout.strip() == "zb"

    res = subprocess.run(
        [str(OWNERSHIP_SCRIPT), "owner", "uv"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert res.stdout.strip() == "brew"


def test_brewfile_evaluates_homebrew_prefixed_env_vars(tmp_path):
    # Verify that HOMEBREW_MAC_BOOTSTRAP_PROFILE and HOMEBREW_MAC_BOOTSTRAP_PRIVATE_DIR
    # are recognized by Brewfile (transport past Homebrew 7 environment filtering)
    profile_dir = tmp_path / "private" / "profiles" / "custom"
    profile_dir.mkdir(parents=True)
    (profile_dir / "Brewfile").write_text('brew "custom-profile-pkg"\n')

    brewfile = TEMPLATE / "Brewfile"
    assert brewfile.exists()
    content = brewfile.read_text()
    assert 'ENV["HOMEBREW_MAC_BOOTSTRAP_PRIVATE_DIR"]' in content
    assert 'ENV["HOMEBREW_MAC_BOOTSTRAP_PROFILE"]' in content


def test_normal_reconcile_halts_on_ownership_mismatch(tmp_path):
    # Setup mock binaries for brew and zb
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    # Mock brew
    mock_brew = bin_dir / "brew"
    mock_brew.write_text("""#!/usr/bin/env bash
if [ "$1" = "bundle" ] && [ "$2" = "list" ]; then
    echo "git"
    echo "uv"
    exit 0
fi
if [ "$1" = "list" ] && [ "$2" = "--formula" ]; then
    # Return uv as installed in brew (mismatch because uv is declared for zb)
    echo "uv"
    echo "git"
    exit 0
fi
if [ "$1" = "list" ] && [ "$2" = "--cask" ]; then
    exit 0
fi
exit 0
""")
    mock_brew.chmod(0o755)

    # Mock zb
    mock_zb = bin_dir / "zb"
    mock_zb.write_text("""#!/usr/bin/env bash
exit 0
""")
    mock_zb.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["ZEROBREW_ROOT"] = str(tmp_path / "zerobrew")
    env["ZEROBREW_PREFIX"] = str(tmp_path / "zerobrew")
    (tmp_path / "zerobrew").mkdir()

    # Running brew-bundle.sh install should exit with code 1 and tell user to migrate
    res = subprocess.run(
        [str(BREW_BUNDLE_SCRIPT), "install"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode != 0
    assert "Ownership mismatch detected" in res.stderr
    assert "uv" in res.stderr
    assert "migrate" in res.stderr


def test_explicit_migrate_dependency_preflight_blocks_uninstall(tmp_path):
    # Setup mock binaries: candidate package 'uv' has dependent 'dependent-tool'
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    mock_brew_log = tmp_path / "brew_calls.log"
    mock_brew = bin_dir / "brew"
    mock_brew.write_text(f"""#!/usr/bin/env bash
echo "brew $@" >> "{mock_brew_log}"
if [ "$1" = "bundle" ] && [ "$2" = "list" ]; then
    echo "git"
    echo "uv"
    exit 0
fi
if [ "$1" = "list" ] && [ "$2" = "--formula" ]; then
    echo "uv"
    echo "git"
    exit 0
fi
if [ "$1" = "uses" ] && [ "$2" = "--installed" ]; then
    if [ "$3" = "uv" ]; then
        echo "some-dependent-app"
        exit 0
    fi
    exit 0
fi
exit 0
""")
    mock_brew.chmod(0o755)

    mock_zb = bin_dir / "zb"
    mock_zb.write_text("""#!/usr/bin/env bash
exit 0
""")
    mock_zb.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["ZEROBREW_ROOT"] = str(tmp_path / "zerobrew")
    env["ZEROBREW_PREFIX"] = str(tmp_path / "zerobrew")
    (tmp_path / "zerobrew").mkdir()

    # Running brew-bundle.sh migrate should fail during preflight and NEVER call brew uninstall
    res = subprocess.run(
        [str(BREW_BUNDLE_SCRIPT), "migrate"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode != 0
    assert "Dependency blocker" in res.stderr
    assert "some-dependent-app" in res.stderr

    # Verify no uninstalls were attempted
    log_content = mock_brew_log.read_text()
    assert "uninstall" not in log_content


def test_explicit_migrate_success_flow(tmp_path):
    # Setup mock binaries where preflight passes and install succeeds
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    zb_root = tmp_path / "zerobrew"
    zb_bin = zb_root / "bin"
    zb_bin.mkdir(parents=True)

    mock_brew_log = tmp_path / "brew_calls.log"
    mock_brew = bin_dir / "brew"
    mock_brew.write_text(f"""#!/usr/bin/env bash
echo "brew $@" >> "{mock_brew_log}"
if [ "$1" = "bundle" ] && [ "$2" = "list" ]; then
    echo "uv"
    exit 0
fi
if [ "$1" = "list" ] && [ "$2" = "--formula" ]; then
    echo "uv"
    exit 0
fi
if [ "$1" = "uses" ] && [ "$2" = "--installed" ]; then
    # No dependents
    exit 0
fi
if [ "$1" = "uninstall" ]; then
    echo "Uninstalled $2"
    exit 0
fi
exit 0
""")
    mock_brew.chmod(0o755)

    mock_zb = bin_dir / "zb"
    mock_zb.write_text(f"""#!/usr/bin/env bash
if [ "$5" = "install" ]; then
    # Create the binary to simulate successful install
    touch "{zb_bin}/$6"
    chmod +x "{zb_bin}/$6"
    exit 0
fi
exit 0
""")
    mock_zb.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["ZEROBREW_ROOT"] = str(zb_root)
    env["ZEROBREW_PREFIX"] = str(zb_root)

    res = subprocess.run(
        [str(BREW_BUNDLE_SCRIPT), "migrate"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode == 0
    assert "Preflight passed" in res.stdout
    assert "Migration complete" in res.stdout

    # Verify brew uninstall WAS called only after verification
    log_content = mock_brew_log.read_text()
    assert "brew uninstall uv" in log_content
