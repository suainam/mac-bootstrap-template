from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any


CURRENT_DIR = Path(__file__).resolve().parent


def resolve_template_root(current_dir: Path) -> Path:
    for candidate in current_dir.parents:
        if (candidate / "agent" / "data-hub").is_dir():
            return candidate
    raise RuntimeError(f"Unable to resolve template root from {current_dir}")


def resolve_repo_root(template_root: Path) -> Path:
    for candidate in (template_root.parent, *template_root.parents):
        if (candidate / "private" / "agent").is_dir():
            return candidate
    return template_root.parent


TEMPLATE_ROOT = resolve_template_root(CURRENT_DIR)
REPO_ROOT = resolve_repo_root(TEMPLATE_ROOT)

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
class LlmWikiConfig:
    enabled: bool
    api_base: str
    project_root: Path
    project_id: str
    token_env: str
    auth_value: str
    exclude_dirs: list[str]


@dataclass(frozen=True)
class SummaryConfig:
    root_relative: str
    level_dirs: dict[str, str]
    deployment_start: str


@dataclass(frozen=True)
class DataHubConfig:
    paths: DataHubPaths
    agent_logs: AgentLogPaths
    sources: list[SourceInput]
    llm: dict[str, Any]
    workflow: dict[str, Any]
    llm_wiki: LlmWikiConfig
    summary: SummaryConfig


def strip_jsonc_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("//"):
            lines.append(line)
    return "\n".join(lines)


def expand_path(value: str | Path) -> Path:
    return Path(os.path.expandvars(str(value))).expanduser()


def expand_env_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: expand_env_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_env_values(item) for item in value]
    if isinstance(value, str):
        return os.path.expandvars(value)
    return value


def load_runtime_json() -> tuple[dict[str, Any], Path]:
    if RUNTIME_CONFIG.exists():
        raw = json.loads(strip_jsonc_comments(RUNTIME_CONFIG.read_text(encoding="utf-8")))
        return expand_env_values(raw), RUNTIME_CONFIG
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
        SourceInput("meeting_note", "raw/sources/Meetings", "*.md"),
        SourceInput("mind_map", "raw/sources/Mindmaps", "*.xmind"),
        SourceInput("wiki_page", "raw/sources/Wiki-Clips", "*.md"),
        SourceInput("wiki_pdf", "raw/sources/Wiki-Clips", "*.pdf"),
        SourceInput("wiki_html", "raw/sources/Wiki-Clips", "*.html"),
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


def build_llm_wiki(config: dict[str, Any], vault_dir: Path) -> LlmWikiConfig:
    raw = config.get("llm_wiki", {})
    return LlmWikiConfig(
        enabled=bool(raw.get("enabled", False)),
        api_base=str(raw.get("api_base", "http://127.0.0.1:19828")),
        project_root=expand_path(raw.get("project_root", vault_dir)),
        project_id=str(raw.get("project_id", "")),
        token_env=str(raw.get("token_env", "LLM_WIKI_TOKEN")),
        auth_value=str(raw.get("token", "")),
        exclude_dirs=list(raw.get("exclude_dirs", ["70_Summaries"])),
    )


def build_summary(config: dict[str, Any]) -> SummaryConfig:
    raw = config.get("summary", {})
    return SummaryConfig(
        root_relative=str(raw.get("root_relative", "70_Summaries")),
        level_dirs={
            "daily": str(raw.get("daily_dir", "Daily")),
            "weekly": str(raw.get("weekly_dir", "Weekly")),
            "monthly": str(raw.get("monthly_dir", "Monthly")),
            "quarterly": str(raw.get("quarterly_dir", "Quarterly")),
            "yearly": str(raw.get("yearly_dir", "Yearly")),
        },
        deployment_start=str(raw.get("deployment_start", "2026-07-10")),
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
    llm_wiki = build_llm_wiki(raw_config, paths.vault_dir)
    summary = build_summary(raw_config)
    return DataHubConfig(
        paths=paths,
        agent_logs=build_agent_logs(raw_config),
        sources=build_sources(raw_config),
        llm=dict(raw_config.get("llm", raw_config if "backends" in raw_config else {})),
        workflow=dict(raw_config.get("workflow", {})),
        llm_wiki=llm_wiki,
        summary=summary,
    )


def get_db_path() -> Path:
    return get_runtime_config().paths.db_path


def get_vault_dir() -> Path:
    return get_runtime_config().paths.vault_dir


def get_runs_dir() -> Path:
    return get_runtime_config().paths.runs_dir


def get_summary_output_dir(level: str) -> Path:
    config = get_runtime_config()
    return config.paths.vault_dir / config.summary.root_relative / config.summary.level_dirs[level]


def load_prompt_template(name: str) -> Template | None:
    """加载 prompt 模板，优先 private 覆盖，回退 template 默认。"""
    config = get_runtime_config()
    private_path = config.paths.repo_root / "private" / "agent" / "prompts" / name
    template_path = config.paths.template_root / "agent" / "data-hub" / "prompts" / name
    for path in [private_path, template_path]:
        if path.exists():
            return Template(path.read_text(encoding="utf-8"))
    return None
