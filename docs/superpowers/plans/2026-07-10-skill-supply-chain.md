# Skill Supply Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a governed skill supply-chain system that uses one JSONC registry to fetch external skills into repo-local quarantine, validate/audit/diff them, apply approval gates, and distribute approved internal/external skills to agent-global or project-local skill views.

**Architecture:** `agent/skills-sources.jsonc` becomes the only human-edited skill governance entry for sources, scope, gates, and distribution intent. `agent/skill-targets.jsonc` becomes the skill-specific target registry for agent skill directories and output formats, so future agent path changes do not require Python or shell edits. A new Python distributor reads both JSONC files, stages external skills under `agent/skills/quarantine/<source>/<skill>/`, evaluates local validation and audit gates, and then writes symlinks/copies directly to configured agent-global and project-local skill directories. The previous skill governance files are retired by this change; do not generate replacement versions of them.

**Tech Stack:** Python 3.12 standard library, in-repo JSONC parser, pytest, existing Makefile, new `agent/skill-targets.jsonc` skill target registry, `npx skills` / skills.sh CLI for external source fetch, optional skills.sh audit API, existing shell wrappers only as thin entrypoints.

## Global Constraints

- Public reusable logic belongs in this template repo; no private usernames, tokens, subscriptions, internal hosts, or machine-only paths in committed template files.
- `agent/skills-sources.jsonc` is the human-edited source/scope/gate registry; `agent/skill-targets.jsonc` is the human-edited agent skill target registry.
- Do not add a mode that recreates the previous `skills-manifest.json`, `skills-distribution.json`, or `skills-promote.txt` workflow.
- External skills must never be installed straight into `~/.codex/skills`, `~/.claude/skills`, `~/.config/opencode/skills`, `~/.pi/agent/skills`, `~/.reasonix/skills`, `~/.gemini/antigravity-cli/skills`, or `~/.agents/skills` during fetch.
- External fetch target is always repo-local: `agent/skills/quarantine/<source>/<skill>/`.
- External skills default to `scope: global`; internal skills default to `scope: project`.
- User approval for an external skill must bind to the resolved version or current content hash. Approval does not carry to changed content.
- Existing canonical agent names remain: `claude`, `codex`, `opencode`, `pi`, `reasonix`, `antigravity`, `cross-agent`.
- Reasonix still needs flat `.md` output; directory-format agents use `<skill>/SKILL.md`.
- `agent/skills/quarantine/`, `.agent-state/skills-lock.json`, and `.agent-state/skill-sync-runs/` are generated runtime artifacts and must be ignored by Git.
- Keep skill target paths and output formats in `agent/skill-targets.jsonc`; do not hardcode agent skill directories in Python or shell.
- Make every mutating command support `--dry-run` before writing outside quarantine.

---

## File Structure

### Create

- `agent/skills-sources.jsonc`
  - Human registry for internal/external sources, examples, defaults, gates, scope, agent targets, project targets, and reference-only upstreams.
- `agent/skill-targets.jsonc`
  - Human registry for canonical agent skill target directories, target formats, link/copy strategy, and shared cross-agent skill locations.
- `agent/schemas/skills-sources.schema.json`
  - JSON schema for the source registry after comment stripping.
- `agent/schemas/skill-targets.schema.json`
  - JSON schema for skill target paths and target formats.
- `scripts/skill_supply_chain.py`
  - Python CLI for `plan`, `fetch`, `audit`, `diff`, `distribute`, and `check`.
- `tests/test_skill_supply_chain.py`
  - Unit tests for JSONC parsing, registry normalization, skills.sh fetch command planning, local validation, gate decisions, distribution actions, and generated artifact checks.
- `docs/skill-supply-chain.md`
  - Human runbook for editing the registry, fetching external skills, approval, distribution, rollback, and verification.

### Modify

- `Makefile`
  - Replace old skill-management targets with `skill-plan`, `skill-fetch`, `skill-audit`, `skill-diff`, `skill-distribute`, `skill-refresh`, and `skill-check` backed by `scripts/skill_supply_chain.py`.
  - Add `scripts/skill_supply_chain.py` to Python syntax checks.
- `scripts/install-agent-tooling.sh`
  - Replace the skill-wiring step with a call to the new distributor in dry-run-safe form, or call a thin function that delegates to `scripts/skill_supply_chain.py distribute`.
- `scripts/lib/agent-configure.sh`
  - Remove direct upstream/personal skill tree wiring from `wire_upstream_skills_step`; delegate to the new registry-driven distributor.
- `scripts/agent-doctor.sh`
  - Add a `Skill Supply Chain` section: registry present, quarantine ignored, latest run log present, gate status summary, and distribution check status.
- `tests/test_agent_skill_registry.py`
  - Replace assertions against retired skill files with assertions against `agent/skills-sources.jsonc`, `agent/skill-targets.jsonc`, and the new checker.
- `.gitignore`
  - Ignore `agent/skills/quarantine/`, `.agent-state/skills-lock.json`, and `.agent-state/skill-sync-runs/`.
- `CONTEXT.md`, `agent/README.md`, `docs/README.md`
  - Update authority and runbook pointers to the new registry and supply-chain docs.

### Stop using

- `agent/skills-manifest.json`
- `agent/skills-distribution.json`
- `agent/skills-promote.txt`
- `scripts/skill_scope_manifest.py`
- `scripts/check-skill-scope.py`
- `scripts/skill-route.sh`
- `scripts/skill-scope-refresh.sh`
- `scripts/sync-agent-upstreams.sh` for skill fetching only; prompt syncing remains separate.

---

## Sample Registry Contract

The first committed `agent/skills-sources.jsonc` must include two external examples and two internal examples.

