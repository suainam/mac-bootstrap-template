# Agent Skills Directory Migration Implementation Plan

> Historical record only. This plan originally referenced the retired
> superpowers workflow; do not execute it. Current guidance is in
> `docs/skill-supply-chain.md`.

**Goal:** Move the Skill supply-chain authority and all managed Skill sources out of `agent/` into a dedicated `agent-skills/` subsystem without changing distribution scope or installed runtime behavior.

**Architecture:** `agent/` retains only agent runtime configuration. `agent-skills/registry/` owns source and target registries; `agent-skills/local/` groups first-party sources by maintenance domain; `agent-skills/local/shadows/` stores audited local shadows of external sources; ignored fetched content lives under `agent-skills/external/quarantine/`. Registry metadata, not directory names, remains authoritative for lineage, scope, projects, gate state, and target wiring.

**Tech Stack:** Python 3.13, JSONC, JSON Schema, Bash, GNU Make, pytest, Git submodule workflow.

## Global Constraints

- Work in the public `template/` child repository; do not modify parent `private/` files in this commit.
- Preserve unrelated dirty files, especially current summary-engine changes under `agent/data-hub/` and `tests/test_summary_*`.
- Produce one atomic public-child commit for this plan: `refactor: split agent skill supply chain`.
- Do not move `agent/data-hub/` in this plan.
- Keep `knowledge-lifecycle-manager` global and enabled.
- Keep the eight `knowledge-*` stage Skills project-scoped to `mac-bootstrap`; the manager may invoke them without globally distributing them.
- Keep `.agent-state/skills-lock.json`, `.agent-state/skill-sync-runs/`, and `.agent-state/skill-snapshots/` as ignored runtime state.
- Do not create compatibility symlinks at `agent/skills`, `agent/skills-sources.jsonc`, or `agent/skill-targets.jsonc`.
- External quarantine content stays ignored and non-authoritative.
- The two JSONC registries remain the only human-edited Skill supply-chain authority.
- Run real distribution only from the real checkout, never a DevSpace worktree.
- Prefix shell commands with `rtk` when the executor is operating under the repository RTK rules; shell builtins and compound `if` blocks remain shell syntax.

---

### Task 1: Add the version-2 registry path contract and recursive local-source validation

**Files:**
- Modify: `scripts/skill_supply_chain.py`
- Modify: `tests/test_skill_supply_chain.py`
- Later move/modify: `agent/schemas/skills-sources.schema.json` -> `agent-skills/registry/schemas/skills-sources.schema.json`
- Later move: `agent/schemas/skill-targets.schema.json` -> `agent-skills/registry/schemas/skill-targets.schema.json`

**Interfaces:**
- Consumes: existing `Registry.paths: dict[str, Path]`, `SkillRef.source_path`, and `SkillRef.local_shadow_path`.
- Produces: registry version `2`; path keys `local_root`, `quarantine_root`, `lockfile`, `run_log_root`, and `snapshot_root`; recursive `find_unmanaged_skill_dirs(registry, root)` behavior.

- [ ] **Step 1: Add failing tests for the new default registry locations and version**

Add to `tests/test_skill_supply_chain.py`:

```python
def test_default_registry_files_live_under_agent_skills_registry() -> None:
    assert DEFAULT_REGISTRY == ROOT / "agent-skills/registry/sources.jsonc"
    assert DEFAULT_TARGETS == ROOT / "agent-skills/registry/targets.jsonc"


def test_registry_version_two_exposes_source_and_state_roots() -> None:
    registry = load_registry(ROOT / "agent-skills/registry/sources.jsonc")

    assert registry.paths == {
        "local_root": Path("agent-skills/local"),
        "quarantine_root": Path("agent-skills/external/quarantine"),
        "lockfile": Path(".agent-state/skills-lock.json"),
        "run_log_root": Path(".agent-state/skill-sync-runs"),
        "snapshot_root": Path(".agent-state/skill-snapshots"),
    }
```

Import `DEFAULT_REGISTRY` and `DEFAULT_TARGETS` from `skill_supply_chain` in the test module’s existing import block.

- [ ] **Step 2: Replace the flat orphan-source fixture with a recursive fixture**

Replace `test_find_unmanaged_skill_dirs_reports_unregistered_internal_source` with:

