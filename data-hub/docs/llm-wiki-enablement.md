# LLM Wiki Enablement & Verification

Runbook for turning on the `llm_wiki` integration after installing or
reinstalling the LLM Wiki app, and for diagnosing why Data Hub retrieval or
summary generation isn't using it. Architecture and evidence-boundary design
live in [2026-07-10-summary-engine-design.md](./2026-07-10-summary-engine-design.md#7-llm_wiki-集成);
this doc is the operational checklist, not a design reference.

## Why `enabled: true` isn't automatic

Installing or reinstalling the LLM Wiki app does not:

- start the app process (no listener on its API port until launched)
- flip `llm_wiki.enabled` in `private/agent/data_hub.runtime.jsonc`

Both steps are required independently. A fresh install with the right
`project_id` and API config still leaves Data Hub in local-evidence-only mode
until you complete this checklist.

## Checklist

1. **Confirm the app is running and listening.**

   ```bash
   python3 -c 'import socket; s=socket.socket(); s.settimeout(2); s.connect(("127.0.0.1", 19828)); print("listening")'
   ```

   If this fails, launch the app (`open -a "LLM Wiki"` on macOS) and retry.
   The API only comes alive when the app process is active; it is not a
   background daemon that survives app quit.

2. **Verify health and project identity.**

   ```bash
   curl -sS http://127.0.0.1:19828/api/v1/health
   curl -sS http://127.0.0.1:19828/api/v1/projects
   ```

   Confirm `ok: true`, the `version` field is current, and the project list
   contains the `project_id` configured in `data_hub.runtime.jsonc` with
   `path` matching `llm_wiki.project_root`.

3. **Check `apiConfig` in the app's own state file matches the runtime
   config's expectations.**

   ```bash
   python3 -c 'import json; from pathlib import Path; d=json.loads((Path.home()/"Library/Application Support/com.llmwiki.app/app-state.json").read_text()); print(d["apiConfig"])'
   ```

   Compare against `llm_wiki.api_config` in `data_hub.runtime.jsonc`
   (`enabled`, `mcp_enabled`, `allow_unauthenticated`, `token`). A version
   bump from reinstalling does not change these fields; they persist across
   app updates as long as the same app-state file is reused.

4. **Flip the Data Hub side switch.**

   Set `llm_wiki.enabled: true` in `private/agent/data_hub.runtime.jsonc`.
   This is the only field that gates whether `summary_evidence.py` and
   retrieval scripts call out to the app; the app being healthy does not
   imply Data Hub will use it.

5. **Run an end-to-end search probe before trusting the summary pipeline.**

   ```bash
   template/.venv/bin/python -c '
   import sys
   sys.path.insert(0, "template/data-hub")
   from data_hub_config import get_runtime_config
   from llm_wiki_client import LlmWikiClient

   cfg = get_runtime_config()
   auth_value = cfg.llm_wiki.auth_value
   client = LlmWikiClient(
       api_base=cfg.llm_wiki.api_base,
       project_id=cfg.llm_wiki.project_id,
       token_env=cfg.llm_wiki.token_env,
       token=auth_value,
   )
   results = client.search("test query", limit=3)
   print(f"{len(results)} results")
   '
   ```

   A non-empty result list confirms config loading, auth, and the project
   index are all correctly wired. Zero results with no error usually means
   the project index is empty or still building, not a config failure.

## Common failure points

- **Field name mismatch**: `LlmWikiConfig` exposes `auth_value`, not `token`.
  Code reading the dataclass directly (rather than going through
  `LlmWikiClient`) must use `cfg.llm_wiki.auth_value`.
- **Config drift after app version bump**: the `version` string recorded in
  `llm_wiki.verification.health.version` inside `data_hub.runtime.jsonc` is a
  point-in-time snapshot from when it was last verified, not an enforced
  contract. A newer running app version is expected and fine; only the API
  contract (paths, auth model) matters, not the exact version string.
- **App not auto-starting**: don't assume a reinstalled or updated app is
  running. Always confirm the port is listening (step 1) before debugging
  anything else.