```jsonc
{
  "$schema": "./schemas/skills-sources.schema.json",
  "version": 1,

  "paths": {
    "internal_root": "agent/skills/personal",
    "standalone_internal_root": "agent/skills",
    "quarantine_root": "agent/skills/quarantine",
    "lockfile": ".agent-state/skills-lock.json",
    "run_log_root": ".agent-state/skill-sync-runs"
  },

  "defaults": {
    "external": {
      "scope": "global",
      "agents": ["claude", "codex", "opencode", "pi", "reasonix", "antigravity", "cross-agent"],
      "audit": {
        "required": true,
        "allow_unaudited": false,
        "max_risk": "LOW",
        "allow_scripts": false
      },
      "gate": {
        "manual_approval": true,
        "approved": false
      }
    },
    "internal": {
      "scope": "project",
      "audit": {
        "required": false,
        "local_validate": true
      },
      "gate": {
        "manual_approval": false,
        "approved": true
      }
    }
  },

  "reference_sources": {
    "agentskills-standard": {
      "type": "external",
      "ref": "agentskills/agentskills",
      "purpose": "format and validator reference only; not distributed"
    }
  },

  "projects": {
    "mac-bootstrap": {
      "skills_dir": "${HOME}/work/config/mac-bootstrap/.agents/skills"
    },
    "product_strategy": {
      "skills_dir": "${HOME}/work/projects/product_strategy/.agents/skills"
    }
  },

  "sources": {
    "vercel-agent-skills": {
      "type": "external",
      "fetcher": "skills.sh",
      "ref": "vercel-labs/agent-skills",
      "skills": {
        "web-design-guidelines": {
          "agents": ["codex", "opencode"],
          "gate": {
            "manual_approval": true,
            "approved": false,
            "reason": "example external skill; approve only after quarantine audit"
          }
        }
      }
    },

    "anthropic-skills": {
      "type": "external",
      "fetcher": "skills.sh",
      "ref": "anthropics/skills",
      "skills": {
        "pdf": {
          "agents": ["claude", "codex"],
          "gate": {
            "manual_approval": true,
            "approved": false,
            "reason": "example external document skill; approve only after quarantine audit"
          }
        }
      }
    },

    "local-personal": {
      "type": "internal",
      "path": "agent/skills/personal",
      "skills": {
        "knowledge-lifecycle-manager": {
          "scope": "global",
          "agents": ["claude", "codex", "opencode", "pi", "reasonix", "antigravity", "cross-agent"],
          "reason": "沉淀与复用入口，应该全局可用"
        },
        "python-data-analysis": {
          "scope": "project",
          "projects": ["mac-bootstrap"],
          "reason": "内部项目分发测试样例"
        }
      }
    },

    "local-standalone": {
      "type": "internal",
      "path": "agent/skills",
      "skills": {
        "daily-tagger": {
          "scope": "project",
          "projects": ["mac-bootstrap"]
        }
      }
    }
  }
}
```

---

## Sample Skill Targets Contract

The first committed `agent/skill-targets.jsonc` must be derived from the current production distribution path, not invented. Current production behavior is implemented in `agent/agent-manifest.json`, `scripts/skill-refresh.sh`, and `scripts/lib/skill-wiring.sh`:

| Target | Production path | Production format | Production strategy | Evidence |
|---|---|---|---|---|
| `claude` | `~/.claude/skills` | directory | symlink | `agent/agent-manifest.json` `agents.claude.paths.skills`; `link_skill_target "$src_dir" "$CLAUDE_SKILLS_DIR/${skill_name}"` |
| `codex` | `~/.codex/skills` | directory | symlink | `agent/agent-manifest.json` `agents.codex.paths.skills`; `link_skill_target "$src_dir" "$CODEX_SKILLS_DIR/${skill_name}"` |
| `opencode` | `~/.config/opencode/skills` | directory | symlink | `agent/agent-manifest.json` `agents.opencode.paths.skills`; `link_skill_target "$src_dir" "$OPENCODE_SKILLS_DIR/${skill_name}"` |
| `pi` | `~/.pi/agent/skills` | directory | symlink | `agent/agent-manifest.json` `agents.pi.paths.skills`; `link_skill_target "$src_dir" "$PI_SKILLS_DIR/${skill_name}"` |
| `antigravity` | `~/.gemini/antigravity-cli/skills` | directory | symlink | `agent/agent-manifest.json` `agents.antigravity.paths.skills`; `link_skill_target "$src_dir" "$ANTIGRAVITY_SKILLS_DIR/${skill_name}"` |
| `cross-agent` | `~/.agents/skills` | directory | symlink | `agent/agent-manifest.json` `shared.cross_agent_skills_dir`; `link_skill_target "$src_dir" "$CROSS_AGENT_SKILLS_DIR/${skill_name}"` |
| `reasonix` | `~/.reasonix/skills` | flat-md | copy | `agent/agent-manifest.json` `agents.reasonix.paths.skills`; `cp -L "$src_dir/SKILL.md" "$REASONIX_SKILLS_DIR/${skill_name}.md"` |

This table is the required migration baseline. If implementation discovers a different production value, pause and update the plan before changing code.

```jsonc
{
  "$schema": "./schemas/skill-targets.schema.json",
  "version": 1,

  "targets": {
    "claude": {
      "path": "~/.claude/skills",
      "format": "directory",
      "strategy": "symlink"
    },
    "codex": {
      "path": "~/.codex/skills",
      "format": "directory",
      "strategy": "symlink"
    },
    "opencode": {
      "path": "~/.config/opencode/skills",
      "format": "directory",
      "strategy": "symlink"
    },
    "pi": {
      "path": "~/.pi/agent/skills",
      "format": "directory",
      "strategy": "symlink"
    },
    "antigravity": {
      "path": "~/.gemini/antigravity-cli/skills",
      "format": "directory",
      "strategy": "symlink"
    },
    "cross-agent": {
      "path": "~/.agents/skills",
      "format": "directory",
      "strategy": "symlink"
    },
    "reasonix": {
      "path": "~/.reasonix/skills",
      "format": "flat-md",
      "strategy": "copy"
    }
  }
}
```