```python
def test_find_unmanaged_skill_dirs_reports_nested_unregistered_source(tmp_path: Path) -> None:
    managed = tmp_path / "agent-skills/local/mac-bootstrap/managed"
    orphan = tmp_path / "agent-skills/local/playground/orphan"
    managed.mkdir(parents=True)
    orphan.mkdir(parents=True)
    managed.joinpath("SKILL.md").write_text(
        "---\nname: managed\ndescription: Managed\n---\n\n# Managed\n",
        encoding="utf-8",
    )
    orphan.joinpath("SKILL.md").write_text(
        "---\nname: orphan\ndescription: Orphan\n---\n\n# Orphan\n",
        encoding="utf-8",
    )
    registry_path = tmp_path / "sources.jsonc"
    registry_path.write_text(
        '''{
          "version": 2,
          "paths": {
            "local_root": "agent-skills/local",
            "quarantine_root": "agent-skills/external/quarantine",
            "lockfile": ".agent-state/skills-lock.json",
            "run_log_root": ".agent-state/skill-sync-runs",
            "snapshot_root": ".agent-state/skill-snapshots"
          },
          "defaults": {
            "internal": {
              "scope": "project",
              "audit": {"required": false},
              "gate": {"approved": true}
            }
          },
          "projects": {
            "mac-bootstrap": {
              "skills_dir": "${HOME}/work/config/mac-bootstrap/.agents/skills"
            }
          },
          "sources": {
            "local-mac-bootstrap": {
              "type": "internal",
              "path": "agent-skills/local/mac-bootstrap",
              "skills": {"managed": {"projects": ["mac-bootstrap"]}}
            }
          }
        }''',
        encoding="utf-8",
    )

    registry = load_registry(registry_path)

    assert find_unmanaged_skill_dirs(registry, tmp_path) == [orphan]
```

- [ ] **Step 3: Add a failing test that snapshots use registry state configuration**

Refactor the snapshot writer to expose this interface:

```python
def snapshot_output_path(registry: Registry, root: Path, label: str, now: str) -> Path:
    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-") or "snapshot"
    return root / registry.paths["snapshot_root"] / f"{now}-{safe_label}.json"
```

Add the test:

```python
def test_snapshot_output_path_uses_registry_snapshot_root(tmp_path: Path) -> None:
    registry = load_registry(ROOT / "agent-skills/registry/sources.jsonc")

    path = snapshot_output_path(registry, tmp_path, "before move", "2026-07-10T120000Z")

    assert path == tmp_path / ".agent-state/skill-snapshots/2026-07-10T120000Z-before-move.json"
```

- [ ] **Step 4: Run focused tests and verify they fail for the old contract**

Run:

```bash
template/.venv/bin/python -m pytest \
  template/tests/test_skill_supply_chain.py \
  -q
```

Expected: FAIL because defaults still point to `agent/`, registry version `2` is rejected, nested orphan scanning is unsupported, or `snapshot_output_path` is absent.

- [ ] **Step 5: Implement the version-2 paths**

In `scripts/skill_supply_chain.py`, replace the constants and `_path_map` contract with:

```python
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "agent-skills" / "registry" / "sources.jsonc"
DEFAULT_TARGETS = ROOT / "agent-skills" / "registry" / "targets.jsonc"


def _path_map(raw: dict) -> dict[str, Path]:
    defaults = {
        "local_root": "agent-skills/local",
        "quarantine_root": "agent-skills/external/quarantine",
        "lockfile": ".agent-state/skills-lock.json",
        "run_log_root": ".agent-state/skill-sync-runs",
        "snapshot_root": ".agent-state/skill-snapshots",
    }
    merged = {**defaults, **raw}
    unknown = sorted(set(merged) - set(defaults))
    if unknown:
        raise RegistryError(f"unsupported registry path keys: {', '.join(unknown)}")
    return {key: Path(value) for key, value in merged.items()}
```

Change the version guard to:

```python
if raw.get("version") != 2:
    raise RegistryError("sources.jsonc version must be 2")
```

- [ ] **Step 6: Implement recursive unmanaged-source detection**

Replace `find_unmanaged_skill_dirs` with:

```python
def find_unmanaged_skill_dirs(registry: Registry, root: Path = ROOT) -> list[Path]:
    managed = _managed_local_skill_source_paths(registry, root)
    local_root = root / registry.paths["local_root"]
    if not local_root.is_dir():
        return []
    candidates = {
        skill_md.parent.resolve()
        for skill_md in local_root.rglob("SKILL.md")
        if skill_md.is_file()
    }
    return sorted(path for path in candidates if path not in managed)
```

