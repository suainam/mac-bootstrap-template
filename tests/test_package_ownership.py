"""Behavior tests for package manager ownership and migration (Issue #164)."""

import json
import os
import shutil
import subprocess
import tempfile
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

    # Test owner for homebrew/core normalized package
    res = subprocess.run(
        [str(OWNERSHIP_SCRIPT), "owner", "homebrew/core/uv"],
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

    # Test owner for custom tapped formula with same base name defaults to brew
    res = subprocess.run(
        [str(OWNERSHIP_SCRIPT), "owner", "custom/tap/fd"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout.strip() == "brew"

    # Test owner with tapped formula
    res = subprocess.run(
        [str(OWNERSHIP_SCRIPT), "owner", "anomalyco/tap/opencode-v2"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout.strip() == "brew"


def test_ownership_manifest_missing_fails_loud(tmp_path):
    env = os.environ.copy()
    env["PACKAGE_OWNERSHIP_MANIFEST"] = str(tmp_path / "nonexistent.json")

    res = subprocess.run(
        [str(OWNERSHIP_SCRIPT), "list-zb"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode != 0
    assert "not found" in res.stderr


def test_ownership_is_independent_of_upstream_metadata(tmp_path):
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
    brewfile = TEMPLATE / "Brewfile"
    assert brewfile.exists()
    content = brewfile.read_text()
    assert 'ENV["HOMEBREW_MAC_BOOTSTRAP_PRIVATE_DIR"]' in content
    assert 'ENV["HOMEBREW_MAC_BOOTSTRAP_PROFILE"]' in content


def test_normal_reconcile_halts_on_ownership_mismatch(tmp_path):
    short_zb = tempfile.mkdtemp(prefix="zb", dir="/tmp")
    try:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()

        mock_brew = bin_dir / "brew"
        mock_brew.write_text("""#!/usr/bin/env bash
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
        env["ZEROBREW_ROOT"] = short_zb
        env["ZEROBREW_PREFIX"] = short_zb

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
    finally:
        shutil.rmtree(short_zb, ignore_errors=True)


def test_explicit_migrate_dependency_preflight_blocks_uninstall(tmp_path):
    short_zb = tempfile.mkdtemp(prefix="zb", dir="/tmp")
    try:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()

        mock_brew_log = tmp_path / "brew_calls.log"
        mock_brew = bin_dir / "brew"
        mock_brew.write_text(f"""#!/usr/bin/env bash
echo "brew $@" >> "{mock_brew_log}"
if [ "$1" = "bundle" ] && [ "$2" = "list" ]; then
    echo "uv"
    echo "fd"
    exit 0
fi
if [ "$1" = "list" ] && [ "$2" = "--formula" ]; then
    echo "uv"
    echo "fd"
    exit 0
fi
if [ "$1" = "uses" ] && [ "$2" = "--installed" ]; then
    if [ "$3" = "fd" ]; then
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
        env["ZEROBREW_ROOT"] = short_zb
        env["ZEROBREW_PREFIX"] = short_zb

        res = subprocess.run(
            [str(BREW_BUNDLE_SCRIPT), "migrate"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert res.returncode != 0
        assert "Dependency blocker" in res.stderr
        assert "some-dependent-app" in res.stderr

        # Assert no uninstall was attempted for ANY candidate
        log_content = mock_brew_log.read_text()
        assert "uninstall" not in log_content
    finally:
        shutil.rmtree(short_zb, ignore_errors=True)


def test_explicit_migrate_runtime_verification_failure_blocks_uninstall(tmp_path):
    # Candidate 'uv' fails runtime execution (returns exit 1 on --version)
    short_zb = tempfile.mkdtemp(prefix="zb", dir="/tmp")
    try:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()

        zb_bin = Path(short_zb) / "bin"
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
    exit 0
fi
if [ "$1" = "uninstall" ]; then
    echo "uninstall $2" >> "{mock_brew_log}"
    exit 0
fi
exit 0
""")
        mock_brew.chmod(0o755)

        mock_zb = bin_dir / "zb"
        mock_zb.write_text(f"""#!/usr/bin/env bash
if [ "$5" = "install" ]; then
    # Create uv binary that fails runtime execution
    echo '#!/bin/sh' > "{zb_bin}/uv"
    echo 'echo "Fatal runtime error: missing dynamic library" >&2' >> "{zb_bin}/uv"
    echo 'exit 1' >> "{zb_bin}/uv"
    chmod +x "{zb_bin}/uv"
    exit 0
fi
exit 0
""")
        mock_zb.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["ZEROBREW_ROOT"] = short_zb
        env["ZEROBREW_PREFIX"] = short_zb

        res = subprocess.run(
            [str(BREW_BUNDLE_SCRIPT), "migrate"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert res.returncode != 0
        assert "Verification failed for uv" in res.stderr

        # Assert no uninstall was called because runtime verification failed
        log_content = mock_brew_log.read_text()
        assert "uninstall" not in log_content
    finally:
        shutil.rmtree(short_zb, ignore_errors=True)


def test_explicit_migrate_success_flow_verifies_bins_and_removes(tmp_path):
    short_zb = tempfile.mkdtemp(prefix="zb", dir="/tmp")
    try:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()

        zb_bin = Path(short_zb) / "bin"
        zb_bin.mkdir(parents=True)
        zb_plugins = Path(short_zb) / "lib" / "docker" / "cli-plugins"
        zb_plugins.mkdir(parents=True)

        mock_brew_log = tmp_path / "brew_calls.log"
        mock_brew = bin_dir / "brew"
        mock_brew.write_text(f"""#!/usr/bin/env bash
echo "brew $@" >> "{mock_brew_log}"
if [ "$1" = "bundle" ] && [ "$2" = "list" ]; then
    echo "uv"
    echo "ast-grep"
    echo "docker-compose"
    exit 0
fi
if [ "$1" = "list" ] && [ "$2" = "--formula" ]; then
    echo "uv"
    echo "ast-grep"
    echo "docker-compose"
    exit 0
fi
if [ "$1" = "uses" ] && [ "$2" = "--installed" ]; then
    exit 0
fi
if [ "$1" = "uninstall" ]; then
    echo "uninstalled $2" >> "{mock_brew_log}"
    exit 0
fi
exit 0
""")
        mock_brew.chmod(0o755)

        mock_zb = bin_dir / "zb"
        mock_zb.write_text(f"""#!/usr/bin/env bash
if [ "$5" = "install" ]; then
    echo '#!/bin/sh' > "{zb_bin}/uv"
    echo 'echo uv 0.13.0' >> "{zb_bin}/uv"
    chmod +x "{zb_bin}/uv"

    echo '#!/bin/sh' > "{zb_bin}/ast-grep"
    echo 'echo ast-grep 0.50.0' >> "{zb_bin}/ast-grep"
    chmod +x "{zb_bin}/ast-grep"

    echo '#!/bin/sh' > "{zb_plugins}/docker-compose"
    echo 'echo Docker Compose version v2.29.0' >> "{zb_plugins}/docker-compose"
    chmod +x "{zb_plugins}/docker-compose"
    exit 0
fi
exit 0
""")
        mock_zb.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["ZEROBREW_ROOT"] = short_zb
        env["ZEROBREW_PREFIX"] = short_zb

        res = subprocess.run(
            [str(BREW_BUNDLE_SCRIPT), "migrate"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert res.returncode == 0
        assert "Preflight passed" in res.stdout
        assert "Verification succeeded" in res.stdout
        assert "Migration complete" in res.stdout

        log_content = mock_brew_log.read_text()
        assert "brew uninstall uv" in log_content
        assert "brew uninstall ast-grep" in log_content
        assert "brew uninstall docker-compose" in log_content
    finally:
        shutil.rmtree(short_zb, ignore_errors=True)
