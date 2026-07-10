# Agent MCP Runtime Reconciler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one normalized MCP desired-state module render and audit every managed agent configuration, eliminating duplicated server definitions and string-only doctor checks.

**Architecture:** A small Python deep module owns the server catalog, dynamic environment resolution, host adapters, Codex TOML rendering, and semantic audit. Existing shell orchestration remains the public installation interface, but delegates MCP writes to the module. Codex managed-section rewriting stays separate because preserving user TOML is a distinct responsibility.

**Tech Stack:** Python 3.12+ standard library (`argparse`, `dataclasses`, `json`, `tomllib`), Bash adapters, pytest.

## Global Constraints

- Public reusable logic belongs under `template/`; machine facts remain outside it.
- No new runtime dependency.
- Preserve unmanaged keys and non-MCP agent configuration.
- Keep optional DevSpace and X API behavior environment-driven.
- Treat OAuth readiness separately from server process availability.
- TDD every behavior: RED, GREEN, REFACTOR.
- Retired graph-server configuration is removed, not retained as a permanent compatibility path.

---

### Task 1: Normalized Desired State

**Files:**
- Create: `scripts/agent_mcp_runtime.py`
- Create: `tests/test_agent_mcp_runtime.py`
- Modify: `Makefile`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `RuntimeInputs`, `ServerSpec`, `desired_servers(inputs)`, `managed_server_names()`.
- Produces: `adapt_server(host, spec)` and `render_json_config(host, existing, desired)`.
- Consumes: environment values already used by `agent-mcp.sh`.

- [ ] **Step 1: Write failing catalog and host-adapter tests**

Add tests proving the normalized catalog contains `context-mode`, `codebase-memory-mcp`, `agent-prompt-library`, `x-docs`, and `context7`; optional `devspace`/`xapi` appear only when enabled; JSON host adapters preserve unrelated keys and express local/remote servers in each host's format.

- [ ] **Step 2: Run test to verify RED**

Run: `.venv/bin/python -m pytest tests/test_agent_mcp_runtime.py -q`

Expected: FAIL because `scripts/agent_mcp_runtime.py` does not exist.

- [ ] **Step 3: Implement minimal desired-state module**

Implement immutable `ServerSpec(name, transport, command, args, url, env, startup_timeout_sec, tool_approvals)` and `RuntimeInputs.from_env(...)`. Keep dynamic Context7 proxy/API-key resolution inside `desired_servers`; keep host-format differences solely in `adapt_server`.

- [ ] **Step 4: Implement JSON preservation**

`render_json_config` must deep-copy the input, update only managed server names, delete disabled optional managed names, and preserve unrelated root/server keys.

- [ ] **Step 5: Run GREEN and coverage**

Run: `.venv/bin/python -m pytest tests/test_agent_mcp_runtime.py -q --cov=scripts/agent_mcp_runtime.py --cov-report=term-missing`

Expected: PASS; critical desired-state and adapter branches covered.

- [ ] **Step 6: Register syntax and coverage surfaces**

Add `scripts/agent_mcp_runtime.py` to `Makefile` syntax checking and `pyproject.toml` coverage include.

- [ ] **Step 7: Commit**

```bash
git add scripts/agent_mcp_runtime.py tests/test_agent_mcp_runtime.py Makefile pyproject.toml
git commit -m "refactor(agent): centralize MCP desired state"
```

### Task 2: Render and Apply Adapters

**Files:**
- Modify: `scripts/agent_mcp_runtime.py`
- Modify: `scripts/render-codex-mcp-block.py`
- Modify: `scripts/sync-codex-mcp-config.py`
- Modify: `scripts/lib/agent-mcp.sh`
- Modify: `tests/test_agent_mcp_runtime.py`
- Modify: `tests/test_codex_mcp_config.py`
- Modify: `tests/test_codex_mcp_helpers.py`
- Modify: `tests/test_codex_mcp_render_helpers.py`

**Interfaces:**
- Consumes: Task 1 `desired_servers`, `render_json_config`, `managed_server_names`.
- Produces: `render_codex_toml(desired)` and CLI commands `render-json`, `render-codex`, `audit`.
- Produces: Bash `write_mcp_config HOST PATH`; existing `configure_*_mcp` functions become thin adapters.

- [ ] **Step 1: Write failing Codex and CLI tests**

Test TOML output for tool approvals, proxy env, optional servers, escaping, and deterministic order. Test `render-json` preserves unrelated data and writes atomically. Test `sync-codex-mcp-config.py` derives managed prefixes without a duplicated tuple.

- [ ] **Step 2: Run focused tests to verify RED**

Run: `.venv/bin/python -m pytest tests/test_agent_mcp_runtime.py tests/test_codex_mcp_config.py tests/test_codex_mcp_helpers.py tests/test_codex_mcp_render_helpers.py -q`

Expected: FAIL on missing render/CLI behavior.

- [ ] **Step 3: Implement renderers and CLI**