Validation rules:

- Every target key must be one of the canonical agent names.
- `format: "directory"` means target path is `<base>/<skill>/SKILL.md`.
- `format: "flat-md"` means target path is `<base>/<skill>.md`.
- `strategy: "symlink"` is allowed only for directory targets.
- `strategy: "copy"` is required for flat-md targets.
- Python distribution code must read this file; hardcoded skill target paths are a test failure.

---

## Core Interfaces

```python
@dataclass(frozen=True)
class SkillRef:
    source_id: str
    name: str
    source_type: Literal["internal", "external"]
    fetcher: str | None
    ref: str | None
    source_path: Path | None
    quarantine_path: Path | None
    scope: Literal["global", "project"]
    agents: tuple[str, ...]
    projects: tuple[str, ...]
    gate: GatePolicy
    audit: AuditPolicy
```

```python
@dataclass(frozen=True)
class SkillTarget:
    agent: str
    path: Path
    format: Literal["directory", "flat-md"]
    strategy: Literal["symlink", "copy"]
```

```python
@dataclass(frozen=True)
class DistributionAction:
    skill_name: str
    source: Path
    target_agent: str | None
    target_path: Path
    action: Literal["link-dir", "copy-flat-md"]
```

```bash
python scripts/skill_supply_chain.py plan
python scripts/skill_supply_chain.py fetch --source vercel-agent-skills --skill web-design-guidelines
python scripts/skill_supply_chain.py audit --source vercel-agent-skills --skill web-design-guidelines
python scripts/skill_supply_chain.py diff --source vercel-agent-skills --skill web-design-guidelines
python scripts/skill_supply_chain.py distribute --dry-run
python scripts/skill_supply_chain.py check
```

---

### Task 1: Registry and parser

**Files:**
- Create: `agent/skills-sources.jsonc`
- Create: `agent/skill-targets.jsonc`
- Create: `agent/schemas/skills-sources.schema.json`
- Create: `agent/schemas/skill-targets.schema.json`
- Create: `scripts/skill_supply_chain.py`
- Create: `tests/test_skill_supply_chain.py`

**Interfaces:**
- Produces: `strip_jsonc_comments(text: str) -> str`, `load_registry(path: Path) -> Registry`, `load_targets(path: Path) -> dict[str, SkillTarget]`, normalized `SkillRef` and `SkillTarget` records.
- Consumes: the sample registry contract and sample skill targets contract above.

- [ ] **Step 1: Write failing parser/default tests**

Add `tests/test_skill_supply_chain.py`:

```python
from pathlib import Path

from scripts.skill_supply_chain import load_registry, load_targets, strip_jsonc_comments


def test_strip_jsonc_comments_preserves_urls_and_strings():
    raw = '''{
      // comment
      "url": "https://github.com/vercel-labs/agent-skills",
      "text": "keep // inside string"
    }'''

    stripped = strip_jsonc_comments(raw)

    assert "comment" not in stripped
    assert "https://github.com/vercel-labs/agent-skills" in stripped
    assert "keep // inside string" in stripped


def test_registry_contains_external_and_internal_examples(tmp_path: Path):
    registry_path = tmp_path / "skills-sources.jsonc"
    registry_path.write_text(REGISTRY_SAMPLE, encoding="utf-8")

    registry = load_registry(registry_path)

    vercel = registry.skills[("vercel-agent-skills", "web-design-guidelines")]
    assert vercel.source_type == "external"
    assert vercel.ref == "vercel-labs/agent-skills"
    assert vercel.quarantine_path == Path("agent/skills/quarantine/vercel-agent-skills/web-design-guidelines")
    assert vercel.scope == "global"
    assert vercel.agents == ("codex", "opencode")

    anthropic = registry.skills[("anthropic-skills", "pdf")]
    assert anthropic.source_type == "external"
    assert anthropic.ref == "anthropics/skills"
    assert anthropic.agents == ("claude", "codex")

    knowledge = registry.skills[("local-personal", "knowledge-lifecycle-manager")]
    assert knowledge.source_type == "internal"
    assert knowledge.scope == "global"
    assert knowledge.agents == ("claude", "codex", "opencode", "pi", "reasonix", "antigravity", "cross-agent")
    assert knowledge.source_path == Path("agent/skills/personal/knowledge-lifecycle-manager")

    python_skill = registry.skills[("local-personal", "python-data-analysis")]
    assert python_skill.scope == "project"
    assert python_skill.projects == ("mac-bootstrap",)


def test_skill_targets_match_current_production_distribution(tmp_path: Path):
    targets_path = tmp_path / "skill-targets.jsonc"
    targets_path.write_text(TARGETS_SAMPLE, encoding="utf-8")

    targets = load_targets(targets_path)

    expected = {
        "claude": (Path("~/.claude/skills"), "directory", "symlink"),
        "codex": (Path("~/.codex/skills"), "directory", "symlink"),
        "opencode": (Path("~/.config/opencode/skills"), "directory", "symlink"),
        "pi": (Path("~/.pi/agent/skills"), "directory", "symlink"),
        "antigravity": (Path("~/.gemini/antigravity-cli/skills"), "directory", "symlink"),
        "cross-agent": (Path("~/.agents/skills"), "directory", "symlink"),
        "reasonix": (Path("~/.reasonix/skills"), "flat-md", "copy"),
    }
    assert set(targets) == set(expected)
    for name, (path, fmt, strategy) in expected.items():
        assert targets[name].path == path
        assert targets[name].format == fmt
        assert targets[name].strategy == strategy
```

- [ ] **Step 1b: Add a production baseline guard test**