Do not exclude `shadows/` or `deprecated/`; every local `SKILL.md` must be represented by either an internal `source_path` or an external `local_shadow_path`.

- [ ] **Step 7: Route snapshot writes through `snapshot_root`**

Add `snapshot_output_path` and replace the hard-coded `.agent-state/skill-snapshots` construction in the snapshot command:

```python
now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
path = snapshot_output_path(registry, root, label, now)
path.parent.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 8: Run focused tests after the registry files have been moved in Task 2**

This test cannot pass until Task 2 creates the new registry files. Keep the failing tests as the migration guard and proceed directly to Task 2.

---

### Task 2: Move registry files and classify every managed Skill source

**Files:**
- Create: `agent-skills/README.md`
- Move: `agent/skills-sources.jsonc` -> `agent-skills/registry/sources.jsonc`
- Move: `agent/skill-targets.jsonc` -> `agent-skills/registry/targets.jsonc`
- Move: `agent/schemas/skills-sources.schema.json` -> `agent-skills/registry/schemas/skills-sources.schema.json`
- Move: `agent/schemas/skill-targets.schema.json` -> `agent-skills/registry/schemas/skill-targets.schema.json`
- Move: all tracked Skill source directories listed below.
- Modify: `.gitignore`

**Interfaces:**
- Consumes: version-2 parser from Task 1.
- Produces: complete `agent-skills/` source tree; no tracked `SKILL.md` under `agent/skills/`; registry source paths matching physical locations.

- [ ] **Step 1: Capture a pre-migration distribution snapshot**

Run from `template/` before moving registry files:

```bash
python3 scripts/skill_supply_chain.py snapshot --label pre-agent-skills-migration
python3 scripts/skill_supply_chain.py plan
```

Expected: snapshot written below `.agent-state/skill-snapshots/`; plan exits `0`.

- [ ] **Step 2: Create destination directories and move registry authority**

Run from `template/`:

```bash
mkdir -p agent-skills/registry/schemas
mkdir -p agent-skills/local/{global,mac-bootstrap,product-strategy,franchise-store,playground,www,deprecated}
mkdir -p agent-skills/local/shadows/{mattpocock,baoyu,guizang,langgpt,qiaomu}
mkdir -p agent-skills/external
git mv agent/skills-sources.jsonc agent-skills/registry/sources.jsonc
git mv agent/skill-targets.jsonc agent-skills/registry/targets.jsonc
git mv agent/schemas/skills-sources.schema.json agent-skills/registry/schemas/skills-sources.schema.json
git mv agent/schemas/skill-targets.schema.json agent-skills/registry/schemas/skill-targets.schema.json
```

- [ ] **Step 3: Move global, project, and disabled first-party Skills**

Run from `template/`:

```bash
git mv agent/skills/personal/knowledge-lifecycle-manager agent-skills/local/global/
git mv agent/skills/personal/cavecrew agent-skills/local/global/

git mv agent/skills/daily-tagger agent-skills/local/mac-bootstrap/
git mv agent/skills/personal/knowledge-candidate-review agent-skills/local/mac-bootstrap/
git mv agent/skills/personal/knowledge-claim-extraction agent-skills/local/mac-bootstrap/
git mv agent/skills/personal/knowledge-daily-weekly-synthesis agent-skills/local/mac-bootstrap/
git mv agent/skills/personal/knowledge-hygiene-audit agent-skills/local/mac-bootstrap/
git mv agent/skills/personal/knowledge-materialization agent-skills/local/mac-bootstrap/
git mv agent/skills/personal/knowledge-record agent-skills/local/mac-bootstrap/
git mv agent/skills/personal/knowledge-reuse-retrieval agent-skills/local/mac-bootstrap/
git mv agent/skills/personal/knowledge-source-ingestion agent-skills/local/mac-bootstrap/
git mv agent/skills/personal/mac-bootstrap-maintenance agent-skills/local/mac-bootstrap/
git mv agent/skills/personal/network-path-triage agent-skills/local/mac-bootstrap/

git mv agent/skills/personal/python-data-analysis agent-skills/local/product-strategy/
git mv agent/skills/personal/sql-analysis agent-skills/local/product-strategy/
git mv agent/skills/personal/decrypt-materialize agent-skills/local/product-strategy/
git mv agent/skills/personal/web-video-presentation-delivery agent-skills/local/product-strategy/

