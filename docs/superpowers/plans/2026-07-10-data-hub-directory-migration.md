# Data Hub Directory Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the independent knowledge persistence subsystem from `agent/data-hub/` to top-level `data-hub/` while preserving workflow, SQLite, vault, scheduling, and lifecycle-manager behavior.

**Architecture:** `data-hub/` becomes the public implementation and runbook root. The global `knowledge-lifecycle-manager` remains under `agent-skills/local/global/` and invokes Data Hub through a stable top-level path; stage Skills remain project-scoped adapters under `agent-skills/local/mac-bootstrap/`. Parent-private runtime configuration remains the machine-specific authority and is updated only after the public child commit.

**Tech Stack:** Python 3.13, SQLite, Bash, launchd, JSONC, GNU Make, pytest, Git submodule workflow.

## Global Constraints

- Start only after `2026-07-10-agent-skills-directory-migration.md` is complete.
- Start only when all current dirty summary-engine files under `agent/data-hub/` and `tests/test_summary_*` are committed or otherwise safely resolved by their owner.
- Preserve all Data Hub implementation content with `git mv`; do not recreate files manually.
- Produce one atomic public-child commit for this plan: `refactor: promote data hub to top level`.
- Do not move lifecycle-manager or stage Skills into `data-hub/`.
- Do not add an `agent/data-hub` compatibility symlink.
- SQLite is canonical state; this migration must not rewrite the database or vault projections.
- Parent `private/agent/data_hub.runtime.jsonc` is modified only in the later private-parent follow-up commit.
- Existing LaunchAgent files are generated runtime state; update them by rerunning the installer, not by editing installed plists directly.
- Run full Data Hub tests in `template/.venv`.
- Prefix shell commands with `rtk` when the executor is operating under the repository RTK rules; shell builtins and compound command blocks remain shell syntax.

---

### Task 1: Lock the top-level location contract with failing tests

**Files:**
- Modify: `tests/test_data_hub.py`
- Modify: `tests/test_data_hub_helpers.py`
- Modify: `tests/test_lifecycle_manager_adapters.py`
- Modify: `tests/test_agent_skill_registry.py`
- Modify: `tests/test_knowledge_record_suggest.py`
- Modify: other tests listed by the path scan in Step 1.

**Interfaces:**
- Consumes: completed `agent-skills/` tree.
- Produces: tests that resolve implementation from `TEMPLATE / "data-hub"` and Skills from `TEMPLATE / "agent-skills" / ...`.

- [ ] **Step 1: Capture baseline status and enumerate active old-path tests**

Run:

```bash
git -C template status --short
git -C template grep -n -E 'agent/data-hub|template/agent/data-hub|agent/data_hub' -- \
  'tests/**' \
  'scripts/**' \
  'launchd/**' \
  'agent-skills/**' \
  'agent/**' \
  'README.md' \
  'CONTEXT.md' \
  'docs/**'
```

Expected: complete active consumer list. Stop if uncommitted Data Hub/summary work remains; do not move through an overlapping dirty tree.

- [ ] **Step 2: Introduce one test helper for the new subsystem root**

In `tests/helpers.py`, add without changing the existing string-valued `TEMPLATE` constant:

```python
DATA_HUB = Path(TEMPLATE) / "data-hub"
AGENT_SKILLS = Path(TEMPLATE) / "agent-skills"
```

Add `from pathlib import Path` to `tests/helpers.py`.

Update Data Hub tests to import `DATA_HUB` instead of reconstructing `Path(__file__).parent.parent / "agent" / "data-hub"`.

- [ ] **Step 3: Add a failing top-level structure test**

Add to `tests/test_data_hub.py`:

```python
from helpers import DATA_HUB, TEMPLATE


def test_data_hub_is_top_level_subsystem() -> None:
    assert DATA_HUB.is_dir()
    assert (DATA_HUB / "README.md").is_file()
    assert (DATA_HUB / "data_hub_config.py").is_file()
    assert (DATA_HUB / "scripts").is_dir()
    assert not (TEMPLATE / "agent/data-hub").exists()
```

- [ ] **Step 4: Add a failing template-root resolver test**

Add to the existing Data Hub config test module:

