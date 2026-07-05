from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CURRENT_DIR = Path(__file__).resolve().parent
TEMPLATE_ROOT = CURRENT_DIR.parents[1]
REPO_ROOT = TEMPLATE_ROOT.parent

RUNTIME_CONFIG = REPO_ROOT / "private" / "agent" / "data_hub.runtime.jsonc"


@dataclass(frozen=True)
class DataHubPaths:
    repo_root: Path
    template_root: Path
    data_hub_dir: Path
    db_path: Path
    vault_dir: Path
    daily_dir: str
    runs_dir: Path
    git_search_roots: list[Path]
    llm_config_path: Path


@dataclass(frozen=True)
class AgentLogPaths:
    claude_projects_dir: Path
    codex_sessions_dir: Path
    opencode_sessions_dir: Path
    agy_brain_dir: Path


@dataclass(frozen=True)
class SourceInput:
    source_type: str
    relative_root: str
    pattern: str


@dataclass(frozen=True)
class DataHubConfig:
    paths: DataHubPaths
    agent_logs: AgentLogPaths
    sources: list[SourceInput]
    llm: dict[str, Any]
    workflow: dict[str, Any]


def strip_jsonc_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("//"):
            lines.append(line)
    return "\n".join(lines)


def expand_path(value: str | Path) -> Path:
    return Path(os.path.expandvars(str(value))).expanduser()


def load_runtime_json() -> tuple[dict[str, Any], Path]:
    if RUNTIME_CONFIG.exists():
        return json.loads(strip_jsonc_comments(RUNTIME_CONFIG.read_text(encoding="utf-8"))), RUNTIME_CONFIG
    return {}, RUNTIME_CONFIG


def runtime_path(config: dict[str, Any], key: str, env_key: str, default: Path | str) -> Path:
    paths = config.get("paths", {})
    if env_key in os.environ:
        return expand_path(os.environ[env_key])
    if key in paths:
        return expand_path(paths[key])
    return expand_path(default)


def runtime_text(config: dict[str, Any], key: str, env_key: str, default: str) -> str:
    paths = config.get("paths", {})
    if env_key in os.environ:
        return os.environ[env_key]
    if key in paths:
        return str(paths[key])
    return default


def default_sources() -> list[SourceInput]:
    return [
        SourceInput("meeting_note", "50_Sources/Meetings", "*.md"),
        SourceInput("mind_map", "50_Sources/Mindmaps", "*.xmind"),
        SourceInput("wiki_page", "50_Sources/Wiki-Clips", "*.md"),
        SourceInput("wiki_pdf", "50_Sources/Wiki-Clips", "*.pdf"),
        SourceInput("wiki_html", "50_Sources/Wiki-Clips", "*.html"),
    ]


def build_sources(config: dict[str, Any]) -> list[SourceInput]:
    configured = config.get("sources", {}).get("inputs")
    if not configured:
        return default_sources()
    return [
        SourceInput(
            source_type=str(item["source_type"]),
            relative_root=str(item["relative_root"]),
            pattern=str(item["pattern"]),
        )
        for item in configured
    ]


def build_agent_logs(config: dict[str, Any]) -> AgentLogPaths:
    logs = config.get("agent_logs", {})
    home = Path.home()
    opencode_default = home / ".config" / "opencode" / "sessions"
    codex_default = opencode_default if opencode_default.exists() else home / ".codex" / "sessions"
    return AgentLogPaths(
        claude_projects_dir=expand_path(logs.get("claude_projects_dir", home / ".claude" / "projects")),
        codex_sessions_dir=expand_path(logs.get("codex_sessions_dir", codex_default)),
        opencode_sessions_dir=expand_path(logs.get("opencode_sessions_dir", opencode_default)),
        agy_brain_dir=expand_path(logs.get("agy_brain_dir", home / ".gemini" / "antigravity-cli" / "brain")),
    )


def get_runtime_config() -> DataHubConfig:
    raw_config, llm_config_path = load_runtime_json()
    paths = DataHubPaths(
        repo_root=runtime_path(raw_config, "repo_root", "DATA_HUB_REPO_ROOT", REPO_ROOT),
        template_root=runtime_path(raw_config, "template_root", "DATA_HUB_TEMPLATE_ROOT", TEMPLATE_ROOT),
        data_hub_dir=runtime_path(raw_config, "data_hub_dir", "DATA_HUB_DIR", CURRENT_DIR),
        db_path=runtime_path(
            raw_config,
            "db_path",
            "AGENT_DB_PATH",
            REPO_ROOT / "private" / "agent" / "data" / "agent_history.db",
        ),
        vault_dir=runtime_path(raw_config, "vault_dir", "OBSIDIAN_VAULT_DIR", Path.home() / "work" / "knowledge"),
        daily_dir=runtime_text(raw_config, "daily_dir", "OBSIDIAN_DAILY_DIR", "10_Periodic/Daily"),
        runs_dir=runtime_path(
            raw_config,
            "runs_dir",
            "AGENT_RUNS_DIR",
            runtime_path(
                raw_config,
                "db_path",
                "AGENT_DB_PATH",
                REPO_ROOT / "private" / "agent" / "data" / "agent_history.db",
            ).parent
            / "runs",
        ),
        git_search_roots=[
            expand_path(part)
            for part in runtime_text(raw_config, "git_search_roots", "GIT_SEARCH_ROOTS", str(Path.home() / "work" / "projects")).split(",")
            if part.strip()
        ],
        llm_config_path=llm_config_path,
    )
    return DataHubConfig(
        paths=paths,
        agent_logs=build_agent_logs(raw_config),
        sources=build_sources(raw_config),
        llm=dict(raw_config.get("llm", raw_config if "backends" in raw_config else {})),
        workflow=dict(raw_config.get("workflow", {})),
    )


def get_db_path() -> Path:
    return get_runtime_config().paths.db_path


def get_vault_dir() -> Path:
    return get_runtime_config().paths.vault_dir


def get_runs_dir() -> Path:
    return get_runtime_config().paths.runs_dir
