#!/usr/bin/env python3
"""Data-driven tooling doctor for mac-bootstrap."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def run_stdout(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    return result.stdout.strip()


def has_command(name: str) -> bool:
    return shutil.which(name) is not None


def has_app(name: str) -> bool:
    return Path("/Applications", name).is_dir() or Path.home().joinpath("Applications", name).is_dir()


def has_npm(name: str) -> bool:
    result = subprocess.run(
        ["npm", "list", "-g", name, "--depth=0"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(errors="ignore"))
    except (OSError, json.JSONDecodeError):
        return {}


def brew_list(kind: str) -> set[str]:
    return {line for line in run_stdout("brew", "list", kind).splitlines() if line}


def parse_brewfile(path: Path) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {"brew": [], "cask": [], "npm": []}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        for key in buckets:
            prefix = f'{key} "'
            if line.startswith(prefix) and line.endswith('"'):
                buckets[key].append(line[len(prefix):-1])
                break
    return buckets


def expected_symlink_targets(template_root: Path, manifest: dict) -> dict[Path, Path]:
    managed = manifest.get("managed_symlinks", {})
    return {
        Path(os.path.expanduser(link_path)): template_root / target
        for link_path, target in managed.items()
    }


def check_managed_symlinks(template_root: Path, manifest: dict) -> bool:
    expected = expected_symlink_targets(template_root, manifest)
    missing = False

    print("=== Managed symlinks ===")
    for link_path, target_path in expected.items():
        if not link_path.is_symlink():
            print(f"missing symlink: {link_path} -> {target_path}")
            missing = True
            continue
        if not link_path.exists():
            print(f"broken symlink: {link_path} -> {target_path}")
            missing = True
            continue

        actual = link_path.resolve()
        expected_target = target_path.resolve()
        if actual != expected_target:
            print(f"stale symlink: {link_path} -> {actual} (expected {expected_target})")
            missing = True
            continue

        print(f"ok symlink: {link_path}")

    return missing


def check_chrome_gemini(manifest: dict) -> bool:
    config = manifest.get("chrome_gemini", {})
    if not config.get("enabled"):
        return False

    profile = config.get("profile", "Default")
    chrome_root = Path.home() / "Library/Application Support/Google/Chrome"
    local_state = read_json(chrome_root / "Local State")
    preferences = read_json(chrome_root / profile / "Preferences")
    missing = False

    print("=== Chrome Gemini ===")
    if not local_state and not preferences:
        print(f"skip chrome gemini: Chrome profile data not found ({chrome_root})")
        return False

    profile_info = local_state.get("profile", {}).get("info_cache", {}).get(profile, {})
    if profile_info.get("is_glic_eligible") is not True:
        print(f"skip chrome gemini: profile {profile} is not marked Glic/Gemini eligible")
        return False

    launcher_enabled = local_state.get("glic", {}).get("launcher_enabled")
    completed_fre = preferences.get("glic", {}).get("completed_fre")
    side_panel_width = preferences.get("side_panel", {}).get("id_to_width", {}).get("kGlic")

    if launcher_enabled is True:
        print("ok chrome gemini: launcher enabled")
    else:
        print("missing chrome gemini: launcher is disabled in Chrome Local State")
        missing = True

    if completed_fre == 1:
        print("ok chrome gemini: first-run flow completed")
    else:
        print("missing chrome gemini: first-run flow not completed")
        missing = True

    if side_panel_width:
        print(f"ok chrome gemini: side panel width recorded ({side_panel_width})")
    else:
        print("warn chrome gemini: side panel width not recorded yet")

    return missing


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("Usage: run-doctor-checks.py <Brewfile> <manifest.json>", file=sys.stderr)
        return 2

    brewfile = Path(argv[1])
    template_root = brewfile.parent
    manifest = json.loads(Path(argv[2]).read_text())
    declared = parse_brewfile(brewfile)

    formulas = brew_list("--formula")
    casks = brew_list("--cask")
    formula_cmd_overrides = manifest.get("formula_command_overrides", {})
    cask_overrides = manifest.get("cask_overrides", {})
    missing = False

    print("=== Formulae ===")
    for name in declared["brew"]:
        if name in formulas:
            print(f"ok formula: {name}")
            continue
        cmd = formula_cmd_overrides.get(name, name)
        if has_command(cmd):
            print(f"ok command: {cmd} (formula: {name})")
        else:
            print(f"missing formula: {name}")
            missing = True

    print("=== Standalone CLIs ===")
    for item in manifest.get("standalone_clis", []):
        commands = item.get("commands", [])
        matched = next((cmd for cmd in commands if has_command(cmd)), None)
        if matched:
            suffix = f" ({matched})" if matched != item["name"] else ""
            print(f"ok cli: {item['name']}{suffix}")
        else:
            print(f"missing cli: {item['name']}")
            missing = True

    print("=== Casks and apps ===")
    for token in declared["cask"]:
        if token in casks:
            print(f"ok cask: {token}")
            continue
        override = cask_overrides.get(token, {})
        app = override.get("app")
        command = override.get("command")
        optional = bool(override.get("optional"))
        if app and has_app(app):
            print(f"ok manual app: {app} (not managed by brew cask: {token})")
        elif command and has_command(command):
            print(f"ok command: {command} (cask: {token})")
        elif optional:
            label = app or token
            print(f"skip optional cask/app: {token} ({label})")
        else:
            label = app or token
            print(f"missing cask/app: {token} ({label})")
            missing = True

    if check_managed_symlinks(template_root, manifest):
        missing = True

    if check_chrome_gemini(manifest):
        missing = True

    print("=== npm CLIs ===")
    for name in declared["npm"]:
        if has_npm(name):
            print(f"ok npm: {name}")
        else:
            print(f"missing npm: {name}")
            missing = True

    if missing:
        print("Doctor failed.")
        return 1

    print("Doctor passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