Add a test that reads the real `agent/agent-manifest.json` and proves `TARGETS_SAMPLE` matches today's production paths. This prevents future agents from silently changing target paths in the new JSONC file without noticing production drift:

```python
import json


def test_skill_targets_sample_matches_agent_manifest_paths():
    manifest = json.loads((Path(__file__).resolve().parents[1] / "agent/agent-manifest.json").read_text(encoding="utf-8"))
    targets = load_targets(Path(__file__).resolve().parents[1] / "agent/skill-targets.jsonc")

    assert targets["claude"].path.as_posix() == manifest["agents"]["claude"]["paths"]["skills"]
    assert targets["codex"].path.as_posix() == manifest["agents"]["codex"]["paths"]["skills"]
    assert targets["opencode"].path.as_posix() == manifest["agents"]["opencode"]["paths"]["skills"]
    assert targets["pi"].path.as_posix() == manifest["agents"]["pi"]["paths"]["skills"]
    assert targets["antigravity"].path.as_posix() == manifest["agents"]["antigravity"]["paths"]["skills"]
    assert targets["reasonix"].path.as_posix() == manifest["agents"]["reasonix"]["paths"]["skills"]
    assert targets["cross-agent"].path.as_posix() == manifest["shared"]["cross_agent_skills_dir"]
    assert targets["reasonix"].format == "flat-md"
    assert targets["reasonix"].strategy == "copy"
    for name in {"claude", "codex", "opencode", "pi", "antigravity", "cross-agent"}:
        assert targets[name].format == "directory"
        assert targets[name].strategy == "symlink"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_supply_chain.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'scripts.skill_supply_chain'
```

- [ ] **Step 3: Implement minimal parser/model**

Create `scripts/skill_supply_chain.py` with dataclasses, JSONC comment stripping, registry load, target load, source default merging, target format validation, agent validation, and path normalization.

- [ ] **Step 4: Add sample registries and schemas**

Create `agent/skills-sources.jsonc` using the sample registry contract above.

Create `agent/skill-targets.jsonc` using the sample skill targets contract above.

Create `agent/schemas/skills-sources.schema.json` with required keys:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["version", "paths", "defaults", "sources"],
  "properties": {
    "version": {"const": 1},
    "paths": {"type": "object"},
    "defaults": {"type": "object"},
    "reference_sources": {"type": "object"},
    "projects": {"type": "object"},
    "sources": {"type": "object"}
  },
  "additionalProperties": false
}
```

Create `agent/schemas/skill-targets.schema.json` with required keys:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["version", "targets"],
  "properties": {
    "version": {"const": 1},
    "targets": {"type": "object"}
  },
  "additionalProperties": false
}
```

- [ ] **Step 5: Verify and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_supply_chain.py -q
.venv/bin/python scripts/skill_supply_chain.py plan
```

Expected:

```text
3 passed
skills=5 external=2 internal=3 targets=7
```

Commit:

```bash
git add agent/skills-sources.jsonc agent/skill-targets.jsonc agent/schemas/skills-sources.schema.json agent/schemas/skill-targets.schema.json scripts/skill_supply_chain.py tests/test_skill_supply_chain.py
git commit -m "feat: add skill supply registry"
```

---

### Task 2: Local validation and unmanaged skill detection

**Files:**
- Modify: `scripts/skill_supply_chain.py`
- Modify: `tests/test_skill_supply_chain.py`

**Interfaces:**
- Produces: `validate_skill_dir(path: Path, expected_name: str) -> list[str]`, `find_unmanaged_skill_dirs(registry: Registry, root: Path) -> list[Path]`.
- Consumes: normalized internal source paths and quarantine root.

- [ ] **Step 1: Write failing validation tests**

Add tests:

```python
from scripts.skill_supply_chain import find_unmanaged_skill_dirs, validate_skill_dir


def test_validate_skill_dir_requires_matching_name(tmp_path: Path):
    skill_dir = tmp_path / "agent/skills/personal/example-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: other-skill\ndescription: Bad\n---\n\n# Bad\n",
        encoding="utf-8",
    )

    errors = validate_skill_dir(skill_dir, "example-skill")

    assert "frontmatter name mismatch: expected example-skill got other-skill" in errors


def test_unmanaged_skill_detection_catches_standalone_skill(tmp_path: Path):
    registry_path = tmp_path / "agent/skills-sources.jsonc"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(REGISTRY_WITHOUT_DAILY_TAGGER, encoding="utf-8")
    daily = tmp_path / "agent/skills/daily-tagger"
    daily.mkdir(parents=True)
    (daily / "SKILL.md").write_text(
        "---\nname: daily-tagger\ndescription: Daily\n---\n\n# Daily\n",
        encoding="utf-8",
    )

    registry = load_registry(registry_path)
    unmanaged = find_unmanaged_skill_dirs(registry, root=tmp_path)

    assert daily in unmanaged
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_supply_chain.py::test_validate_skill_dir_requires_matching_name tests/test_skill_supply_chain.py::test_unmanaged_skill_detection_catches_standalone_skill -q
```

Expected:

```text
ImportError: cannot import name 'validate_skill_dir'
```

- [ ] **Step 3: Implement validation**

Parse the first YAML frontmatter block with standard-library string parsing. Required fields: `name`, `description`. Fail when directory name differs from `name`.

- [ ] **Step 4: Implement unmanaged detection**

Walk `agent/skills/**/SKILL.md`. Ignore paths under `agent/skills/quarantine`. Treat all configured internal source dirs as managed.

- [ ] **Step 5: Verify and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_supply_chain.py -q
.venv/bin/python scripts/skill_supply_chain.py check
```

Expected:

```text
ok skill supply check
```

Commit:

```bash
git add scripts/skill_supply_chain.py tests/test_skill_supply_chain.py
git commit -m "feat: validate skill registry entries"
```

---

### Task 3: External fetch into repo-local quarantine