```python
def test_resolve_template_root_from_top_level_data_hub(tmp_path: Path) -> None:
    data_hub = tmp_path / "template/data-hub"
    data_hub.mkdir(parents=True)

    assert data_hub_config.resolve_template_root(data_hub) == tmp_path / "template"
```

- [ ] **Step 5: Update lifecycle adapter location assertions**

In `tests/test_lifecycle_manager_adapters.py`, use:

```python
from helpers import AGENT_SKILLS, DATA_HUB

MANAGER = AGENT_SKILLS / "local/global/knowledge-lifecycle-manager"
```

Replace every `Path(__file__).parent.parent / "agent" / "data-hub"` with `DATA_HUB`.

- [ ] **Step 6: Run the structural tests and verify failure**

Run:

```bash
template/.venv/bin/python -m pytest \
  template/tests/test_data_hub.py \
  template/tests/test_data_hub_helpers.py \
  template/tests/test_lifecycle_manager_adapters.py \
  -q
```

Expected: FAIL because `data-hub/` does not yet exist and the old directory still exists.

---

### Task 2: Move the subsystem and remove path assumptions from its runtime

**Files:**
- Move: `agent/data-hub/` -> `data-hub/`
- Modify after move: `data-hub/data_hub_config.py`
- Modify after move: `data-hub/data_hub.runtime.jsonc.example`
- Modify after move: `data-hub/daily_morning.sh`
- Modify after move: `data-hub/daily_reminder.sh`
- Modify after move: `data-hub/run-daily-evening.sh`
- Modify after move: `data-hub/AGENTS.md`

**Interfaces:**
- Consumes: top-level location tests from Task 1.
- Produces: `resolve_template_root(current_dir: Path) -> Path` for `template/data-hub`; shell adapters deriving `DATA_HUB_DIR`, `TEMPLATE_ROOT`, and parent `REPO_ROOT` from their own locations.

- [ ] **Step 1: Move the tracked directory intact**

Run from `template/`:

```bash
git mv agent/data-hub data-hub
```

Expected: Git reports renames; no file content is lost.

- [ ] **Step 2: Update Python template-root discovery**

In `data-hub/data_hub_config.py`, replace `resolve_template_root` with:

```python
def resolve_template_root(current_dir: Path) -> Path:
    for candidate in current_dir.parents:
        if (candidate / "data-hub").is_dir():
            return candidate
    raise RuntimeError(f"Unable to resolve template root from {current_dir}")
```

Keep:

```python
CURRENT_DIR = Path(__file__).resolve().parent
TEMPLATE_ROOT = resolve_template_root(CURRENT_DIR)
REPO_ROOT = resolve_repo_root(TEMPLATE_ROOT)
RUNTIME_CONFIG = REPO_ROOT / "private" / "agent" / "data_hub.runtime.jsonc"
```

Do not change private configuration ownership.

- [ ] **Step 3: Update the runtime example path**

In `data-hub/data_hub.runtime.jsonc.example`, set:

```json
"data_hub_dir": "$HOME/work/config/mac-bootstrap/template/data-hub"
```

Retain the instruction to copy private values into `private/agent/data_hub.runtime.jsonc`.

- [ ] **Step 4: Normalize shell location variables**

At the top of each root shell adapter, use:

```bash
DATA_HUB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_ROOT="$(cd "$DATA_HUB_DIR/.." && pwd)"
REPO_ROOT="$(cd "$TEMPLATE_ROOT/.." && pwd)"
PYTHON="${PYTHON:-$TEMPLATE_ROOT/.venv/bin/python}"
```

Replace Python path injection in `daily_morning.sh` and `daily_reminder.sh` with:

```bash
sys.path.insert(0, '${DATA_HUB_DIR}')
```

Replace executable paths with `$DATA_HUB_DIR/...`. Preserve scheduling and workday logic unchanged.

- [ ] **Step 5: Update local Data Hub rules**

In `data-hub/AGENTS.md`, replace the old boundary with:

```markdown
- Data Hub implementation and subsystem documentation live under `template/data-hub/`.
- Agent Skill source or routing changes belong under `template/agent-skills/`.
- Agent runtime configuration changes belong under `template/agent/`.
```