git mv agent/skills/personal/franchise-store-sankey-analysis agent-skills/local/franchise-store/
git mv agent/skills/personal/sankey-flow-analysis agent-skills/local/franchise-store/

git mv agent/skills/personal/daily-claude-battle-boost agent-skills/local/playground/
git mv agent/skills/personal/ottos-effect-analysis agent-skills/local/playground/
git mv agent/skills/personal/ottos-north-star-metric agent-skills/local/playground/
git mv agent/skills/personal/ottos-retail-ab-test agent-skills/local/playground/

git mv agent/skills/personal/marimo-analysis agent-skills/local/www/
git mv agent/skills/personal/marimo-dashboard-create agent-skills/local/www/
git mv agent/skills/personal/marimo-etl-test agent-skills/local/www/

git mv agent/skills/personal/caveman-commit agent-skills/local/deprecated/
git mv agent/skills/personal/caveman-compress agent-skills/local/deprecated/
git mv agent/skills/personal/caveman-help agent-skills/local/deprecated/
git mv agent/skills/personal/caveman-review agent-skills/local/deprecated/
git mv agent/skills/personal/caveman-stats agent-skills/local/deprecated/
git mv agent/skills/personal/docker-data-project agent-skills/local/deprecated/
git mv agent/skills/personal/eval-loop agent-skills/local/deprecated/
```

- [ ] **Step 4: Move external local shadows without changing their lineage**

Run from `template/`:

```bash
git mv agent/skills/personal/caveman agent-skills/local/shadows/mattpocock/
git mv agent/skills/personal/baoyu-diagram agent-skills/local/shadows/baoyu/
git mv agent/skills/personal/baoyu-infographic agent-skills/local/shadows/baoyu/
git mv agent/skills/personal/guizang-ppt-skill agent-skills/local/shadows/guizang/
git mv agent/skills/personal/langgpt-prompt-writer agent-skills/local/shadows/langgpt/
git mv agent/skills/personal/qiaomu-goal-meta-skill agent-skills/local/shadows/qiaomu/
```

- [ ] **Step 5: Update `sources.jsonc` to version 2 and explicit source groups**

Set:

```json
{
  "$schema": "./schemas/skills-sources.schema.json",
  "version": 2,
  "paths": {
    "local_root": "agent-skills/local",
    "quarantine_root": "agent-skills/external/quarantine",
    "lockfile": ".agent-state/skills-lock.json",
    "run_log_root": ".agent-state/skill-sync-runs",
    "snapshot_root": ".agent-state/skill-snapshots"
  }
}
```

Replace `local-personal` and `local-standalone` with these source records while preserving every existing per-Skill scope, project, agent, gate, audit, and distribution-state value:

```json
"local-global": {
  "type": "internal",
  "path": "agent-skills/local/global",
  "skills": {
    "knowledge-lifecycle-manager": {"scope": "global"},
    "cavecrew": {"scope": "global", "distribution_state": "staged"}
  }
},
"local-mac-bootstrap": {
  "type": "internal",
  "path": "agent-skills/local/mac-bootstrap",
  "skills": {}
},
"local-product-strategy": {
  "type": "internal",
  "path": "agent-skills/local/product-strategy",
  "skills": {}
},
"local-franchise-store": {
  "type": "internal",
  "path": "agent-skills/local/franchise-store",
  "skills": {}
},
"local-playground": {
  "type": "internal",
  "path": "agent-skills/local/playground",
  "skills": {}
},
"local-www": {
  "type": "internal",
  "path": "agent-skills/local/www",
  "skills": {}
},
"local-deprecated": {
  "type": "internal",
  "path": "agent-skills/local/deprecated",
  "skills": {}
}
```

Populate the empty `skills` objects by moving the existing records unchanged into their matching directory group. Update external shadow fields exactly:

```json
"local_shadow_path": "agent-skills/local/shadows/mattpocock/caveman"
```

Apply the same vendor-qualified shape for Baoyu, Guizang, LangGPT, and Qiaomu shadows.

- [ ] **Step 6: Strengthen the source-registry schema**

Change `agent-skills/registry/schemas/skills-sources.schema.json` to require version `2` and exact path keys:

```json
"version": {"const": 2},
"paths": {
  "type": "object",
  "required": [
    "local_root",
    "quarantine_root",
    "lockfile",
    "run_log_root",
    "snapshot_root"
  ],
  "additionalProperties": false,
  "properties": {
    "local_root": {"type": "string", "minLength": 1},
    "quarantine_root": {"type": "string", "minLength": 1},
    "lockfile": {"type": "string", "minLength": 1},
    "run_log_root": {"type": "string", "minLength": 1},
    "snapshot_root": {"type": "string", "minLength": 1}
  }
}
```

Keep target registry version `1`; its contract does not change.

- [ ] **Step 7: Move ignored quarantine state and update ignore rules**

If the ignored cache exists, preserve it locally:

```bash
mkdir -p agent-skills/external
if [ -d agent/skills/quarantine ]; then
  mv agent/skills/quarantine agent-skills/external/quarantine