**Files:**
- Modify: `scripts/skill_supply_chain.py`
- Modify: `tests/test_skill_supply_chain.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `build_skills_sh_fetch_command(skill: SkillRef) -> list[str]`, `fetch_external_skill(skill: SkillRef, root: Path, dry_run: bool) -> CommandResult`.
- Consumes: external `SkillRef` records.

- [ ] **Step 1: Write failing fetch command tests**

Add tests:

```python
from scripts.skill_supply_chain import build_skills_sh_fetch_command


def test_skills_sh_command_uses_specific_skill_and_universal_agent(tmp_path: Path):
    registry_path = tmp_path / "skills-sources.jsonc"
    registry_path.write_text(REGISTRY_SAMPLE, encoding="utf-8")
    skill = load_registry(registry_path).skills[("vercel-agent-skills", "web-design-guidelines")]

    cmd = build_skills_sh_fetch_command(skill)

    assert cmd == [
        "npx",
        "skills",
        "add",
        "vercel-labs/agent-skills",
        "--skill",
        "web-design-guidelines",
        "--agent",
        "universal",
        "--copy",
        "--yes",
    ]


def test_anthropic_pdf_command_uses_same_quarantine_fetch_shape(tmp_path: Path):
    registry_path = tmp_path / "skills-sources.jsonc"
    registry_path.write_text(REGISTRY_SAMPLE, encoding="utf-8")
    skill = load_registry(registry_path).skills[("anthropic-skills", "pdf")]

    cmd = build_skills_sh_fetch_command(skill)

    assert cmd[3] == "anthropics/skills"
    assert cmd[5] == "pdf"
    assert "--agent" in cmd
    assert "universal" in cmd
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_supply_chain.py::test_skills_sh_command_uses_specific_skill_and_universal_agent tests/test_skill_supply_chain.py::test_anthropic_pdf_command_uses_same_quarantine_fetch_shape -q
```

Expected:

```text
ImportError: cannot import name 'build_skills_sh_fetch_command'
```

- [ ] **Step 3: Implement command builder**

Rules:

```text
DISABLE_TELEMETRY=1 in environment
npx skills add <ref> --skill <skill> --agent universal --copy --yes
working directory: agent/skills/quarantine/.tmp/<source>/<skill>/work
move result: .agents/skills/<skill> -> agent/skills/quarantine/<source>/<skill>
```

- [ ] **Step 4: Add `.gitignore` entries**

Add:

```gitignore
# Generated skill supply-chain artifacts
agent/skills/quarantine/
.agent-state/skills-lock.json
.agent-state/skill-sync-runs/
```

- [ ] **Step 5: Verify dry-run output and commit**

Run:

```bash
.venv/bin/python scripts/skill_supply_chain.py fetch --source vercel-agent-skills --skill web-design-guidelines --dry-run
.venv/bin/python scripts/skill_supply_chain.py fetch --source anthropic-skills --skill pdf --dry-run
```

Expected:

```text
DRY-RUN fetch external skill vercel-agent-skills/web-design-guidelines -> agent/skills/quarantine/vercel-agent-skills/web-design-guidelines
DRY-RUN fetch external skill anthropic-skills/pdf -> agent/skills/quarantine/anthropic-skills/pdf
```

Commit:

```bash
git add scripts/skill_supply_chain.py tests/test_skill_supply_chain.py .gitignore
git commit -m "feat: fetch external skills into quarantine"
```

---

### Task 4: Audit, diff, gate, and logs

**Files:**
- Modify: `scripts/skill_supply_chain.py`
- Modify: `tests/test_skill_supply_chain.py`

**Interfaces:**
- Produces: `inspect_skill_content(path: Path) -> SkillInspection`, `evaluate_gate(skill: SkillRef, inspection: SkillInspection, audit: AuditResult | None) -> GateDecision`, `write_run_log(event: dict) -> Path`.
- Consumes: quarantined external skill dirs and internal source dirs.

- [ ] **Step 1: Write failing gate tests**

Add tests:

```python
from scripts.skill_supply_chain import evaluate_gate, inspect_skill_content


def test_gate_blocks_external_skill_with_scripts_when_scripts_not_allowed(tmp_path: Path):
    skill_dir = tmp_path / "agent/skills/quarantine/external/scripted"
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: scripted\ndescription: Has scripts\n---\n\n# Scripted\n",
        encoding="utf-8",
    )
    (skill_dir / "scripts/run.sh").write_text("echo hi\n", encoding="utf-8")
    skill = load_registry(write_registry_for_external(tmp_path, "scripted")).skills[("external", "scripted")]

    decision = evaluate_gate(skill, inspect_skill_content(skill_dir), audit=None)

    assert decision.allowed is False
    assert "scripts present but audit.allow_scripts is false" in decision.reasons


def test_gate_requires_approval_hash_to_match_current_content(tmp_path: Path):
    skill_dir = tmp_path / "agent/skills/quarantine/external/safe"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: safe\ndescription: Safe\n---\n\n# Safe\n",
        encoding="utf-8",
    )
    current_hash = inspect_skill_content(skill_dir).content_hash
    skill = load_registry(write_registry_for_external(tmp_path, "safe", approved_hash="old")) .skills[("external", "safe")]

    decision = evaluate_gate(skill, inspect_skill_content(skill_dir), audit=None)

    assert current_hash != "old"
    assert decision.allowed is False
    assert decision.approved_version_matches is False
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_supply_chain.py::test_gate_blocks_external_skill_with_scripts_when_scripts_not_allowed tests/test_skill_supply_chain.py::test_gate_requires_approval_hash_to_match_current_content -q
```

Expected:

```text
ImportError: cannot import name 'evaluate_gate'
```

- [ ] **Step 3: Implement content inspection**

Hash all non-ignored files under the skill directory, ordered by relative path. Record: `content_hash`, `has_scripts`, `file_count`, `skill_md_exists`.

- [ ] **Step 4: Implement audit result model**

Represent audit as local JSON:

```json
{
  "status": "pass",
  "risk_level": "LOW",
  "source": "skills.sh",
  "raw": {}
}
```

When audit API returns no result and `allow_unaudited` is false, block distribution.

- [ ] **Step 5: Implement run logs**

Write one JSONL record per event to `.agent-state/skill-sync-runs/YYYY-MM-DDTHHMMSSZ.jsonl`. Include `event`, `source`, `skill`, `result`, `reasons`, and `content_hash`. Never log environment variables or tokens.

- [ ] **Step 6: Verify and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_supply_chain.py -q
.venv/bin/python scripts/skill_supply_chain.py audit --source vercel-agent-skills --skill web-design-guidelines --dry-run
.venv/bin/python scripts/skill_supply_chain.py diff --source vercel-agent-skills --skill web-design-guidelines --dry-run
```

