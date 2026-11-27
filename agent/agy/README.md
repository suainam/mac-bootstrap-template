# Antigravity (`agy`) Configuration & Gemini API CLI

## Settings Layering

`make agent-apply` runs `configure_antigravity_settings_file` (`scripts/lib/agent-mcp.sh`), which merges:

1. `template/agent/agy/settings.json` (public defaults: sandbox mode, tool permissions)
2. `private/agent/agy/settings.json` (machine-specific overrides: `trustedWorkspaces`, UI flags)

into `~/.gemini/antigravity-cli/settings.json`, and ensures `~/.gemini/antigravity-cli/skills` is listed under `skills`.

## `gemini-api` CLI & `gemini-skills`

- **CLI installer**: `scripts/install-gemini-api.sh` (registered in `manifests/external-tools.json`, installs to `~/.local/bin/gemini-api` via `google-gemini/gemini-api-cli`).
- **Skills**: `google-gemini-skills` (`gemini-api-cli`, `gemini-api-dev`, `gemini-live-api-dev`, `gemini-omni-flash-api`) are registered in `agent-skills/registry/sources.jsonc` and distributed to `~/.gemini/antigravity-cli/skills/` (and other agents) via `make skill-refresh`.
- **Auth** (never commit keys to `template/`):
  - `export GEMINI_API_KEY="..."` (env var, highest precedence after CLI flags), or
  - `gemini-api configure --api-key "..."` (OS keychain), or
  - `~/.config/gemini-api/config.yaml` (fallback).
- **Verify**:
  - `gemini-api --version`
  - `gemini-api whoami`
  - `gemini-api models`
  - `gemini-api image "test icon" --dry-run`
