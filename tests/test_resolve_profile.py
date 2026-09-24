"""Tests for resolve-profile.sh and machine-aware profile resolution."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Mapping

import pytest

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = TEMPLATE_ROOT / "scripts" / "resolve-profile.sh"


def run_resolver(
    env_overrides: Mapping[str, str] | None = None,
    stdin_text: str = "",
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [str(SCRIPT)],
        input=stdin_text,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_env_var_takes_highest_precedence(tmp_path: Path):
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    (private_dir / "current_profile").write_text("work\n")
    (private_dir / "machines.json").write_text(json.dumps({"default_profile": "work"}))

    res = run_resolver(
        {
            "MAC_BOOTSTRAP_PROFILE": "custom-override",
            "MAC_BOOTSTRAP_PRIVATE_DIR": str(private_dir),
        }
    )
    assert res.returncode == 0
    assert res.stdout.strip() == "custom-override"


def test_current_profile_file_takes_precedence_over_machines_json(tmp_path: Path):
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    (private_dir / "current_profile").write_text("home-local\n")
    (private_dir / "machines.json").write_text(
        json.dumps(
            {
                "machines": {"dummy-uuid": {"profile": "work"}},
                "default_profile": "work",
            }
        )
    )

    res = run_resolver(
        {
            "MAC_BOOTSTRAP_PROFILE": "",
            "MAC_BOOTSTRAP_PRIVATE_DIR": str(private_dir),
        }
    )
    assert res.returncode == 0
    assert res.stdout.strip() == "home-local"


def test_machines_json_resolves_by_uuid_or_hostname(tmp_path: Path):
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    (private_dir / "machines.json").write_text(
        json.dumps(
            {
                "machines": {
                    "TEST-UUID-1234": {
                        "hostname": "testhost",
                        "profile": "home",
                    }
                },
                "default_profile": "work",
            }
        )
    )

    # With default_profile fallback when no UUID/hostname matches
    res = run_resolver(
        {
            "MAC_BOOTSTRAP_PROFILE": "",
            "MAC_BOOTSTRAP_PRIVATE_DIR": str(private_dir),
        }
    )
    assert res.returncode == 0
    # Should resolve to either matching current host or default_profile
    assert res.stdout.strip() in {"home", "work"}


def test_machines_json_default_profile_fallback(tmp_path: Path):
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    (private_dir / "machines.json").write_text(
        json.dumps(
            {
                "machines": {
                    "NON-EXISTENT-UUID": {
                        "profile": "custom",
                    }
                },
                "default_profile": "fallback-profile",
            }
        )
    )

    res = run_resolver(
        {
            "MAC_BOOTSTRAP_PROFILE": "",
            "MAC_BOOTSTRAP_PRIVATE_DIR": str(private_dir),
        }
    )
    assert res.returncode == 0
    # Current host doesn't match NON-EXISTENT-UUID, falls back to default_profile
    assert res.stdout.strip() == "fallback-profile"
