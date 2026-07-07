#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
from typing import Any, Mapping


@dataclass
class DevSpaceConfig:
    source_path: Path
    allowed_roots: list[Path]
    host: str
    port: int
    public_base_url: str
    cloudflare_tunnel_token: str
    node_preference: str
    install_mode: str
    devspace_bin: str
    npm_bin: str
    log_dir: Path


@dataclass
class ResolvedBinaries:
    node: str
    npm: str
    devspace: str
    brew: str


def strip_jsonc(text: str) -> str:
    out: list[str] = []
    in_string = False
    escaped = False
    i = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def expand_env(value: str, env: Mapping[str, str] | None = None) -> str:
    source = dict(os.environ if env is None else env)
    home = source.get("HOME", str(Path.home()))
    return os.path.expandvars(value.replace("$HOME", home))


def load_devspace_config(
    repo_root: Path,
    config_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> DevSpaceConfig:
    repo_root = repo_root.resolve()
    source_path = (config_path or repo_root / "private" / "agent" / "devspace.runtime.jsonc").resolve()
    if not source_path.exists():
        raise FileNotFoundError(
            f"DevSpace runtime config not found: {source_path}. "
            "Create private/agent/devspace.runtime.jsonc from template/agent/devspace.runtime.example.jsonc."
        )
    data = json.loads(strip_jsonc(source_path.read_text(encoding="utf-8")))
    paths = data.get("paths") or {}
    server = data.get("server") or {}
    exposure = data.get("exposure") or {}
    runtime = data.get("runtime") or {}
    allowed_roots = [
        Path(expand_env(item, env)).expanduser().resolve()
        for item in (paths.get("allowed_roots") or [])
    ]
    log_dir = Path(
        expand_env(
            runtime.get("log_dir", str(repo_root / "private" / "agent" / "logs" / "devspace")),
            env,
        )
    ).expanduser()
    return DevSpaceConfig(
        source_path=source_path,
        allowed_roots=allowed_roots,
        host=server.get("host", "127.0.0.1"),
        port=int(server.get("port", 7676)),
        public_base_url=exposure.get("public_base_url", ""),
        cloudflare_tunnel_token=exposure.get("cloudflare_tunnel_token", ""),
        node_preference=runtime.get("node_preference", "auto"),
        install_mode=runtime.get("install_mode", "brew+npm"),
        devspace_bin=runtime.get("devspace_bin", ""),
        npm_bin=runtime.get("npm_bin", ""),
        log_dir=log_dir.resolve(),
    )


def validate_config(config: DevSpaceConfig) -> list[str]:
    errors: list[str] = []
    if not config.allowed_roots:
        errors.append("paths.allowed_roots must contain at least one directory")
    for index, root in enumerate(config.allowed_roots):
        if not root.exists():
            errors.append(f"paths.allowed_roots[{index}] does not exist")
        elif not root.is_dir():
            errors.append(f"paths.allowed_roots[{index}] is not a directory")
    if not config.host:
        errors.append("server.host must not be empty")
    if not 1 <= config.port <= 65535:
        errors.append("server.port must be between 1 and 65535")
    if config.public_base_url:
        if not config.public_base_url.startswith("https://"):
            errors.append("exposure.public_base_url must start with https://")
        if config.public_base_url.rstrip("/").endswith("/mcp"):
            errors.append("exposure.public_base_url must not include /mcp")
    if config.install_mode != "brew+npm":
        errors.append("runtime.install_mode must be brew+npm in phase 1")
    return errors


def render_effective_config(config: DevSpaceConfig) -> dict[str, object]:
    return {
        "source_path": str(config.source_path),
        "paths": {"allowed_roots": [str(path) for path in config.allowed_roots]},
        "server": {"host": config.host, "port": config.port},
        "exposure": {
            "public_base_url": config.public_base_url,
            "cloudflare_tunnel_token": "configured" if config.cloudflare_tunnel_token else "",
        },
        "runtime": {
            "node_preference": config.node_preference,
            "install_mode": config.install_mode,
            "devspace_bin": config.devspace_bin,
            "npm_bin": config.npm_bin,
            "log_dir": str(config.log_dir),
        },
    }


def is_node_compatible(node_bin: str) -> bool:
    try:
        version_text = subprocess.run(
            [node_bin, "--version"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    version = version_text.lstrip("v")
    parts = version.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return False
    if major == 22:
        return minor >= 19
    return 22 < major < 27


def resolve_binaries(config: DevSpaceConfig, env: Mapping[str, str] | None = None) -> ResolvedBinaries:
    path_env = None if env is None else env.get("PATH")
    brew = shutil.which("brew", path=path_env) or "/opt/homebrew/bin/brew"
    npm = config.npm_bin or shutil.which("npm", path=path_env) or ""
    devspace = config.devspace_bin or shutil.which("devspace", path=path_env) or ""

    candidates: list[str] = []
    explicit = shutil.which("node", path=path_env)
    if explicit:
        candidates.append(explicit)
    for candidate in (
        "/opt/homebrew/opt/node@22/bin/node",
        "/usr/local/opt/node@22/bin/node",
    ):
        if candidate not in candidates:
            candidates.append(candidate)
    node = ""
    for candidate in candidates:
        if is_node_compatible(candidate):
            node = candidate
            break
    return ResolvedBinaries(node=node, npm=npm, devspace=devspace, brew=brew)


def build_install_commands(config: DevSpaceConfig, bins: ResolvedBinaries) -> list[list[str]]:
    commands: list[list[str]] = []
    if not bins.node:
        commands.append([bins.brew, "install", "node@22"])
        commands.append([bins.brew, "link", "--overwrite", "--force", "node@22"])
    if not bins.devspace:
        npm_bin = bins.npm or "npm"
        commands.append([npm_bin, "install", "-g", "@waishnav/devspace"])
    return commands


def build_run_command(config: DevSpaceConfig, bins: ResolvedBinaries) -> list[str]:
    return [bins.devspace, "serve"]


def build_run_env(config: DevSpaceConfig, env: Mapping[str, str] | None = None) -> dict[str, str]:
    base = dict(os.environ if env is None else env)
    base["HOST"] = config.host
    base["PORT"] = str(config.port)
    base["DEVSPACE_ALLOWED_ROOTS"] = ",".join(str(root) for root in config.allowed_roots)
    if config.public_base_url:
        base["DEVSPACE_PUBLIC_BASE_URL"] = config.public_base_url.rstrip("/")
    return base


def check_port_available(host: str, port: int) -> tuple[bool, str]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
    except OSError as exc:
        return False, str(exc)
    finally:
        sock.close()
    return True, "available"


def probe_local_mcp(host: str, port: int, timeout: float = 2.0) -> tuple[int | None, str]:
    try:
        conn = HTTPConnection(host, port, timeout=timeout)
        conn.request("GET", "/mcp")
        response = conn.getresponse()
        return response.status, response.reason
    except OSError as exc:
        return None, str(exc)


def get_devspace_doctor_output(devspace_bin: str) -> tuple[int, str]:
    try:
        result = subprocess.run(
            [devspace_bin, "doctor"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return 127, "devspace binary not found"
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part).strip()
    return result.returncode, output


def validate_devspace_setup(doctor_output: str) -> list[str]:
    errors: list[str] = []
    if "Run: devspace init" in doctor_output:
        errors.append("devspace is not initialized; run `devspace init` or provide DEVSPACE_OAUTH_OWNER_TOKEN before `run`")
    if "Config file: missing" in doctor_output:
        errors.append("~/.devspace/config.json is missing")
    if "Auth file: missing" in doctor_output:
        errors.append("~/.devspace/auth.json is missing")
    return errors


def ensure_valid_config(config: DevSpaceConfig) -> list[str]:
    return validate_config(config)


def print_errors(errors: list[str]) -> None:
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)


def cmd_print_config(args: argparse.Namespace) -> int:
    config = load_devspace_config(repo_root=args.repo_root, config_path=args.config)
    print(json.dumps(render_effective_config(config), ensure_ascii=False, indent=2))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    config = load_devspace_config(repo_root=args.repo_root, config_path=args.config)
    errors = ensure_valid_config(config)
    bins = resolve_binaries(config)
    if not bins.node:
        errors.append("node binary not found or not compatible with DevSpace >=22.19 <27")
    if not bins.npm and not config.npm_bin:
        errors.append("npm binary not found")
    doctor_output = ""
    if bins.devspace:
        _, doctor_output = get_devspace_doctor_output(bins.devspace)
        errors.extend(validate_devspace_setup(doctor_output))
    if errors:
        print_errors(errors)
        if doctor_output:
            print(doctor_output)
        return 1
    print(json.dumps(render_effective_config(config), ensure_ascii=False, indent=2))
    print(f"node={bins.node}")
    print(f"npm={bins.npm or 'MISSING'}")
    print(f"devspace={bins.devspace or 'MISSING'}")
    if doctor_output:
        print(doctor_output)
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    config = load_devspace_config(repo_root=args.repo_root, config_path=args.config)
    errors = ensure_valid_config(config)
    if errors:
        print_errors(errors)
        return 1
    bins = resolve_binaries(config)
    commands = build_install_commands(config, bins)
    if not commands:
        print("Already installed: compatible node and devspace present")
        return 0
    for command in commands:
        print("+", " ".join(command))
        if not args.dry_run:
            subprocess.run(command, check=True)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = load_devspace_config(repo_root=args.repo_root, config_path=args.config)
    errors = ensure_valid_config(config)
    if errors:
        print_errors(errors)
        return 1
    bins = resolve_binaries(config)
    if not bins.devspace:
        print("ERROR: devspace binary not found; run install first", file=sys.stderr)
        return 1
    _, doctor_output = get_devspace_doctor_output(bins.devspace)
    setup_errors = validate_devspace_setup(doctor_output)
    if setup_errors:
        print_errors(setup_errors)
        print(doctor_output)
        return 1
    available, detail = check_port_available(config.host, config.port)
    if not available:
        print(f"ERROR: port conflict on {config.host}:{config.port}: {detail}", file=sys.stderr)
        return 1
    config.log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = config.log_dir / "devspace.stdout.log"
    stderr_path = config.log_dir / "devspace.stderr.log"
    command = build_run_command(config, bins)
    print("+", " ".join(command), flush=True)
    run_env = build_run_env(config)
    with stdout_path.open("a", encoding="utf-8") as stdout_handle, stderr_path.open("a", encoding="utf-8") as stderr_handle:
        process = subprocess.Popen(command, stdout=stdout_handle, stderr=stderr_handle, env=run_env)

        def terminate_child(signum: int, frame: object) -> None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            raise SystemExit(128 + signum)

        old_sigterm = signal.signal(signal.SIGTERM, terminate_child)
        old_sigint = signal.signal(signal.SIGINT, terminate_child)
        try:
            return process.wait()
        finally:
            signal.signal(signal.SIGTERM, old_sigterm)
            signal.signal(signal.SIGINT, old_sigint)


def cmd_doctor(args: argparse.Namespace) -> int:
    config = load_devspace_config(repo_root=args.repo_root, config_path=args.config)
    errors = ensure_valid_config(config)
    if errors:
        print("CONFIG ERROR")
        for error in errors:
            print(error)
        return 1
    status, probe_detail = probe_local_mcp(config.host, config.port)
    if status is not None:
        print(f"OK: /mcp returned {status} {probe_detail}")
        print(f"LOG DIR: {config.log_dir}")
        return 0
    available, detail = check_port_available(config.host, config.port)
    if not available:
        print(f"RUNTIME CONFLICT: {config.host}:{config.port} -> {detail}")
        print(f"LOCAL PROBE: {probe_detail}")
        print(f"LOG DIR: {config.log_dir}")
        return 1
    print(f"SERVICE FAILURE: local /mcp probe failed: {probe_detail}")
    print(f"LOG DIR: {config.log_dir}")
    return 1


def cmd_tunnel_run(args: argparse.Namespace) -> int:
    config = load_devspace_config(repo_root=args.repo_root, config_path=args.config)
    errors = ensure_valid_config(config)
    if errors:
        print_errors(errors)
        return 1
    if not config.cloudflare_tunnel_token:
        print("ERROR: exposure.cloudflare_tunnel_token is missing", file=sys.stderr)
        return 1
    command = ["cloudflared", "tunnel", "run", "--token", config.cloudflare_tunnel_token]
    print("+ cloudflared tunnel run --token <redacted>", flush=True)
    if args.dry_run:
        return 0
    return subprocess.run(command, check=False).returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devspace_local")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("print-config").set_defaults(func=cmd_print_config)
    sub.add_parser("check").set_defaults(func=cmd_check)
    sub.add_parser("install").set_defaults(func=cmd_install)
    sub.add_parser("run").set_defaults(func=cmd_run)
    sub.add_parser("doctor").set_defaults(func=cmd_doctor)
    sub.add_parser("tunnel-run").set_defaults(func=cmd_tunnel_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