fi
```

Replace `.gitignore` entry:

```gitignore
agent-skills/external/quarantine/
```

Do not add quarantine contents to Git.

- [ ] **Step 8: Write `agent-skills/README.md`**

Document these authority rules:

```markdown
# Agent Skills

`agent-skills/` owns Skill source lineage, local source code, external quarantine,
distribution policy, and target wiring. Agent runtime configuration remains under
`agent/`.

## Authority

- `registry/sources.jsonc`: lineage, scope, projects, state, audit, gate
- `registry/targets.jsonc`: installation targets and wiring strategy
- `local/`: tracked local sources and approved external shadows
- `external/quarantine/`: ignored fetched content; never authoritative
- `.agent-state/`: ignored locks, run logs, and snapshots

Directory placement improves navigation. Registry metadata remains authoritative
for distribution behavior.
```

- [ ] **Step 9: Run registry tests**

Run:

```bash
template/.venv/bin/python -m pytest template/tests/test_skill_supply_chain.py -q
```

Expected: PASS.

---

### Task 3: Update all runtime consumers, tests, and documentation

**Files:**
- Modify: `scripts/agent-doctor.sh`
- Modify: `scripts/skill-refresh.sh`
- Modify: `scripts/knowledge-record-gate.sh`
- Modify: `scripts/lib/skill-wiring.sh`
- Modify: `tests/test_skill_supply_chain.py`
- Modify: `tests/test_agent_skill_registry.py`
- Modify: `tests/test_knowledge_record_suggest.py`
- Modify: `agent/agent-manifest.json`
- Modify: `agent/manifest.yaml`
- Modify: `agent/README.md`
- Modify: `CONTEXT.md`
- Modify: `README.md`
- Modify: `docs/skill-supply-chain.md`
- Modify: `docs/data-hub-record-knowledge.md`
- Modify: tracked `agent/data-hub/` docs and adapters that reference moved Skill paths.

**Interfaces:**
- Consumes: new registry and source paths from Task 2.
- Produces: runtime wrappers and tests with zero dependency on `agent/skills*`; `agent/` documentation limited to runtime configuration.

- [ ] **Step 1: Update registry authority tests before wrappers**

In `tests/test_agent_skill_registry.py`, replace `load_sources` and authority assertions:

```python
def load_sources() -> dict:
    return json.loads(
        Path(TEMPLATE, "agent-skills", "registry", "sources.jsonc").read_text(
            encoding="utf-8"
        )
    )


def test_skill_sources_registry_is_authoritative() -> None:
    assert Path(TEMPLATE, "agent-skills/registry/sources.jsonc").is_file()
    assert Path(TEMPLATE, "agent-skills/registry/targets.jsonc").is_file()
    assert Path(TEMPLATE, "scripts/skill_supply_chain.py").is_file()
    assert not Path(TEMPLATE, "agent/skills-sources.jsonc").exists()
    assert not Path(TEMPLATE, "agent/skill-targets.jsonc").exists()
    assert not Path(TEMPLATE, "agent/skills").exists()
```

Update source IDs in assertions:

```python
sources["local-product-strategy"]
sources["local-mac-bootstrap"]
sources["local-franchise-store"]
sources["local-playground"]
sources["local-www"]
sources["local-global"]
```

Add explicit lifecycle assertions:

```python
def test_lifecycle_manager_is_global_but_stage_skills_are_project_scoped() -> None:
    sources = load_sources()["sources"]
    manager = sources["local-global"]["skills"]["knowledge-lifecycle-manager"]
    stages = sources["local-mac-bootstrap"]["skills"]

    assert manager["scope"] == "global"
    for name in (
        "knowledge-source-ingestion",
        "knowledge-claim-extraction",
        "knowledge-candidate-review",
        "knowledge-materialization",
        "knowledge-daily-weekly-synthesis",
        "knowledge-hygiene-audit",
        "knowledge-record",
        "knowledge-reuse-retrieval",
    ):
        assert stages[name]["scope"] == "project"
        assert stages[name]["projects"] == ["mac-bootstrap"]
