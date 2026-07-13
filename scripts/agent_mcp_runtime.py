#!/usr/bin/env python3
"""Normalized desired state for managed agent MCP servers."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
import tomllib
from typing import Any, Callable, Mapping


MANAGED_NAMES = (
    "context-mode",
    "codebase-memory-mcp",
    "agent-prompt-library",
    "context7",
    "devspace",
)
RETIRED_ALIASES = ("code-review-graph", "codebase-memory", "x-docs", "xapi")
CONTEXT7_PROXY_KEYS = {
    "NODE_USE_ENV_PROXY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "http_proxy",
    "https_proxy",
    "ALL_PROXY",
    "all_proxy",
    "NO_PROXY",
    "no_proxy",
}

CBM_TOOLS = (
    "search_graph",
    "trace_path",
    "get_code_snippet",
    "get_architecture",
    "query_graph",
    "search_code",
    "detect_changes",
    "index_repository",
    "list_projects",
    "get_graph_schema",
    "index_status",
    "manage_adr",
    "ingest_traces",
)

CONTEXT_MODE_TOOLS = ("ctx_stats", "ctx_search", "ctx_index", "ctx_doctor")


@dataclass(frozen=True)
class RuntimeInputs:
    home: Path
    bootstrap: Path
    context7_command: str
    context7_key: str = ""
    http_proxy: str = ""
    https_proxy: str = ""
    all_proxy: str = ""
    no_proxy: str = "localhost,127.0.0.1,::1"
    devspace_enabled: bool = False
    devspace_url: str = ""

    @classmethod
    def from_env(
        cls,
        *,
        bootstrap: Path,
        context7_command: str,
        environ: Mapping[str, str] | None = None,
    ) -> "RuntimeInputs":
        env = os.environ if environ is None else environ
        http_proxy = env.get("HTTP_PROXY") or env.get("http_proxy", "")
        return cls(
            home=Path(env.get("HOME", str(Path.home()))),
            bootstrap=bootstrap,
            context7_command=context7_command,
            context7_key=env.get("CONTEXT7_KEY", ""),
            http_proxy=http_proxy,
            https_proxy=env.get("HTTPS_PROXY") or env.get("https_proxy") or http_proxy,
            all_proxy=env.get("ALL_PROXY") or env.get("all_proxy") or http_proxy,
            no_proxy=env.get("NO_PROXY") or env.get("no_proxy") or "localhost,127.0.0.1,::1",
            devspace_enabled=env.get("DEVSPACE_MCP_ENABLE") == "1",
            devspace_url=env.get("DEVSPACE_MCP_URL", ""),
        )


@dataclass(frozen=True)
class ServerSpec:
    name: str
    transport: str
    command: str = ""
    args: tuple[str, ...] = ()
    url: str = ""
    env: Mapping[str, str] = field(default_factory=dict)
    startup_timeout_sec: int | None = None
    tool_approvals: tuple[str, ...] = ()
    enabled: bool = True
    hosts: tuple[str, ...] = (
        "codex",
        "claude",
        "opencode",
        "pi",
        "reasonix",
        "antigravity",
    )


@dataclass(frozen=True)
class AuditIssue:
    code: str
    server: str = ""


def managed_server_names() -> tuple[str, ...]:
    return MANAGED_NAMES


def retired_server_names() -> tuple[str, ...]:
    return RETIRED_ALIASES


def desired_servers(inputs: RuntimeInputs) -> dict[str, ServerSpec]:
    context7_args: list[str] = []
    if inputs.context7_command == "npx":
        context7_args.extend(("-y", "@upstash/context7-mcp"))
    if inputs.context7_key:
        context7_args.extend(("--api-key", inputs.context7_key))

    context7_env: dict[str, str] = {}
    if inputs.http_proxy:
        context7_env = {
            "NODE_USE_ENV_PROXY": "1",
            "HTTP_PROXY": inputs.http_proxy,
            "HTTPS_PROXY": inputs.https_proxy or inputs.http_proxy,
            "http_proxy": inputs.http_proxy,
            "https_proxy": inputs.https_proxy or inputs.http_proxy,
            "ALL_PROXY": inputs.all_proxy or inputs.http_proxy,
            "all_proxy": inputs.all_proxy or inputs.http_proxy,
            "NO_PROXY": inputs.no_proxy,
            "no_proxy": inputs.no_proxy,
        }

    servers = {
        "context-mode": ServerSpec(
            "context-mode",
            "local",
            command="context-mode",
            tool_approvals=CONTEXT_MODE_TOOLS,
            hosts=("codex",),
        ),
        "codebase-memory-mcp": ServerSpec(
            "codebase-memory-mcp",
            "local",
            command="codebase-memory-mcp",
            tool_approvals=CBM_TOOLS,
        ),
        "agent-prompt-library": ServerSpec(
            "agent-prompt-library",
            "local",
            command=str(inputs.home / ".local/bin/agent-prompt-mcp"),
            tool_approvals=("search_prompts",),
        ),
        "context7": ServerSpec(
            "context7",
            "local",
            command=inputs.context7_command,
            args=tuple(context7_args),
            env=context7_env,
        ),
    }
    if inputs.devspace_enabled and inputs.devspace_url:
        servers["devspace"] = ServerSpec("devspace", "remote", url=inputs.devspace_url)
    return servers


def load_mcp_policy(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError(f"invalid MCP policy: {path}")
    defaults = value.get("default_enabled")
    profiles = value.get("profiles")
    if not isinstance(defaults, dict) or not isinstance(profiles, dict):
        raise ValueError(f"invalid MCP policy shape: {path}")
    unknown = set(defaults) - set(MANAGED_NAMES)
    for profile, names in profiles.items():
        if not isinstance(profile, str) or not isinstance(names, list):
            raise ValueError(f"invalid MCP profile: {profile}")
        unknown.update(set(names) - set(MANAGED_NAMES))
    if unknown:
        raise ValueError(f"unknown MCP names in policy: {', '.join(sorted(unknown))}")
    return value


def apply_default_policy(
    desired: Mapping[str, ServerSpec], policy: Mapping[str, Any]
) -> dict[str, ServerSpec]:
    defaults = policy["default_enabled"]
    return {
        name: replace(spec, enabled=bool(defaults.get(name, True)))
        for name, spec in desired.items()
    }


def adapt_server(host: str, spec: ServerSpec) -> dict[str, Any]:
    if host == "opencode":
        if spec.transport == "remote":
            return {"enabled": True, "type": "remote", "url": spec.url}
        result: dict[str, Any] = {
            "enabled": True,
            "type": "local",
            "command": [spec.command, *spec.args],
        }
    elif host == "claude" and spec.transport == "remote":
        return {"type": "http", "url": spec.url}
    elif spec.transport == "remote":
        return {"url": spec.url}
    else:
        result = {"command": spec.command, "args": list(spec.args)}

    if spec.env:
        result["env"] = dict(spec.env)
    if spec.startup_timeout_sec is not None:
        result["startup_timeout_sec"] = spec.startup_timeout_sec
    return result


def render_json_config(
    host: str,
    existing: Mapping[str, Any],
    desired: Mapping[str, ServerSpec],
) -> dict[str, Any]:
    root_key = "mcp" if host == "opencode" else "mcpServers"
    result = deepcopy(dict(existing))
    if host == "reasonix":
        result.setdefault("skipSetup", False)
    current = result.get(root_key)
    servers = deepcopy(current) if isinstance(current, dict) else {}
    for name in MANAGED_NAMES:
        if name in desired and host in desired[name].hosts:
            servers[name] = adapt_server(host, desired[name])
        else:
            servers.pop(name, None)
    for name in RETIRED_ALIASES:
        servers.pop(name, None)
    result[root_key] = servers
    return result


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_array(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def render_codex_toml(desired: Mapping[str, ServerSpec]) -> str:
    sections = ["# BEGIN MAC-BOOTSTRAP MANAGED MCPS"]
    for name, spec in desired.items():
        if "codex" not in spec.hosts:
            continue
        lines = [f"[mcp_servers.{name}]"]
        lines.append(f"enabled = {'true' if spec.enabled else 'false'}")
        if spec.transport == "remote":
            lines.append(f"url = {_toml_string(spec.url)}")
        else:
            lines.append(f"command = {_toml_string(spec.command)}")
            lines.append(f"args = {_toml_array(spec.args)}")
            if spec.startup_timeout_sec is not None:
                lines.append(f"startup_timeout_sec = {spec.startup_timeout_sec}")
        sections.append("\n".join(lines))
        if spec.env:
            env_lines = [f"[mcp_servers.{name}.env]"]
            env_lines.extend(
                f"{key} = {_toml_string(value)}" for key, value in spec.env.items()
            )
            sections.append("\n".join(env_lines))
        for tool in spec.tool_approvals:
            sections.append(
                f"[mcp_servers.{name}.tools.{tool}]\napproval_mode = \"approve\""
            )
    sections.append("# END MAC-BOOTSTRAP MANAGED MCPS")
    return "\n\n".join(sections) + "\n"


def parse_codex_toml(text: str) -> dict[str, Any]:
    return tomllib.loads(text)


def _codex_server(spec: ServerSpec) -> dict[str, Any]:
    if spec.transport == "remote":
        result: dict[str, Any] = {"url": spec.url}
    else:
        result = {"command": spec.command, "args": list(spec.args)}
        if spec.startup_timeout_sec is not None:
            result["startup_timeout_sec"] = spec.startup_timeout_sec
    if spec.env:
        result["env"] = dict(spec.env)
    if spec.tool_approvals:
        result["tools"] = {
            tool: {"approval_mode": "approve"} for tool in spec.tool_approvals
        }
    result["enabled"] = spec.enabled
    return result


def _stable_server_view(name: str, value: Any) -> Any:
    if name != "context7" or not isinstance(value, dict):
        return value
    stable = deepcopy(value)
    env = stable.pop("env", None)
    if env:
        valid_env = (
            isinstance(env, dict)
            and set(env) == CONTEXT7_PROXY_KEYS
            and env.get("NODE_USE_ENV_PROXY") == "1"
            and all(isinstance(item, str) and item for item in env.values())
        )
        if not valid_env:
            stable["invalid_context7_env"] = True
    for key in ("args", "command"):
        values = stable.get(key)
        if not isinstance(values, list) or "--api-key" not in values:
            continue
        indexes = [index for index, item in enumerate(values) if item == "--api-key"]
        valid_key = (
            len(indexes) == 1
            and indexes[0] + 1 < len(values)
            and isinstance(values[indexes[0] + 1], str)
            and bool(values[indexes[0] + 1])
        )
        if valid_key:
            del values[indexes[0] : indexes[0] + 2]
        else:
            stable["invalid_context7_api_key"] = True
    return stable


def audit_config(
    host: str,
    config: Mapping[str, Any],
    desired: Mapping[str, ServerSpec],
    *,
    external_hooks_present: bool = False,
    executable_resolver: Callable[[str], str | None] | None = None,
) -> list[AuditIssue]:
    root_key = "mcp" if host == "opencode" else "mcpServers"
    if host == "codex":
        root_key = "mcp_servers"
    observed_value = config.get(root_key, {})
    observed = observed_value if isinstance(observed_value, dict) else {}
    issues: list[AuditIssue] = []

    for name, spec in desired.items():
        if host not in spec.hosts:
            continue
        if name not in observed:
            issues.append(AuditIssue("missing_server", name))
            continue
        expected = _codex_server(spec) if host == "codex" else adapt_server(host, spec)
        if _stable_server_view(name, observed[name]) != _stable_server_view(name, expected):
            issues.append(AuditIssue("server_mismatch", name))

    for name in MANAGED_NAMES:
        if name in observed and (name not in desired or host not in desired[name].hosts):
            issues.append(AuditIssue("stale_managed_server", name))
    for name in RETIRED_ALIASES:
        if name in observed:
            issues.append(AuditIssue("retired_server", name))

    if executable_resolver is not None:
        mismatched = {issue.server for issue in issues if issue.code != "stale_managed_server"}
        for name, spec in desired.items():
            if host not in spec.hosts:
                continue
            if spec.transport == "local" and name not in mismatched:
                if executable_resolver(spec.command) is None:
                    issues.append(AuditIssue("missing_executable", name))

    hooks = config.get("hooks", {})
    toml_hooks_present = isinstance(hooks, dict) and any(key != "state" for key in hooks)
    if host == "codex" and external_hooks_present and toml_hooks_present:
        issues.append(AuditIssue("duplicate_hook_representation"))
    return issues


def _runtime_inputs(args: argparse.Namespace) -> RuntimeInputs:
    return RuntimeInputs.from_env(
        bootstrap=Path(args.bootstrap).expanduser().resolve(),
        context7_command=args.context7_command,
    )


def _write_json_atomically(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        temp_path.replace(path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bootstrap", required=True)
    parser.add_argument("--context7-command", required=True)
    parser.add_argument("--policy")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)

    json_parser = subparsers.add_parser("render-json")
    json_parser.add_argument("--host", required=True, choices=("claude", "opencode", "pi", "reasonix", "antigravity"))
    json_parser.add_argument("--path", required=True)
    _add_runtime_args(json_parser)

    codex_parser = subparsers.add_parser("render-codex")
    _add_runtime_args(codex_parser)

    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument(
        "--host",
        required=True,
        choices=("codex", "claude", "opencode", "pi", "reasonix", "antigravity"),
    )
    audit_parser.add_argument("--path", required=True)
    audit_parser.add_argument("--hooks-path")
    audit_parser.add_argument("--check-executables", action="store_true")
    _add_runtime_args(audit_parser)

    args = parser.parse_args()
    desired = desired_servers(_runtime_inputs(args))
    if args.policy:
        desired = apply_default_policy(desired, load_mcp_policy(Path(args.policy)))
    if args.action == "render-codex":
        print(render_codex_toml(desired), end="")
        return 0

    target = Path(args.path).expanduser()
    if args.action == "audit":
        if not target.exists():
            print(f"missing_config host={args.host}")
            return 1
        if args.host == "codex":
            config = parse_codex_toml(target.read_text())
        else:
            config = json.loads(target.read_text())
        resolver = shutil.which if args.check_executables else None
        hooks_present = bool(args.hooks_path and Path(args.hooks_path).expanduser().exists())
        issues = audit_config(
            args.host,
            config,
            desired,
            external_hooks_present=hooks_present,
            executable_resolver=resolver,
        )
        for issue in issues:
            suffix = f" server={issue.server}" if issue.server else ""
            print(f"{issue.code} host={args.host}{suffix}")
        return 1 if issues else 0

    existing: Mapping[str, Any] = {}
    if target.exists() and target.read_text().strip():
        loaded = json.loads(target.read_text())
        if not isinstance(loaded, dict):
            raise ValueError(f"JSON config root must be an object: {target}")
        existing = loaded
    _write_json_atomically(target, render_json_config(args.host, existing, desired))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