- [ ] **Step 6: Run structural and config tests**

Run:

```bash
template/.venv/bin/python -m pytest \
  template/tests/test_data_hub.py \
  template/tests/test_data_hub_helpers.py \
  template/tests/test_lifecycle_manager_adapters.py \
  -q
```

Expected: PASS.

---

### Task 3: Update lifecycle-manager and stage-Skill adapters

**Files:**
- Modify: `agent-skills/local/global/knowledge-lifecycle-manager/README.md`
- Modify: `agent-skills/local/global/knowledge-lifecycle-manager/run.sh`
- Modify: `agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py`
- Modify: `agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager_reporting.py`
- Modify: `agent-skills/local/global/knowledge-lifecycle-manager/scripts/record_knowledge.py`
- Modify: `agent-skills/local/mac-bootstrap/knowledge-*/SKILL.md`
- Modify: `agent-skills/local/mac-bootstrap/knowledge-*/scripts/*`
- Modify: `scripts/knowledge-record-gate.sh`
- Modify: lifecycle and knowledge-record tests.

**Interfaces:**
- Consumes: `TEMPLATE_ROOT / "data-hub"` as implementation root.
- Produces: global manager command surface unchanged; stage wrappers invoking top-level Data Hub scripts.

- [ ] **Step 1: Add one manager path helper**

In the manager implementation, define:

```python
TEMPLATE_ROOT = Path(__file__).resolve().parents[4]
DATA_HUB_DIR = TEMPLATE_ROOT / "data-hub"


def data_hub_script(name: str) -> Path:
    path = DATA_HUB_DIR / "scripts" / name
    if not path.is_file():
        raise FileNotFoundError(f"Data Hub script not found: {path}")
    return path
```

Replace constructed `agent/data-hub` paths with `data_hub_script(...)` or `DATA_HUB_DIR`.

- [ ] **Step 2: Add a manager path-contract test**

Add to `tests/test_lifecycle_manager_cli.py`:

```python
def test_manager_resolves_top_level_data_hub() -> None:
    assert manager.DATA_HUB_DIR == Path(TEMPLATE) / "data-hub"
    assert manager.data_hub_script("run_summary_schedule.py") == (
        Path(TEMPLATE) / "data-hub/scripts/run_summary_schedule.py"
    )
```

Import `Path` and the existing string-valued `TEMPLATE` constant in this test module.

- [ ] **Step 3: Update stage wrapper commands**

Every stage wrapper must invoke one of these paths:

```text
$TEMPLATE_ROOT/data-hub/scripts/ingest_logs.py
$TEMPLATE_ROOT/data-hub/scripts/ingest_sources.py
$TEMPLATE_ROOT/data-hub/scripts/generate_candidates.py
$TEMPLATE_ROOT/data-hub/scripts/claim_extraction.py
$TEMPLATE_ROOT/data-hub/scripts/knowledge_retrieval.py
$TEMPLATE_ROOT/data-hub/scripts/materialize_candidates.py
$TEMPLATE_ROOT/data-hub/scripts/hygiene_audit.py
```

For wrappers located at `agent-skills/local/mac-bootstrap/<skill>/scripts/`, calculate:

```bash
TEMPLATE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$TEMPLATE_ROOT/.venv/bin/python}"
```

Use `exec "$PYTHON_BIN" ... "$@"` for single-command wrappers.

- [ ] **Step 4: Update active Skill documentation**

Replace executable paths:

```text
template/agent/data-hub/ -> template/data-hub/
template/agent/skills/personal/knowledge-lifecycle-manager/
  -> template/agent-skills/local/global/knowledge-lifecycle-manager/
```

Do not change the registry scopes decided in the Skill migration plan.

- [ ] **Step 5: Run manager and stage tests**

Run:

```bash
template/.venv/bin/python -m pytest \
  template/tests/test_lifecycle_manager_cli.py \
  template/tests/test_lifecycle_manager_reporting.py \
  template/tests/test_lifecycle_manager_adapters.py \
  template/tests/test_knowledge_record_suggest.py \
  template/tests/test_agent_skill_registry.py \
  -q
```