```

- [ ] **Step 2: Run authority tests and verify wrapper failures**

Run:

```bash
template/.venv/bin/python -m pytest \
  template/tests/test_agent_skill_registry.py \
  template/tests/test_knowledge_record_suggest.py \
  -q
```

Expected: registry assertions pass after edits; knowledge-record imports or old wrapper paths still fail until Step 3.

- [ ] **Step 3: Update deterministic consumers**

Use these exact replacements:

```text
agent/skills-sources.jsonc
  -> agent-skills/registry/sources.jsonc

agent/skill-targets.jsonc
  -> agent-skills/registry/targets.jsonc

agent/skills/personal/knowledge-lifecycle-manager
  -> agent-skills/local/global/knowledge-lifecycle-manager

agent/skills/personal/knowledge-record
  -> agent-skills/local/mac-bootstrap/knowledge-record
```

Apply them in:

- `scripts/agent-doctor.sh`
- `scripts/skill-refresh.sh`
- `scripts/knowledge-record-gate.sh`
- `tests/test_knowledge_record_suggest.py`
- Data Hub docs and Skill adapters.

The command in `scripts/knowledge-record-gate.sh` must become:

```python
manager = "template/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py"
```

The `SCRIPTS_DIR` fixture in `tests/test_knowledge_record_suggest.py` must become:

```python
SCRIPTS_DIR = (
    Path(__file__).parent.parent
    / "agent-skills"
    / "local"
    / "mac-bootstrap"
    / "knowledge-record"
    / "scripts"
)
```

- [ ] **Step 4: Remove Skill source ownership from agent runtime manifests**

Delete `canonical.personal_skills_dir` from `agent/agent-manifest.json`.

Delete `upstreams` and `personal_skills` from `agent/manifest.yaml`. Retain prompt-library and agent runtime configuration only. Add a short pointer:

```yaml
# Skill source lineage and distribution authority:
# ../agent-skills/registry/sources.jsonc
# ../agent-skills/registry/targets.jsonc
```

Update `agent-skills/local/global/knowledge-lifecycle-manager/SKILL.md` so its description says it is the global reusable command center. Remove the stale `Project-scoped to mac-bootstrap data-hub` sentence. Keep backend-specific behavior documented as the current Data Hub adapter, not as the Skill's distribution scope.

- [ ] **Step 5: Update Skill wiring help text**

In `scripts/lib/skill-wiring.sh`, replace source-layout descriptions with installed-runtime descriptions only:

```text
Managed skills are installed into the configured agent targets and project
`.agents/skills/` directories. Source authority lives under
`template/agent-skills/registry/`.
```

Do not describe `~/.agent/skills/personal` as a source tree.

- [ ] **Step 6: Split documentation ownership**

Apply these rules:

- `agent/README.md`: agent binaries, rules, prompts, extensions, MCP, quality gates; one short link to `../agent-skills/README.md`.
- `agent-skills/README.md`: source model, directory taxonomy, commands, lifecycle-manager/global-stage distinction.
- `docs/skill-supply-chain.md`: full operations runbook with new registry/quarantine paths.
- `CONTEXT.md`: list `agent/` and `agent-skills/` as separate authorities.
- `README.md`: onboarding links to both subsystems.
- `docs/data-hub-record-knowledge.md`: manager and knowledge-record paths after the Skill move.

Update historical implementation reports only when they are active runbooks or contain executable commands. Leave immutable historical prose intact; add a migration note if an old path must remain for historical accuracy.

- [ ] **Step 7: Run zero-old-path checks**

Run from `template/`:

```bash
rg -n \
  'agent/skills-sources\.jsonc|agent/skill-targets\.jsonc|agent/skills/personal|agent/skills/quarantine' \
  --glob '!.git/**' \
  --glob '!.agent-state/**' \
  --glob '!docs/superpowers/plans/**' \
  .