Expected:

```text
DRY-RUN audit external skill vercel-agent-skills/web-design-guidelines
DRY-RUN diff external skill vercel-agent-skills/web-design-guidelines
```

Commit:

```bash
git add scripts/skill_supply_chain.py tests/test_skill_supply_chain.py
git commit -m "feat: gate external skill promotion"
```

---

### Task 5: Direct distribution from registry

**Files:**
- Modify: `scripts/skill_supply_chain.py`
- Modify: `tests/test_skill_supply_chain.py`

**Interfaces:**
- Produces: `build_distribution_actions(registry: Registry, targets: dict[str, SkillTarget], root: Path) -> list[DistributionAction]`, `apply_distribution_actions(actions: list[DistributionAction], dry_run: bool) -> None`.
- Consumes: approved external quarantine dirs, internal source dirs, `agent/skill-targets.jsonc`, and project `skills_dir` registry entries.

- [ ] **Step 1: Write failing distribution tests**

Add tests:

```python
from scripts.skill_supply_chain import build_distribution_actions, load_targets


def test_global_internal_skill_distributes_to_configured_agents(tmp_path: Path):
    registry = load_registry(write_sample_registry(tmp_path))
    targets = load_targets(write_sample_targets(tmp_path))
    skill_dir = tmp_path / "agent/skills/personal/knowledge-lifecycle-manager"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: knowledge-lifecycle-manager\ndescription: Knowledge lifecycle\n---\n\n# Knowledge\n",
        encoding="utf-8",
    )

    actions = build_distribution_actions(registry, targets=targets, root=tmp_path)

    codex_actions = [a for a in actions if a.skill_name == "knowledge-lifecycle-manager" and a.target_agent == "codex"]
    assert codex_actions
    assert codex_actions[0].action == "link-dir"


def test_project_internal_skill_distributes_only_to_project_view(tmp_path: Path):
    registry = load_registry(write_sample_registry(tmp_path))
    targets = load_targets(write_sample_targets(tmp_path))
    skill_dir = tmp_path / "agent/skills/personal/python-data-analysis"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: python-data-analysis\ndescription: Python data analysis\n---\n\n# Python\n",
        encoding="utf-8",
    )

    actions = build_distribution_actions(registry, targets=targets, root=tmp_path)

    project_actions = [a for a in actions if a.skill_name == "python-data-analysis"]
    assert len(project_actions) == 1
    assert project_actions[0].target_agent is None
    assert ".agents/skills/python-data-analysis" in project_actions[0].target_path.as_posix()


def test_reasonix_distribution_uses_flat_md(tmp_path: Path):
    registry = load_registry(write_registry_with_reasonix_global_skill(tmp_path))
    targets = load_targets(write_sample_targets(tmp_path))
    skill_dir = tmp_path / "agent/skills/personal/example"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: example\ndescription: Example\n---\n\n# Example\n",
        encoding="utf-8",
    )

    actions = build_distribution_actions(registry, targets=targets, root=tmp_path)

    reasonix = [a for a in actions if a.target_agent == "reasonix"][0]
    assert reasonix.action == "copy-flat-md"
    assert reasonix.target_path.name == "example.md"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_supply_chain.py::test_global_internal_skill_distributes_to_configured_agents tests/test_skill_supply_chain.py::test_project_internal_skill_distributes_only_to_project_view tests/test_skill_supply_chain.py::test_reasonix_distribution_uses_flat_md -q
```

Expected:

```text
ImportError: cannot import name 'build_distribution_actions'
```

- [ ] **Step 3: Implement target resolution**

Read agent paths and formats from `agent/skill-targets.jsonc`. Resolve:

```text
format=directory + strategy=symlink -> <target.path>/<skill>
format=flat-md   + strategy=copy    -> <target.path>/<skill>.md
project                             -> projects.<name>.skills_dir/<skill>
```

Do not read agent skill paths from `agent/agent-manifest.json` inside distribution code. That file may remain useful for other agent configuration, but skill target locations are now owned by `agent/skill-targets.jsonc`.

- [ ] **Step 4: Implement apply behavior**

For `link-dir`: remove existing symlink, preserve real dirs by moving to `.bak` if no backup exists, then symlink source dir.

For `copy-flat-md`: copy `SKILL.md` to `<skill>.md`.

- [ ] **Step 5: Verify dry-run and commit**

Run:

```bash
.venv/bin/python scripts/skill_supply_chain.py distribute --dry-run
.venv/bin/python -m pytest tests/test_skill_supply_chain.py -q
```

Expected:

```text
DRY-RUN distribution actions
```

Commit:

```bash
git add scripts/skill_supply_chain.py tests/test_skill_supply_chain.py
git commit -m "feat: distribute skills from registry"
```

---

### Task 6: Replace old skill management surfaces