Expected: PASS; manager remains global in registry; stages remain project-scoped.

---

### Task 4: Update launchd, public docs, and every active path consumer

**Files:**
- Modify: `launchd/install_obsidian_jobs.sh`
- Modify: `scripts/agent-doctor.sh`
- Modify: `README.md`
- Modify: `CONTEXT.md`
- Modify: `data-hub/README.md`
- Modify: `data-hub/CONTEXT.md`
- Modify: `data-hub/docs/README.md`
- Modify: `data-hub/docs/ops.md`
- Modify: `data-hub/docs/cron-setup.md`
- Modify: `data-hub/docs/troubleshooting.md`
- Modify: `docs/data-hub-record-knowledge.md`
- Modify: active tests and runbooks found by the zero-old-path scan.

**Interfaces:**
- Consumes: top-level Data Hub path and manager adapter contract.
- Produces: generated LaunchAgents executing `template/data-hub/*`; public documentation with `data-hub/` as authority.

- [ ] **Step 1: Update the launchd installer source root**

In `launchd/install_obsidian_jobs.sh`, set:

```bash
DATA_HUB_DIR="$MAC_BOOTSTRAP_DIR/template/data-hub"
```

Keep plist labels, times, logs, and load/unload behavior unchanged.

- [ ] **Step 2: Add or update launchd path assertions**

In `tests/test_lifecycle_manager_adapters.py`, assert:

```python
assert 'DATA_HUB_DIR="$MAC_BOOTSTRAP_DIR/template/data-hub"' in installer_text
assert "template/agent/data-hub" not in installer_text
```

- [ ] **Step 3: Update public authority docs**

Document:

```text
agent/        agent runtime configuration
agent-skills/ Skill supply chain and Skill sources
data-hub/     knowledge persistence subsystem
```

Update Data Hub run commands to `template/data-hub/...`. Keep historical ADR/spec statements intact when they describe past state; append a migration note instead of rewriting history.

- [ ] **Step 4: Run active zero-old-path scan**

Run from `template/`:

```bash
git grep -n -E 'template/agent/data-hub|agent/data-hub|agent/data_hub' -- \
  ':!docs/superpowers/plans/**' \
  ':!docs/superpowers/specs/**' \
  ':!docs/archive/**' \
  ':!data-hub/docs/archive/**'
```

Expected: no active code, config, test, Skill, README, ops, troubleshooting, or launchd match.

- [ ] **Step 5: Run documentation and adapter tests**

Run:

```bash
bash -n template/launchd/install_obsidian_jobs.sh
bash -n template/data-hub/daily_morning.sh
bash -n template/data-hub/daily_reminder.sh
bash -n template/data-hub/run-daily-evening.sh
template/.venv/bin/python -m pytest \
  template/tests/test_lifecycle_manager_adapters.py \
  template/tests/test_agent_skill_registry.py \
  -q
```

Expected: PASS.

---

### Task 5: Run Data Hub regression gates and commit the public-child migration

**Files:**
- Test-only/runtime outputs; no new source files expected.

**Interfaces:**
- Consumes: completed top-level migration.
- Produces: regression evidence that path changes did not alter canonical state, scheduling, workflow, summary, or projection behavior.

- [ ] **Step 1: Run the complete focused Data Hub suite**

Run:

```bash
template/.venv/bin/python -m pytest \
  template/tests/test_data_hub.py \
  template/tests/test_data_hub_helpers.py \
  template/tests/test_data_hub_sources.py \
  template/tests/test_daily_workflows.py \
  template/tests/test_lifecycle_manager_cli.py \
  template/tests/test_lifecycle_manager_reporting.py \
  template/tests/test_lifecycle_manager_adapters.py \
  template/tests/test_knowledge_record_suggest.py \
  template/tests/test_summary_contracts.py \
  template/tests/test_summary_store.py \
  template/tests/test_summary_publish_recovery.py \
  template/tests/test_summary_evidence.py \
  template/tests/test_summary_synthesis.py \
  template/tests/test_summary_renderer.py \
  template/tests/test_summary_inputs.py \
  template/tests/test_period_summary.py \
  template/tests/test_build_period_summary_cli.py \
  template/tests/test_summary_calendar.py \
  template/tests/test_summary_schedule.py \
  template/tests/test_workflow_abandoned.py \
  -q
```