Render TOML from the normalized specs. The CLI accepts explicit host/path/context7 command plus environment-driven optional settings. JSON writes use a same-directory temporary file and `Path.replace`.

- [ ] **Step 4: Convert shell MCP configuration to thin adapters**

Replace embedded per-host MCP definitions with `write_mcp_config`. Retain `write_json_file` only for non-MCP Antigravity settings. Remove retired graph-server cleanup statements after the live/source cleanup is proven.

- [ ] **Step 5: Keep Codex wrapper compatibility**

Make `render-codex-mcp-block.py` a thin import/CLI adapter. Make `sync-codex-mcp-config.py` derive prefixes from `managed_server_names()` plus the obsolete `codebase-memory` alias.

- [ ] **Step 6: Run GREEN and shell syntax**

Run: `.venv/bin/python -m pytest tests/test_agent_mcp_runtime.py tests/test_codex_mcp_config.py tests/test_codex_mcp_helpers.py tests/test_codex_mcp_render_helpers.py -q`

Run: `bash -n scripts/lib/agent-mcp.sh`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/agent_mcp_runtime.py scripts/render-codex-mcp-block.py scripts/sync-codex-mcp-config.py scripts/lib/agent-mcp.sh tests/test_agent_mcp_runtime.py tests/test_codex_mcp_config.py tests/test_codex_mcp_helpers.py tests/test_codex_mcp_render_helpers.py
git commit -m "refactor(agent): render MCP configs through host adapters"
```

### Task 3: Semantic Audit and Documentation

**Files:**
- Modify: `scripts/agent_mcp_runtime.py`
- Modify: `scripts/agent-doctor.sh`
- Modify: `tests/test_agent_mcp_runtime.py`
- Modify: `tests/test_agent_doctor_config.py`
- Modify: `agent/README.md`
- Modify: `CONTEXT.md`
- Modify: `.gitignore`
- Modify: `.publicignore`

**Interfaces:**
- Consumes: normalized desired state and host adapters.
- Produces: `audit_config(host, config, desired) -> list[AuditIssue]` and CLI `audit` exit code 0/1.
- Produces: doctor checks semantic equality for managed servers instead of duplicating grep expectations.

- [ ] **Step 1: Write failing semantic-audit tests**

Cover missing server, wrong command, stale managed server, unrelated server preservation, duplicate Codex hook representation, missing local executable as a distinct issue, and OAuth-required remote server as configured-not-broken.

- [ ] **Step 2: Run tests to verify RED**

Run: `.venv/bin/python -m pytest tests/test_agent_mcp_runtime.py tests/test_agent_doctor_config.py -q`

Expected: FAIL on missing audit behavior.

- [ ] **Step 3: Implement semantic audit**

Parse JSON/TOML into normalized specs, compare only managed names, emit stable issue codes, and keep executable/readiness probes explicit. Detect both `hooks.json` and TOML hook definitions as `duplicate_hook_representation`.

- [ ] **Step 4: Delegate doctor to audit**

Replace Codex/JSON-agent string checks with CLI audit calls while retaining non-MCP doctor checks. Doctor output must name host and issue code without printing secrets.

- [ ] **Step 5: Align docs and remove obsolete residues**

Document desired-state ownership, host adapters, install/apply/audit flow, optional server semantics, and single-representation hooks. Remove obsolete graph-cache ignore entries and source cleanup references.

- [ ] **Step 6: Run focused GREEN**

Run: `.venv/bin/python -m pytest tests/test_agent_mcp_runtime.py tests/test_agent_doctor_config.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/agent_mcp_runtime.py scripts/agent-doctor.sh tests/test_agent_mcp_runtime.py tests/test_agent_doctor_config.py agent/README.md CONTEXT.md .gitignore .publicignore
git commit -m "feat(agent): audit managed MCP state semantically"
```

### Task 4: Full Verification and Review

**Files:**
- Modify only files required by review findings.

**Interfaces:**
- Consumes all previous tasks.
- Produces merge-ready child and parent branches with review evidence.

- [ ] **Step 1: Run full child checks**

Run: `make check`

Run: `make doctor-agent`

Expected: PASS. Worktree-only symlink checks may be verified again after local merge from the canonical checkout.

- [ ] **Step 2: Request independent code review**

Review `BASE_SHA..HEAD_SHA` against this plan. Fix every Critical and Important issue; rerun focused and full tests.

- [ ] **Step 3: Run neat-freak**

Audit README/CONTEXT/agent docs, rule links, CLAUDE/AGENTS same-source constraints, obsolete names, and document sizes. Make only current-fact edits.

- [ ] **Step 4: Commit review/doc corrections**

```bash
git add -u
git commit -m "docs(agent): align MCP runtime ownership"
```

- [ ] **Step 5: Prepare parent pointer**

Commit the child branch first, then stage only the `template` gitlink and required parent documentation. Do not include private runtime DB changes.