**Files:**
- Modify: `Makefile`
- Modify: `scripts/install-agent-tooling.sh`
- Modify: `scripts/lib/agent-configure.sh`
- Modify: `scripts/agent-doctor.sh`
- Modify: `tests/test_agent_skill_registry.py`
- Delete: `agent/skills-manifest.json`
- Delete: `agent/skills-distribution.json`
- Delete: `agent/skills-promote.txt`
- Delete: `scripts/skill_scope_manifest.py`
- Delete: `scripts/check-skill-scope.py`
- Delete: `scripts/skill-route.sh`
- Delete: `scripts/skill-scope-refresh.sh`
- Delete: `scripts/sync-agent-upstreams.sh`

**Interfaces:**
- Consumes: registry-driven distributor from prior tasks.
- Produces: Makefile and installer paths that only invoke the new supply-chain script for skills.

- [ ] **Step 1: Write failing registry authority tests**

Replace `tests/test_agent_skill_registry.py` content with tests that assert the new source exists and retired files do not exist:

```python
import os

from helpers import TEMPLATE


def test_skill_sources_registry_is_authoritative():
    assert os.path.exists(os.path.join(TEMPLATE, "agent", "skills-sources.jsonc"))
    assert os.path.exists(os.path.join(TEMPLATE, "agent", "skill-targets.jsonc"))


def test_previous_skill_governance_files_are_removed():
    for rel in [
        "agent/skills-manifest.json",
        "agent/skills-distribution.json",
        "agent/skills-promote.txt",
        "scripts/skill_scope_manifest.py",
        "scripts/check-skill-scope.py",
        "scripts/skill-route.sh",
        "scripts/skill-scope-refresh.sh",
        "scripts/sync-agent-upstreams.sh",
    ]:
        assert not os.path.exists(os.path.join(TEMPLATE, rel)), rel
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_agent_skill_registry.py -q
```

Expected: failure because retired files still exist.

- [ ] **Step 3: Update Makefile targets**

Replace the skill target block with:

```makefile
skill-plan:
	$(PYTHON) scripts/skill_supply_chain.py plan

skill-fetch:
	$(PYTHON) scripts/skill_supply_chain.py fetch $(if $(SOURCE),--source $(SOURCE),) $(if $(SKILL),--skill $(SKILL),)

skill-audit:
	$(PYTHON) scripts/skill_supply_chain.py audit $(if $(SOURCE),--source $(SOURCE),) $(if $(SKILL),--skill $(SKILL),)

skill-diff:
	$(PYTHON) scripts/skill_supply_chain.py diff $(if $(SOURCE),--source $(SOURCE),) $(if $(SKILL),--skill $(SKILL),)

skill-distribute:
	$(PYTHON) scripts/skill_supply_chain.py distribute

skill-refresh: skill-fetch skill-audit skill-distribute

skill-check:
	$(PYTHON) scripts/skill_supply_chain.py check
```

Add to `check`:

```makefile
	$(PYTHON) scripts/check-python-syntax.py scripts/skill_supply_chain.py
	$(PYTHON) scripts/skill_supply_chain.py check
```

- [ ] **Step 4: Update installer skill step**

In `scripts/install-agent-tooling.sh`, replace `wire_upstream_skills_step` call with:

```bash
print_step_header "Step 2b — Wire managed skills into agents"
run "$BOOTSTRAP/scripts/skill_supply_chain.py" distribute
```

If executing Python directly is brittle, use:

```bash
run python3 "$BOOTSTRAP/scripts/skill_supply_chain.py" distribute
```

- [ ] **Step 5: Simplify `wire_upstream_skills_step`**

In `scripts/lib/agent-configure.sh`, replace the body with:

```bash
wire_upstream_skills_step() {
  run python3 "$BOOTSTRAP/scripts/skill_supply_chain.py" distribute
}
```

- [ ] **Step 6: Delete retired files**

Run:

```bash
git rm agent/skills-manifest.json agent/skills-distribution.json agent/skills-promote.txt \
  scripts/skill_scope_manifest.py scripts/check-skill-scope.py scripts/skill-route.sh \
  scripts/skill-scope-refresh.sh scripts/sync-agent-upstreams.sh
```

- [ ] **Step 7: Verify and commit**

Run:

```bash
bash -n scripts/install-agent-tooling.sh
bash -n scripts/lib/agent-configure.sh
.venv/bin/python -m pytest tests/test_agent_skill_registry.py tests/test_skill_supply_chain.py -q
make skill-plan
make skill-check
```

Expected:

```text
skill registry authoritative
ok skill supply check
```

Commit:

```bash
git add Makefile scripts/install-agent-tooling.sh scripts/lib/agent-configure.sh scripts/agent-doctor.sh tests/test_agent_skill_registry.py
git commit -m "refactor: replace skill manifests with supply registry"
```

---

### Task 7: Doctor and documentation

**Files:**
- Modify: `scripts/agent-doctor.sh`
- Modify: `CONTEXT.md`
- Modify: `agent/README.md`
- Modify: `docs/README.md`
- Create: `docs/skill-supply-chain.md`

**Interfaces:**
- Consumes: `scripts/skill_supply_chain.py check`.
- Produces: user-facing runbook and health output.

- [ ] **Step 1: Add doctor health section**

In `scripts/agent-doctor.sh`, add after agent skills checks:

```bash
echo ""
echo "--- Skill Supply Chain ---"
if [ -f "$BOOTSTRAP/agent/skills-sources.jsonc" ]; then
  echo "  OK   skills-sources.jsonc"
else
  echo "  MISS skills-sources.jsonc"
fi
if [ -f "$BOOTSTRAP/agent/skill-targets.jsonc" ]; then
  echo "  OK   skill-targets.jsonc"
else
  echo "  MISS skill-targets.jsonc"
fi
if python3 "$BOOTSTRAP/scripts/skill_supply_chain.py" check >/tmp/mac-bootstrap-skill-check.out 2>/tmp/mac-bootstrap-skill-check.err; then
  echo "  OK   skill supply check"
else
  echo "  WARN skill supply check failed"
  sed 's/^/       /' /tmp/mac-bootstrap-skill-check.err
fi
if git -C "$BOOTSTRAP" check-ignore -q agent/skills/quarantine 2>/dev/null; then
  echo "  OK   quarantine ignored"
else
  echo "  WARN quarantine is not ignored"
fi
```