Expected: PASS with no skips introduced by the migration.

- [ ] **Step 2: Run dry-run workflow smoke tests**

Run with the real private runtime config but without materializing output:

```bash
template/.venv/bin/python template/data-hub/scripts/run_summary_schedule.py \
  --date 2026-07-10 \
  --dry-run
template/.venv/bin/python \
  template/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py \
  health
```

Expected: scripts load from `template/data-hub`; health finds runtime config and canonical DB; no DB or vault writes from dry-run.

- [ ] **Step 3: Run public-child gates**

Run serially:

```bash
make -C template skill-check
make -C template doctor-agent
make -C template check
make -C template privacy-audit
```

Expected: PASS.

- [ ] **Step 4: Verify no canonical-state mutation**

Before and after smoke tests, record:

```bash
stat -f '%m %z %N' private/agent/data/agent_history.db
git status --short
```

Expected: database modification time and size unchanged by dry-run; no new vault or DB artifacts enter Git status.

- [ ] **Step 5: Review and commit only the public migration**

Run:

```bash
git -C template status --short
git -C template diff --check
git -C template diff --stat
git -C template add -A -- \
  agent \
  data-hub \
  agent-skills \
  launchd/install_obsidian_jobs.sh \
  scripts/agent-doctor.sh \
  tests \
  README.md \
  CONTEXT.md \
  docs/data-hub-record-knowledge.md
git -C template diff --cached --check
git -C template commit -m "refactor: promote data hub to top level"
```

Expected: second public-child migration commit; no private parent files staged.

---

### Task 6: Update real runtime configuration and parent submodule pointer

**Files:**
- Modify in private parent: `private/agent/data_hub.runtime.jsonc`
- Modify in private parent: `README.md`
- Modify in private parent: `CONTEXT.md`
- Update in private parent: `template` submodule pointer.
- Generated runtime: installed LaunchAgent plists.

**Interfaces:**
- Consumes: both public-child commits pushed from the real `template/` checkout.
- Produces: parent runtime pointing to `template/data-hub`; parent pointer referencing both migration commits; reinstalled schedules using new executable paths.

- [ ] **Step 1: Push the public child after final review**

Run:

```bash
git -C template log -2 --oneline
git -C template push
```

Expected: remote contains:

```text
refactor: split agent skill supply chain
refactor: promote data hub to top level
```

- [ ] **Step 2: Update private runtime path**

In parent `private/agent/data_hub.runtime.jsonc`, change only:

```json
"data_hub_dir": "$HOME/work/config/mac-bootstrap/template/data-hub"
```

Do not copy private values into public template files.

- [ ] **Step 3: Update parent documentation pointers**

Replace active parent onboarding links:

```text
template/agent/data-hub/ -> template/data-hub/
```

In parent `CONTEXT.md`, keep `private/agent/data_hub.runtime.jsonc` as runtime authority and point implementation/runbooks to `template/data-hub/`.

- [ ] **Step 4: Reinstall generated LaunchAgents**

Run:

```bash
bash template/launchd/install_obsidian_jobs.sh
```

Verify generated plists:

```bash
rg -n 'template/(agent/)?data-hub' "$HOME/Library/LaunchAgents"/*obsidian-*.plist
```

Expected: every program path contains `template/data-hub`; zero `template/agent/data-hub` matches.

- [ ] **Step 5: Verify real runtime health**

Run:

```bash
template/.venv/bin/python \
  template/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py \
  health
make doctor-agent
make check
make privacy-audit
make doctor
```

Expected: all gates PASS; manager reads real private config and existing SQLite state from the new implementation path.

- [ ] **Step 6: Commit the private parent follow-up**

Stage only parent docs, runtime config, and submodule pointer:

```bash
git add template private/agent/data_hub.runtime.jsonc README.md CONTEXT.md
git diff --cached --check
git diff --cached --submodule=short
git commit -m "chore: activate split agent subsystems"
```

Expected: no public implementation duplicated into parent; no runtime DB, logs, vault files, or unrelated private changes staged.