```

Expected: no active code, test, config, or runbook matches. Historical design/implementation records may match only when explicitly marked pre-migration.

- [ ] **Step 8: Run focused validation**

Run:

```bash
python3 scripts/check-python-syntax.py scripts/skill_supply_chain.py
template/.venv/bin/python -m pytest \
  template/tests/test_skill_supply_chain.py \
  template/tests/test_agent_skill_registry.py \
  template/tests/test_knowledge_record_suggest.py \
  -q
make -C template skill-check
make -C template doctor-agent
```

Expected: all tests PASS; `skill-check` reports no unmanaged sources; doctor reports both registries present.

---

### Task 4: Prove distribution equivalence, refresh runtime links, and commit

**Files:**
- Runtime only: `.agent-state/skills-lock.json`
- Runtime only: `.agent-state/skill-sync-runs/`
- Runtime only: `.agent-state/skill-snapshots/`
- Runtime only: configured global and project Skill targets.

**Interfaces:**
- Consumes: completed source-tree and registry migration.
- Produces: installed targets resolving to `agent-skills/`; post-migration snapshot equal in membership/scope to the pre-migration snapshot.

- [ ] **Step 1: Generate and inspect the dry-run plan**

Run from `template/`:

```bash
python3 scripts/skill_supply_chain.py plan
python3 scripts/skill_supply_chain.py distribute --dry-run
make skill-reconcile
```

Expected:

- `knowledge-lifecycle-manager` targets global agent surfaces.
- Stage Skills target only the `mac-bootstrap` project surface.
- Product/project Skills retain their previous project targets.
- No target source contains `/agent/skills/`.
- Reconcile proposes only stale links/copies caused by the source move.

- [ ] **Step 2: Apply distribution and stale-link reconciliation**

Run only from the real checkout:

```bash
make skill-distribute
make skill-reconcile APPLY=1
make skill-distribute
```

Expected: enabled targets point to `template/agent-skills/...`; no broken old symlink remains.

- [ ] **Step 3: Capture and compare the post-migration view**

Run:

```bash
make skill-snapshot LABEL=post-agent-skills-migration
make skill-check
make doctor-agent
```

Compare the newest pre/post snapshots. Expected differences: local source IDs and source paths reflect the new taxonomy. Skill names, scope, projects, agents, state, and target membership remain unchanged.

- [ ] **Step 4: Run public-child release gates**

Run serially:

```bash
make -C template check
make -C template privacy-audit
```

Expected: PASS with no skipped tests and no private path leakage.

- [ ] **Step 5: Review the exact child-repository diff**

Run:

```bash
git -C template status --short
git -C template diff --check
git -C template diff --stat
git -C template diff -- agent agent-skills scripts tests docs CONTEXT.md README.md Makefile .gitignore
```

Expected: only Skill supply-chain migration files; current unrelated summary-engine edits remain unstaged.

- [ ] **Step 6: Commit the public-child migration**

Stage only the migration:

```bash
git -C template add -A -- \
  .gitignore \
  CONTEXT.md \
  README.md \
  agent/README.md \
  agent/agent-manifest.json \
  agent/manifest.yaml \
  agent/schemas \
  agent/skills \
  agent/skill-targets.jsonc \
  agent/skills-sources.jsonc \
  agent-skills \
  docs/skill-supply-chain.md \
  docs/data-hub-record-knowledge.md \
  scripts/agent-doctor.sh \
  scripts/knowledge-record-gate.sh \
  scripts/lib/skill-wiring.sh \
  scripts/skill-refresh.sh \
  scripts/skill_supply_chain.py \
  tests/test_agent_skill_registry.py \
  tests/test_knowledge_record_suggest.py \
  tests/test_skill_supply_chain.py

# Add only Data Hub runbooks whose Skill command paths changed; inspect each first.
git -C template add -- \
  agent/data-hub/README.md \
  agent/data-hub/docs/acceptance-report.md \
  agent/data-hub/docs/cron-setup.md \
  agent/data-hub/docs/ops.md \
  agent/data-hub/docs/troubleshooting.md
git -C template diff --cached --check
git -C template commit -m "refactor: split agent skill supply chain"
```

Before committing, inspect `git -C template diff --cached --name-only`; remove any unrelated dirty summary-engine file from the index.

Do not update the parent submodule pointer yet. Complete the Data Hub migration plan first, then push the child commits and make one parent pointer/private-runtime follow-up commit.
