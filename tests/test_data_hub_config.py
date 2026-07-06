from __future__ import annotations

from pathlib import Path

import sys

CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR.parent / "agent" / "data-hub"))

import data_hub_config


def configure_files(monkeypatch, tmp_path: Path, runtime_text: str = "", env_text: str = "") -> Path:
    for key in (
        "AGENT_DB_PATH",
        "OBSIDIAN_VAULT_DIR",
        "OBSIDIAN_DAILY_DIR",
        "AGENT_RUNS_DIR",
        "GIT_SEARCH_ROOTS",
        "DATA_HUB_REPO_ROOT",
        "DATA_HUB_TEMPLATE_ROOT",
        "DATA_HUB_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    private = tmp_path / "private" / "agent"
    private.mkdir(parents=True)
    runtime = private / "data_hub.runtime.jsonc"
    if runtime_text:
        runtime.write_text(runtime_text)
    monkeypatch.setattr(data_hub_config, "RUNTIME_CONFIG", runtime)
    return runtime


def test_runtime_config_loads_paths_sources_and_llm(monkeypatch, tmp_path):
    configure_files(
        monkeypatch,
        tmp_path,
        runtime_text=f"""{{
          "paths": {{
            "db_path": "{tmp_path}/agent.db",
            "vault_dir": "{tmp_path}/vault",
            "daily_dir": "Daily",
            "runs_dir": "{tmp_path}/runs",
            "git_search_roots": "{tmp_path}/repo1,{tmp_path}/repo2"
          }},
          "sources": {{"inputs": [
            {{"source_type": "meeting_note", "relative_root": "Meetings", "pattern": "*.md"}}
          ]}},
          "llm": {{"backends": [{{"name": "api", "kind": "openai_api"}}]}}
        }}""",
    )
    cfg = data_hub_config.get_runtime_config()
    assert cfg.paths.db_path == tmp_path / "agent.db"
    assert cfg.paths.vault_dir == tmp_path / "vault"
    assert cfg.paths.daily_dir == "Daily"
    assert [p.name for p in cfg.paths.git_search_roots] == ["repo1", "repo2"]
    assert cfg.sources[0].relative_root == "Meetings"
    assert cfg.llm["backends"][0]["name"] == "api"


def test_runtime_config_expands_env_vars_inside_llm_config(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_LLM_API_KEY", "secret-from-env")
    configure_files(
        monkeypatch,
        tmp_path,
        runtime_text="""{
          "llm": {
            "backends": [
              {
                "name": "api",
                "kind": "openai_api",
                "api_key": "$TEST_LLM_API_KEY"
              }
            ]
          }
        }""",
    )
    cfg = data_hub_config.get_runtime_config()
    assert cfg.llm["backends"][0]["api_key"] == "secret-from-env"


def test_shell_env_overrides_runtime_and_env_file(monkeypatch, tmp_path):
    configure_files(
        monkeypatch,
        tmp_path,
        runtime_text=f'{{"paths": {{"db_path": "{tmp_path}/runtime.db"}}}}',
        env_text=f'AGENT_DB_PATH="{tmp_path}/env-file.db"\n',
    )
    monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "shell.db"))
    cfg = data_hub_config.get_runtime_config()
    assert cfg.paths.db_path == tmp_path / "shell.db"


def test_default_paths_apply_when_runtime_and_shell_env_missing(monkeypatch, tmp_path):
    configure_files(monkeypatch, tmp_path)
    monkeypatch.delenv("OBSIDIAN_VAULT_DIR", raising=False)
    cfg = data_hub_config.get_runtime_config()
    assert cfg.paths.vault_dir == Path.home() / "work" / "knowledge"


def test_load_prompt_template_returns_template_when_file_exists(monkeypatch, tmp_path):
    runtime = configure_files(monkeypatch, tmp_path)
    template_dir = tmp_path / "template" / "agent" / "data-hub" / "prompts"
    template_dir.mkdir(parents=True)
    (template_dir / "test-prompt.md").write_text("Hello, $name!")
    runtime.write_text(f'{{"paths":{{"repo_root":"{tmp_path}","template_root":"{tmp_path}/template"}}}}')
    monkeypatch.setattr(data_hub_config, "RUNTIME_CONFIG", runtime)

    result = data_hub_config.load_prompt_template("test-prompt.md")
    assert result is not None
    assert result.substitute(name="World") == "Hello, World!"


def test_load_prompt_template_returns_none_when_not_found(monkeypatch, tmp_path):
    runtime = configure_files(monkeypatch, tmp_path)
    runtime.write_text(f'{{"paths":{{"repo_root":"{tmp_path}","template_root":"{tmp_path}/template"}}}}')
    monkeypatch.setattr(data_hub_config, "RUNTIME_CONFIG", runtime)

    result = data_hub_config.load_prompt_template("nonexistent.md")
    assert result is None


def test_load_prompt_template_private_overrides_template(monkeypatch, tmp_path):
    runtime = configure_files(monkeypatch, tmp_path)
    template_dir = tmp_path / "template" / "agent" / "data-hub" / "prompts"
    template_dir.mkdir(parents=True)
    (template_dir / "shared.md").write_text("Template version")
    private_dir = tmp_path / "private" / "agent" / "prompts"
    private_dir.mkdir(parents=True)
    (private_dir / "shared.md").write_text("Private override, $name!")
    runtime.write_text(f'{{"paths":{{"repo_root":"{tmp_path}","template_root":"{tmp_path}/template"}}}}')
    monkeypatch.setattr(data_hub_config, "RUNTIME_CONFIG", runtime)

    result = data_hub_config.load_prompt_template("shared.md")
    assert result is not None
    assert result.substitute(name="test") == "Private override, test!"