- [ ] **Step 2: Create runbook**

Create `docs/skill-supply-chain.md` with these sections:

```markdown
# Skill Supply Chain

## Authority

`agent/skills-sources.jsonc` owns source/scope/gate policy. `agent/skill-targets.jsonc` owns agent skill target paths and formats. Both are human-edited JSONC governance files.

## External flow

external source -> `agent/skills/quarantine/<source>/<skill>/` -> audit -> diff -> gate -> distribute

## Internal flow

internal source dir -> local validation -> gate -> distribute

## Example sources

- External global sample: `vercel-labs/agent-skills` / `web-design-guidelines`
- External global sample: `anthropics/skills` / `pdf`
- Internal global sample: `agent/skills/personal/knowledge-lifecycle-manager`
- Internal project sample: `agent/skills/personal/python-data-analysis` -> `mac-bootstrap`

## Commands

```bash
make skill-plan
make skill-fetch SOURCE=vercel-agent-skills SKILL=web-design-guidelines
make skill-audit SOURCE=vercel-agent-skills SKILL=web-design-guidelines
make skill-diff SOURCE=vercel-agent-skills SKILL=web-design-guidelines
make skill-distribute
make skill-check
make doctor-agent
```
```

- [ ] **Step 3: Update authority docs**

In `CONTEXT.md`, replace the skill row with:

```markdown
| Agent skill governance | `agent/skills-sources.jsonc`, `agent/skill-targets.jsonc` | quarantine, generated links and user-level agent skill dirs | `make skill-refresh`; `make skill-check`; `make doctor-agent` |
```

In `agent/README.md`, replace the old upstream skill section with a short pointer to `docs/skill-supply-chain.md`.

In `docs/README.md`, add:

```markdown
- `skill-supply-chain.md`：agent skill 来源、隔离审查、门禁和分发 runbook。
```

- [ ] **Step 4: Verify and commit**

Run:

```bash
bash -n scripts/agent-doctor.sh
make doctor-agent
```

Expected:

```text
--- Skill Supply Chain ---
  OK   skills-sources.jsonc
```

Commit:

```bash
git add scripts/agent-doctor.sh CONTEXT.md agent/README.md docs/README.md docs/skill-supply-chain.md
git commit -m "docs: document skill supply chain"
```

---

### Task 8: Final verification and cleanup

**Files:**
- Modify only files required by failed verification.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified direct-rebuild skill governance system.

- [ ] **Step 1: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_supply_chain.py tests/test_agent_skill_registry.py -q
```

Expected:

```text
all tests pass
```

- [ ] **Step 2: Run syntax and shell checks**

Run:

```bash
.venv/bin/python scripts/check-python-syntax.py scripts/skill_supply_chain.py
bash -n scripts/install-agent-tooling.sh
bash -n scripts/lib/agent-configure.sh
bash -n scripts/agent-doctor.sh
```

Expected:

```text
ok scripts/skill_supply_chain.py
```

- [ ] **Step 3: Run skill commands**

Run:

```bash
make skill-plan
make skill-check
make skill-fetch SOURCE=vercel-agent-skills SKILL=web-design-guidelines --dry-run
make skill-fetch SOURCE=anthropic-skills SKILL=pdf --dry-run
```

If Make does not pass `--dry-run` cleanly, run the Python commands directly:

```bash
.venv/bin/python scripts/skill_supply_chain.py fetch --source vercel-agent-skills --skill web-design-guidelines --dry-run
.venv/bin/python scripts/skill_supply_chain.py fetch --source anthropic-skills --skill pdf --dry-run
```

Expected:

```text
DRY-RUN fetch external skill vercel-agent-skills/web-design-guidelines
DRY-RUN fetch external skill anthropic-skills/pdf
```

- [ ] **Step 4: Run full check if affordable**

Run:

```bash
make check
```

Expected: existing suite passes. If unrelated environment checks fail, record exact failures and run the focused checks above as completion evidence.

- [ ] **Step 5: Commit verification fixes**

If any fixes were needed:

```bash
git add <changed-files>
git commit -m "test: verify skill supply chain"
```

---

## Self-Review

- Spec coverage: JSONC registry, external/internal sources, repo-local quarantine, audit/diff/gate, user approval, global/project/agent distribution, doctor/check/logging, and direct rebuild are all assigned to tasks.
- External examples are fixed: `vercel-labs/agent-skills:web-design-guidelines` and `anthropics/skills:pdf`.
- Internal examples are fixed with corrected scope: `knowledge-lifecycle-manager` is global because it is a reusable knowledge sedimentation entry; `python-data-analysis` is project-scoped to `mac-bootstrap` as the internal distribution test sample. `daily-tagger` is included to force unmanaged/standalone handling.
- Agent skill target paths are data-driven through `agent/skill-targets.jsonc`; Python and shell must not hardcode skill directories.
- The plan does not create old manifest outputs or a bridge back to previous skill governance files.
- Type names are consistent: `SkillRef`, `SkillTarget`, `Registry`, `AuditPolicy`, `GatePolicy`, `DistributionAction`, `GateDecision`.
- Mutating operations have dry-run coverage before apply.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-10-skill-supply-chain.md`.

Recommended execution mode: **Subagent-Driven**. Dispatch one fresh subagent per task, review the diff and tests between tasks, and do not let later tasks start until the previous task's verification commands pass.
