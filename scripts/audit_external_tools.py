#!/usr/bin/env python3
"""Audit external-tools manifest drift for the active machine profile.

Compares declared external tools (common + active profile) against actual
filesystem inventory in bounded roots, excluding Brew-owned packages,
repo-managed scripts, and system artifacts.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMMON_MANIFEST = TEMPLATE_ROOT / "manifests" / "external-tools.json"
DEFAULT_RESOLVE_SCRIPT = TEMPLATE_ROOT / "scripts" / "resolve-profile.sh"
DEFAULT_DOCTOR_MANIFEST = TEMPLATE_ROOT / "scripts" / "doctor-manifest.json"
DEFAULT_LAUNCHD_DIR = TEMPLATE_ROOT / "launchd"


def resolve_private_dir(template_root: Path = TEMPLATE_ROOT, env: dict[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    for var in ("MAC_BOOTSTRAP_PRIVATE_DIR", "HOMEBREW_MAC_BOOTSTRAP_PRIVATE_DIR"):
        val = source.get(var)
        if val and Path(val).is_dir():
            return Path(val).resolve()
    sibling = template_root.parent / "private"
    if sibling.is_dir():
        return sibling.resolve()
    inner = template_root / "private"
    if inner.is_dir():
        return inner.resolve()
    return sibling


def resolve_profile(
    resolve_script: Path | None = None,
    private_dir: Path | None = None,
    env: dict[str, str] | None = None,
) -> str:
    source = os.environ if env is None else env
    for var in ("MAC_BOOTSTRAP_PROFILE", "HOMEBREW_MAC_BOOTSTRAP_PROFILE"):
        val = source.get(var)
        if val:
            return val.strip()

    script = resolve_script or DEFAULT_RESOLVE_SCRIPT
    if script and script.is_file() and os.access(script, os.X_OK):
        p_env = dict(source)
        if private_dir:
            p_env["MAC_BOOTSTRAP_PRIVATE_DIR"] = str(private_dir)
        try:
            out = subprocess.run([str(script)], capture_output=True, text=True, timeout=10, env=p_env)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass

    resolved_private = private_dir or resolve_private_dir(env=source)
    current_profile_file = resolved_private / "current_profile"
    if current_profile_file.is_file():
        try:
            val = current_profile_file.read_text(encoding="utf-8").strip()
            if val:
                return val
        except OSError:
            pass

    raise ValueError(
        "cannot resolve active machine profile: please set MAC_BOOTSTRAP_PROFILE or private/current_profile"
    )


def load_manifest_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in manifest {path}: {exc}") from exc


def load_all_profile_declared_plist_names(
    common_manifest_path: Path, private_dir: Path
) -> set[str]:
    names = set()
    common_data = load_manifest_file(common_manifest_path)
    for item in common_data.get("daemons", []):
        for p in item.get("plist_paths", []):
            names.add(Path(os.path.expanduser(p)).name)

    profiles_root = private_dir / "profiles"
    if profiles_root.is_dir():
        for prof_dir in profiles_root.iterdir():
            if not prof_dir.is_dir():
                continue
            manifest = prof_dir / "external-tools.json"
            if manifest.is_file():
                p_data = load_manifest_file(manifest)
                for item in p_data.get("daemons", []):
                    for p in item.get("plist_paths", []):
                        names.add(Path(os.path.expanduser(p)).name)
    return names


def load_effective_manifest(
    common_manifest_path: Path | None = None,
    profile: str | None = None,
    private_dir: Path | None = None,
    resolve_script: Path | None = None,
) -> tuple[dict, str, Path]:
    c_path = common_manifest_path or DEFAULT_COMMON_MANIFEST
    if not c_path.is_file():
        raise FileNotFoundError(f"common manifest not found: {c_path}")

    p_dir = private_dir or resolve_private_dir()
    act_profile = profile or resolve_profile(resolve_script=resolve_script, private_dir=p_dir)

    common_data = load_manifest_file(c_path)
    profile_path = p_dir / "profiles" / act_profile / "external-tools.json"
    profile_data = load_manifest_file(profile_path) if profile_path.is_file() else {}

    merged: dict[str, list] = {
        "standalone_binaries": [],
        "external_apps": [],
        "daemons": [],
    }

    # Merge standalone_binaries
    seen_bins: set[str] = set()
    for item in common_data.get("standalone_binaries", []) + profile_data.get("standalone_binaries", []):
        key = item.get("name") or item.get("target")
        if key and key not in seen_bins:
            seen_bins.add(key)
            merged["standalone_binaries"].append(item)

    # Merge external_apps
    seen_apps: set[str] = set()
    for item in common_data.get("external_apps", []) + profile_data.get("external_apps", []):
        key = item.get("app") or item.get("name")
        if key and key not in seen_apps:
            seen_apps.add(key)
            merged["external_apps"].append(item)

    # Merge daemons
    seen_daemons: set[str] = set()
    for item in common_data.get("daemons", []) + profile_data.get("daemons", []):
        key = item.get("name")
        if key and key not in seen_daemons:
            seen_daemons.add(key)
            merged["daemons"].append(item)

    return merged, act_profile, profile_path


def _normalize_app_name(raw: object) -> str | None:
    if isinstance(raw, str):
        return Path(raw).name
    if isinstance(raw, dict):
        val = raw.get("target") or raw.get("name")
        return Path(val).name if isinstance(val, str) else None
    if isinstance(raw, (list, tuple)) and raw:
        return _normalize_app_name(raw[0])
    return None


def get_brew_installed_artifacts() -> tuple[set[str], set[str], set[str]]:
    """Extract apps, plists, and bundle IDs from installed Brew casks and services."""
    if not shutil.which("brew"):
        raise RuntimeError("brew CLI not found in PATH")
    res = subprocess.run(
        ["brew", "info", "--json=v2", "--casks", "--installed"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if res.returncode != 0:
        raise RuntimeError(f"brew info failed (exit {res.returncode}): {res.stderr.strip()}")

    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"failed to parse brew info JSON: {exc}") from exc

    services_res = subprocess.run(
        ["brew", "services", "list", "--json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if services_res.returncode != 0:
        raise RuntimeError(f"brew services list failed (exit {services_res.returncode}): {services_res.stderr.strip()}")

    try:
        services_data = json.loads(services_res.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"failed to parse brew services JSON: {exc}") from exc

    if not isinstance(services_data, list):
        raise RuntimeError(f"failed to parse brew services JSON: expected list, got {type(services_data).__name__}")

    apps = set()
    plists = set()
    bundle_ids = set()

    for svc in services_data:
        if not isinstance(svc, dict):
            raise RuntimeError(f"failed to parse brew services JSON: expected dict item, got {type(svc).__name__}")
        file_path = svc.get("file")
        if file_path is not None:
            if not isinstance(file_path, str):
                raise RuntimeError(f"failed to parse brew services JSON: expected string for 'file', got {type(file_path).__name__}")
            base = Path(file_path.strip()).name
            if base:
                plists.add(base)
    for cask in data.get("casks", []):
        for art in cask.get("artifacts", []):
            if not isinstance(art, dict):
                continue
            if "app" in art:
                for a in art["app"]:
                    norm = _normalize_app_name(a)
                    if norm:
                        apps.add(norm)
            if "uninstall" in art:
                for u in art["uninstall"]:
                    if isinstance(u, dict):
                        if "delete" in u:
                            del_items = u["delete"] if isinstance(u["delete"], list) else [u["delete"]]
                            for d in del_items:
                                if not isinstance(d, str):
                                    continue
                                base = Path(d).name
                                if base.endswith(".app"):
                                    apps.add(base)
                                elif base.endswith(".plist"):
                                    plists.add(base)
                        if "launchctl" in u:
                            labels = u["launchctl"] if isinstance(u["launchctl"], list) else [u["launchctl"]]
                            for lab in labels:
                                if isinstance(lab, str):
                                    plists.add(f"{Path(lab).name}.plist")
                        if "pkgutil" in u:
                            pkgs = u["pkgutil"] if isinstance(u["pkgutil"], list) else [u["pkgutil"]]
                            for pkg in pkgs:
                                if not isinstance(pkg, str):
                                    continue
                                try:
                                    pkg_out = subprocess.run(
                                        ["pkgutil", "--files", pkg],
                                        capture_output=True,
                                        text=True,
                                        timeout=5,
                                    )
                                    if pkg_out.returncode == 0:
                                        for line in pkg_out.stdout.splitlines():
                                            if line.endswith(".app"):
                                                apps.add(Path(line).name)
                                except Exception:
                                    pass
                        if "quit" in u:
                            q = u["quit"]
                            q_items = q if isinstance(q, list) else [q]
                            for item in q_items:
                                if isinstance(item, str):
                                    bundle_ids.add(item)

    return apps, plists, bundle_ids


def get_app_bundle_id(app_path: Path) -> str | None:
    info_plist = app_path / "Contents" / "Info.plist"
    if info_plist.is_file():
        try:
            with open(info_plist, "rb") as f:
                data = plistlib.load(f)
                return data.get("CFBundleIdentifier")
        except Exception:
            pass
    return None


def is_system_app(app_path: Path) -> bool:
    if app_path.name in ("Safari.app", "Utilities"):
        return True
    bundle_id = get_app_bundle_id(app_path)
    return bool(bundle_id and bundle_id.startswith("com.apple."))


def is_system_plist(plist_path: Path) -> bool:
    return plist_path.name.startswith("com.apple.")


def check_missing(manifest: dict, app_search_roots: list[Path]) -> list[str]:
    drift = []

    # 1. Standalone binaries
    for item in manifest.get("standalone_binaries", []):
        name = item.get("name", "?")
        target_str = item.get("target")
        if not target_str:
            drift.append(f"  binary '{name}': manifest has no 'target'")
            continue
        p = Path(os.path.expanduser(target_str))
        if not p.exists():
            drift.append(f"  binary '{name}': MISSING target {target_str}")
        elif not os.access(p, os.X_OK):
            drift.append(f"  binary '{name}': target not executable {target_str}")

    # 2. External apps (pure filesystem check)
    for item in manifest.get("external_apps", []):
        name = item.get("name", "?")
        app_name = item.get("app")
        bundle_id = item.get("bundle_id")
        if not app_name:
            drift.append(f"  app '{name}': manifest has no 'app'")
            continue

        found = False
        for root in app_search_roots:
            candidate = root / app_name
            if candidate.is_dir():
                found = True
                break
            if bundle_id:
                for existing in root.glob("*.app"):
                    if get_app_bundle_id(existing) == bundle_id:
                        found = True
                        break
                if found:
                    break

        if not found:
            drift.append(f"  app '{name}': MISSING {app_name}")

    # 3. Daemons (plist existence probe only)
    for item in manifest.get("daemons", []):
        name = item.get("name", "?")
        plist_paths = item.get("plist_paths", [])
        if not plist_paths:
            drift.append(f"  daemon '{name}': manifest has no 'plist_paths'")
            continue
        found = any(Path(os.path.expanduser(p)).exists() for p in plist_paths)
        if not found:
            drift.append(f"  daemon '{name}': MISSING plist at {plist_paths}")

    return drift


def check_unexpected(
    manifest: dict,
    bin_roots: list[Path],
    app_roots: list[Path],
    launchd_roots: list[Path],
    brew_apps: set[str],
    brew_plists: set[str],
    brew_bundle_ids: set[str],
    all_declared_daemon_plists: set[str],
    launchd_dir: Path = DEFAULT_LAUNCHD_DIR,
) -> list[str]:
    drift = []

    # Declared sets with absolute expanded paths
    declared_bin_paths = {
        Path(os.path.expanduser(item["target"])).resolve()
        for item in manifest.get("standalone_binaries", [])
        if item.get("target")
    }
    declared_app_names = {
        item["app"] for item in manifest.get("external_apps", []) if item.get("app")
    }
    declared_app_bundle_ids = {
        item["bundle_id"] for item in manifest.get("external_apps", []) if item.get("bundle_id")
    }
    declared_plist_paths = {
        Path(os.path.expanduser(p)).resolve()
        for item in manifest.get("daemons", [])
        for p in item.get("plist_paths", [])
    }

    # Template maintenance agents: only exclude plists not declared in ANY profile/common
    maintenance_plists = set()
    if launchd_dir.is_dir():
        for p in launchd_dir.glob("*.plist"):
            if p.name not in all_declared_daemon_plists:
                maintenance_plists.add(p.name)

    repo_prefixes = [str(TEMPLATE_ROOT.resolve()), str(TEMPLATE_ROOT.parent.resolve())]

    # 1. Bounded Binaries Roots (~/.local/bin)
    for b_root in bin_roots:
        if not b_root.is_dir():
            continue
        for entry in b_root.iterdir():
            try:
                resolved = entry.resolve()
            except OSError:
                resolved = entry

            if resolved in declared_bin_paths or entry in declared_bin_paths:
                continue

            # Check if symlink points into repo, brew, or known tools
            if entry.is_symlink():
                target_str = str(resolved)
                if any(target_str.startswith(prefix) for prefix in repo_prefixes):
                    continue
                if "/opt/homebrew" in target_str or "/usr/local" in target_str or "Cellar" in resolved.parts:
                    continue
                if ".local/share/uv" in target_str or target_str.endswith(".app/Contents/MacOS/" + entry.name):
                    continue

            drift.append(f"  binary '{entry.name}': UNEXPECTED in {b_root}")

    # 2. Bounded App Roots (/Applications, ~/Applications)
    for a_root in app_roots:
        if not a_root.is_dir():
            continue
        for entry in a_root.iterdir():
            if not entry.name.endswith(".app"):
                continue
            if entry.name in declared_app_names:
                continue
            if entry.name in brew_apps:
                continue

            # Check bundle identifier
            bundle_id = get_app_bundle_id(entry)
            if bundle_id:
                if bundle_id in declared_app_bundle_ids:
                    continue
                if bundle_id in brew_bundle_ids:
                    continue

            if is_system_app(entry):
                continue

            drift.append(f"  app '{entry.name}': UNEXPECTED in {a_root}")

    # 3. Bounded Launchd Roots
    for l_root in launchd_roots:
        if not l_root.is_dir():
            continue
        for entry in l_root.glob("*.plist"):
            try:
                resolved = entry.resolve()
            except OSError:
                resolved = entry

            if resolved in declared_plist_paths or entry in declared_plist_paths:
                continue
            if entry.name in maintenance_plists:
                continue
            if entry.name in brew_plists:
                continue
            if is_system_plist(entry):
                continue
            drift.append(f"  daemon '{entry.name}': UNEXPECTED in {l_root}")

    return drift


def run_audit(
    common_manifest_path: Path | None = None,
    profile: str | None = None,
    private_dir: Path | None = None,
    resolve_script: Path | None = None,
    bin_roots: list[Path] | None = None,
    app_roots: list[Path] | None = None,
    launchd_roots: list[Path] | None = None,
    skip_brew: bool = False,
) -> tuple[int, list[str], str]:
    c_path = common_manifest_path or DEFAULT_COMMON_MANIFEST
    p_dir = private_dir or resolve_private_dir()

    try:
        manifest, act_profile, _ = load_effective_manifest(
            common_manifest_path=c_path,
            profile=profile,
            private_dir=p_dir,
            resolve_script=resolve_script,
        )
    except (FileNotFoundError, ValueError) as exc:
        return 3, [str(exc)], profile or "unknown"

    act_bin_roots = bin_roots if bin_roots is not None else [Path("~/.local/bin").expanduser()]
    act_app_roots = (
        app_roots
        if app_roots is not None
        else [Path("/Applications"), Path("~/Applications").expanduser()]
    )
    act_launchd_roots = (
        launchd_roots
        if launchd_roots is not None
        else [
            Path("~/Library/LaunchAgents").expanduser(),
            Path("/Library/LaunchAgents"),
            Path("/Library/LaunchDaemons"),
        ]
    )

    drift = check_missing(manifest, act_app_roots)

    if skip_brew:
        brew_apps, brew_plists, brew_bundle_ids = set(), set(), set()
    else:
        try:
            brew_apps, brew_plists, brew_bundle_ids = get_brew_installed_artifacts()
        except RuntimeError as exc:
            return 3, [f"audit configuration error: {exc}"], act_profile

    all_declared_daemon_plists = load_all_profile_declared_plist_names(c_path, p_dir)

    drift += check_unexpected(
        manifest=manifest,
        bin_roots=act_bin_roots,
        app_roots=act_app_roots,
        launchd_roots=act_launchd_roots,
        brew_apps=brew_apps,
        brew_plists=brew_plists,
        brew_bundle_ids=brew_bundle_ids,
        all_declared_daemon_plists=all_declared_daemon_plists,
    )

    code = 2 if drift else 0
    return code, drift, act_profile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", "--common-manifest", dest="common_manifest", type=Path, default=DEFAULT_COMMON_MANIFEST)
    parser.add_argument("--profile", default=None, help="Machine profile override")
    parser.add_argument("--private-dir", type=Path, default=None, help="Private directory override")
    parser.add_argument("--resolve-script", type=Path, default=DEFAULT_RESOLVE_SCRIPT)
    parser.add_argument("--dump-manifest", action="store_true", help="Print effective manifest JSON and exit")
    parser.add_argument("--bin-root", type=Path, action="append", dest="bin_roots", help="Override binary root for scan")
    parser.add_argument("--app-root", type=Path, action="append", dest="app_roots", help="Override app root for scan")
    parser.add_argument("--launchd-root", type=Path, action="append", dest="launchd_roots", help="Override launchd root for scan")
    parser.add_argument("--skip-brew", action="store_true", help="Skip Homebrew inspection (for test environments)")
    args = parser.parse_args()

    if args.dump_manifest:
        try:
            manifest, act_profile, _ = load_effective_manifest(
                common_manifest_path=args.common_manifest,
                profile=args.profile,
                private_dir=args.private_dir,
                resolve_script=args.resolve_script,
            )
            print(json.dumps(manifest, indent=2))
            return 0
        except Exception as exc:
            print(f"Error loading manifest: {exc}", file=sys.stderr)
            return 3

    code, drift, act_profile = run_audit(
        common_manifest_path=args.common_manifest,
        profile=args.profile,
        private_dir=args.private_dir,
        resolve_script=args.resolve_script,
        bin_roots=args.bin_roots,
        app_roots=args.app_roots,
        launchd_roots=args.launchd_roots,
        skip_brew=args.skip_brew,
    )

    if code == 3:
        for err in drift:
            print(f"manifest error: {err}", file=sys.stderr)
        return 3

    if code == 0:
        print(f"ok external tools manifest: profile={act_profile} no drift")
        return 0

    print(f"FAIL external tools drift (profile={act_profile}):")
    print("\n".join(drift))
    return 2


if __name__ == "__main__":
    sys.exit(main())
