#!/usr/bin/env python3
"""Data-driven tooling doctor for mac-bootstrap."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def run_checked(args: list[str], *, env: dict[str, str] | None = None) -> list[str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False, env=env)
    except OSError as exc:
        raise RuntimeError(f"command failed ({' '.join(args)}): {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"command failed ({' '.join(args)}): {detail}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def has_command(name: str) -> bool:
    return shutil.which(name) is not None


def has_app(name: str) -> bool:
    return Path("/Applications", name).is_dir() or Path.home().joinpath("Applications", name).is_dir()


def has_npm(name: str) -> bool:
    try:
        result = subprocess.run(
            ["npm", "list", "-g", name, "--depth=0"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(errors="ignore"))
    except (OSError, json.JSONDecodeError):
        return {}


def bundle_env(template_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    private_dir = env.get("HOMEBREW_MAC_BOOTSTRAP_PRIVATE_DIR") or env.get("MAC_BOOTSTRAP_PRIVATE_DIR")
    if not private_dir:
        candidate = template_root.parent / "private"
        if candidate.is_dir():
            private_dir = str(candidate.resolve())

    profile = env.get("HOMEBREW_MAC_BOOTSTRAP_PROFILE") or env.get("MAC_BOOTSTRAP_PROFILE")
    if not profile:
        for rel in ("scripts/resolve-profile.sh", "resolve-profile.sh"):
            resolver = template_root / rel
            if resolver.is_file() and os.access(resolver, os.X_OK):
                probe_env = env.copy()
                if private_dir:
                    probe_env["MAC_BOOTSTRAP_PRIVATE_DIR"] = private_dir
                res = subprocess.run(
                    [str(resolver)],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=probe_env,
                )
                if res.returncode == 0 and res.stdout.strip():
                    profile = res.stdout.strip()
                    break

    if private_dir:
        env["MAC_BOOTSTRAP_PRIVATE_DIR"] = private_dir
        env["HOMEBREW_MAC_BOOTSTRAP_PRIVATE_DIR"] = private_dir
    if profile:
        env["MAC_BOOTSTRAP_PROFILE"] = profile
        env["HOMEBREW_MAC_BOOTSTRAP_PROFILE"] = profile
    return env


def evaluate_brewfile(brewfile: Path, env: dict[str, str] | None = None) -> dict[str, list[str]]:
    active_env = env if env is not None else bundle_env(brewfile.parent)
    flag_map = {
        "brew": "--formula",
        "cask": "--cask",
        "npm": "--npm",
    }
    return {
        key: run_checked(["brew", "bundle", "list", f"--file={brewfile}", flag], env=active_env)
        for key, flag in flag_map.items()
    }


def brew_list(kind: str) -> set[str]:
    args = ["brew", "list", kind]
    if kind == "--formula":
        args.append("--full-name")
    return set(run_checked(args))


def zb_list(root: str | None = None) -> set[str]:
    zb_root = root or os.environ.get("ZEROBREW_ROOT", "/opt/zerobrew")
    lines = run_checked(["zb", "--root", zb_root, "list"])
    return {line.split()[0] for line in lines if line.split()}


def load_zb_ownership(template_root: Path) -> set[str]:
    manifest_override = os.environ.get("PACKAGE_OWNERSHIP_MANIFEST")
    path = Path(manifest_override) if manifest_override else template_root / "scripts" / "package-ownership.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"missing or invalid ownership manifest ({path}): {exc}") from exc
    formulas = data.get("zerobrew_formulas")
    if not isinstance(formulas, list) or not all(isinstance(item, str) and item for item in formulas):
        raise RuntimeError(f"invalid zerobrew_formulas in ownership manifest ({path})")
    return set(formulas)


def expected_formula_owner(name: str, zb_manifest: set[str]) -> str:
    normalized = name.removeprefix("homebrew/core/").removeprefix("core/")
    if name in zb_manifest or normalized in zb_manifest:
        return "zb"
    return "brew"


def check_formulae(
    declared_formulas: list[str],
    brew_installed: set[str],
    zb_installed: set[str],
    zb_manifest: set[str],
    formula_cmd_overrides: dict[str, str],
) -> bool:
    missing = False
    print("=== Formulae ===")
    for name in declared_formulas:
        expected = expected_formula_owner(name, zb_manifest)
        short_name = name.split("/")[-1]
        normalized = name.removeprefix("homebrew/core/").removeprefix("core/")
        in_brew = normalized in brew_installed
        if "/" not in name:
            in_brew = in_brew or any(item.endswith("/" + name) for item in brew_installed)
        in_zb = name in zb_installed or (
            short_name in zb_installed and (expected == "zb" or short_name not in zb_manifest)
        )

        if in_brew and in_zb:
            print(f"duplicate formula owner: {name} (installed in both brew and zb, expected {expected})")
            missing = True
            continue

        if expected == "zb":
            if in_zb:
                alias = formula_cmd_overrides.get(name)
                suffix = f" [cmd: {alias}]" if alias else ""
                print(f"ok formula: {name} (zb){suffix}")
            elif in_brew:
                print(f"wrong formula owner: {name} (installed in brew, expected zb)")
                missing = True
            else:
                print(f"missing formula: {name} (expected zb)")
                missing = True
        else:
            if in_brew:
                alias = formula_cmd_overrides.get(name)
                suffix = f" [cmd: {alias}]" if alias else ""
                print(f"ok formula: {name} (brew){suffix}")
            elif in_zb:
                print(f"wrong formula owner: {name} (installed in zb, expected brew)")
                missing = True
            else:
                print(f"missing formula: {name} (expected brew)")
                missing = True
    return missing

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

def check_ssh_config(template_root: Path) -> bool:
    script = template_root / "scripts" / "ssh-manage.sh"
    print("=== SSH config ===")
    if not script.is_file():
        print(f"skip ssh config: {script} not found")
        return False
    result = subprocess.run(
        [str(script), "verify"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        print("ok ssh config: deploy, permissions, and ssh -G resolution")
        return False
    detail = (result.stderr or result.stdout).strip() or "no detail"
    for line in detail.splitlines()[-5:]:
        print(f"missing ssh config: {line}")
    return True


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
    args = [arg for arg in argv[1:] if arg != "--strict"]
    if len(args) != 2 or any(arg.startswith("-") for arg in args):
        print("Usage: run-doctor-checks.py <Brewfile> <manifest.json> [--strict]", file=sys.stderr)
        return 2

    brewfile = Path(args[0])
    template_root = brewfile.parent
    try:
        manifest = json.loads(Path(args[1]).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Doctor error: invalid doctor manifest ({args[1]}): {exc}", file=sys.stderr)
        print("Doctor failed.")
        return 1

    try:
        zb_manifest = load_zb_ownership(template_root)
        declared = evaluate_brewfile(brewfile)
        brew_formulas = brew_list("--formula")
        zb_formulas = zb_list()
        casks = brew_list("--cask")
    except RuntimeError as exc:
        print(f"Doctor error: {exc}", file=sys.stderr)
        print("Doctor failed.")
        return 1

    formula_cmd_overrides = manifest.get("formula_command_overrides", {})
    cask_overrides = manifest.get("cask_overrides", {})
    missing = check_formulae(
        declared["brew"],
        brew_formulas,
        zb_formulas,
        zb_manifest,
        formula_cmd_overrides,
    )
    print("=== Standalone CLIs ===")
    for item in manifest.get("standalone_clis", []):
        commands = item.get("commands", [])
        matched = next((cmd for cmd in commands if has_command(cmd)), None)
        if matched:
            suffix = f" ({matched})" if matched != item["name"] else ""
            print(f"ok cli: {item['name']}{suffix}")
        elif item.get("optional"):
            print(f"skip optional cli: {item['name']}")
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

    if check_ssh_config(template_root):
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
