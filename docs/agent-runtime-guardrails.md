# Agent Runtime Guardrails

Three guardrails keep agent work reproducible instead of machine-local: the
managed memory bridge, documentation content checks, and the subagent timeout
bound. Each one is versioned here, installed by `make`, and covered by tests.

## 1. Managed memory bridge

`scripts/ai-memory-mcp-bridge.py` is the only supported stdio entry point for
the shared memory primary. It wraps the official `mcp-bridge` subcommand and
fixes two things a raw invocation cannot:

- **Scope injection.** Project-scoped tools (`memory_query`, `memory_status`,
  `memory_write_page`, handoffs, messages, and the rest of the memory surface)
  declare both `workspace` and `project`. A session-less client sends neither,
  and the server then resolves the call into its `shared_slot` project, writing
  into the wrong namespace. The bridge derives the pair from the nearest
  `.ai-memory.toml` marker (explicit keys win) or, failing that, from the Git
  `origin` remote normalized to `<owner>-<repo>`, and injects them only when the
  caller left both empty.
- **Fail closed.** When neither a marker nor a Git remote resolves an identity,
  the bridge answers the call itself with MCP error `-32602` instead of
  forwarding it. An unidentified checkout can therefore never silently write to
  the shared slot.

Global and explicitly scoped calls pass through untouched, and every other
message (`initialize`, notifications, `tools/list`, responses) is forwarded
byte-for-byte over newline-delimited JSON-RPC.

Placement and credentials:

| Item | Location | Notes |
| --- | --- | --- |
| Bridge binary | `~/.local/bin/ai-memory-mcp-bridge` | symlink into `template/scripts/`, installed by `scripts/install-omp-config.sh` |
| Data directory | `~/.omp/agent/ai-memory-cc15/` | `0700`; holds `auth-token` at `0600` |
| Token | `auth-token` file | read at startup, exported as `AI_MEMORY_AUTH_TOKEN`; never passed in argv |

`install-omp-config.sh` refuses to clobber a foreign file: an existing symlink
to another target is replaced, an existing regular file is moved to
`<target>.pre-mac-bootstrap` first, and an already-present backup aborts the
install.

## 2. Documentation content checks

Documentation-only pushes used to skip every check. `scripts/check_docs.py`
now runs on them and rejects:

- relative Markdown links whose target does not exist;
- shell fences that `bash -n` cannot parse;
- credential-looking values passed as command-line arguments
  (`--token secret`, `--api-key=...`), while allowing placeholders such as
  `<YOUR_TOKEN>`, `{{TOKEN}}`, `$ENV_VAR`, and numeric values.

Angle-bracket and double-brace placeholders are replaced with a neutral token
before parsing, because `cmd <table>` is a shell syntax error even though it is
valid documentation. Real syntax errors in the same fence are still reported.

Entry points:

```bash
make docs-check        # changed docs vs DOCS_BASE (default HEAD)
make docs-check-all    # every doc in the repository
```

`repo-check` depends on `docs-check`, and `scripts/agent_check_scope_gate.py`
runs the checker for documentation-only pushes instead of returning early.

## 3. MCP command health

`scripts/run-doctor-checks.py` verifies that every enabled stdio server in the
configured MCP files has a resolvable `command`. A missing bridge binary is the
most common cause of a session that starts without memory tools, and it is
invisible until the first tool call.

The doctor manifest declares the configs to inspect:

```json
{ "mcp_configs": ["~/.omp/agent/mcp.json"] }
```

Non-stdio transports and disabled entries are skipped. An entry with no
`command`, or one that neither exists as an executable path nor resolves on
`PATH`, fails the check.

## 4. Subagent timeout bound

`agent/omp/extensions/subagent-timeout-bound.ts` closes the gap between a child
that hit its wall-clock cap and a parent that keeps waiting or respawns it:

- on a timed-out task result (sync result or async completion message), it
  emits a bounded `SUBAGENT CLOSED FOR EXPLORATION` snapshot built from the
  partial output, so the parent can harvest partial findings;
- on a later `task`/`resume` call naming the same agent id, it blocks the call
  and points at the snapshot instead of paying for the same dead exploration
  twice.

The extension is declared in `agent/omp/extensions.json` and linked by
`scripts/install-omp-extensions.sh`; `make omp-extensions` applies it.

## Verification

```bash
env -u PYTEST_ADDOPTS .venv/bin/python -m pytest \
  tests/test_ai_memory_mcp_bridge.py \
  tests/test_check_docs.py \
  tests/test_agent_check_scope_gate.py \
  tests/test_doctor_helpers.py \
  tests/test_omp_subagent_timeout_bound.py -q
make syntax-check
./scripts/privacy-audit.sh
```
