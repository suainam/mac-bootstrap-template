# Skill Distribution Confirmation

> Historical record only; this confirmation is not an active distribution instruction. Use `docs/skill-supply-chain.md`.

> This is the confirmation view after user review of `2026-07-10-skill-distribution-audit.md`. Use the `Mark` column as the user's current intent, but resolve the open project-routing questions before changing `skills-sources.jsonc` broadly.

## Latest registry change already applied

Added external skills.sh source:

```jsonc
"vercel-skills": {
  "type": "external",
  "fetcher": "skills.sh",
  "ref": "https://github.com/vercel-labs/skills",
  "skills": {
    "find-skills": {
      "agents": ["claude", "codex", "opencode", "cross-agent"],
      "gate": {
        "manual_approval": true,
        "approved": false,
        "reason": "user requested: npx skills add https://github.com/vercel-labs/skills --skill find-skills; approve after quarantine audit"
      }
    }
  }
}
```

Verification:

```text
uv run pytest tests/test_skill_supply_chain.py -q -> 14 passed
python3 scripts/skill_supply_chain.py check -> skills=42 external=3 internal=39 global=17 project=25 targets=7
python3 scripts/skill_supply_chain.py fetch --source vercel-skills --skill find-skills --dry-run
  -> DRY-RUN fetch external skill vercel-skills/find-skills -> agent/skills/quarantine/vercel-skills/find-skills
```

## 1. Confirmed global / routed core

These can stay broadly available, unless later noise proves they over-trigger.

| Decision | Skills | Notes |
|---|---|---|
| KEEP-GLOBAL | `using-git-worktrees`, `writing-plans`, `executing-plans` | Core plan/worktree workflow. |
| KEEP-GLOBAL | `knowledge-lifecycle-manager` | User corrected: reusable knowledge sedimentation entry, global. |
| KEEP-GLOBAL | `caveman`, `caveman-help`, `neat-freak` | High-frequency workflow helpers. |
| KEEP-ROUTED | `finishing-a-development-branch`, `requesting-code-review`, `diagnosing-bugs`, `improve-codebase-architecture` | Coding-agent oriented; route to Claude/Codex/OpenCode, maybe Cross-agent. |
| KEEP-ROUTED | `langgpt-prompt-writer`, `qiaomu-goal-meta-skill`, `humanizer-zh` | Useful, but not necessarily Pi/Reasonix/Antigravity. |
| KEEP-ROUTED | `search-first`, `documentation-lookup`, `python-testing`, `docker-patterns`, `data-throughput-accelerator` | Practical coding/data support. |
| KEEP-ROUTED | `web-design-engineer`, `beautiful-article`, `kb-retriever`, `defuddle`, `obsidian-cli`, `obsidian-markdown` | Keep if content/knowledge workflows remain common; see conflicts below because user marks include some `[project]`/`[drop]`. |
| KEEP-ROUTED | `find-skills` | Newly requested. Keep gated until quarantine audit passes. |

## 2. Stage / source-only candidates

Keep the upstream source available, but do not distribute by default.

| Decision | Skills | Notes |
|---|---|---|
| STAGE | `postgres-patterns`, `database-migrations`, `data-scraper-agent` | Useful but situational. |
| STAGE | `pytorch-patterns`, `mle-workflow`, `clickhouse-io` | User marked drop; safer implementation is source-only/staged first unless you want physical removal. |
| STAGE | `grill-with-docs`, `handoff`, `writing-great-skills` | Useful during repo/skill work, but not everyday global defaults. |
| STAGE | `gpt-image-2` | Host image generation exists; keep as source/reference unless local image workflow is active. |
| STAGE | `obsidian-bases`, `json-canvas` | Niche Obsidian features. |
| STAGE | `write-a-skill`, `zoom-out`, `codebase-memory`, `decrypt-read` | Runtime-only/unmanaged; inspect source before formal management. |
| STAGE | `cavecrew`, `caveman-compress`, `caveman-stats` | Support varies by host or has overwrite/session-log assumptions. |

## 3. Merge candidates

Do not keep multiple global skills with the same conceptual trigger.

| Cluster | Current skills | Proposed canonical path |
|---|---|---|
| TDD | `tdd`, `tdd-workflow`, `test-driven-development` | Pick one canonical TDD skill. My bias: keep `test-driven-development` if following Superpowers, otherwise keep `tdd-workflow` if it is more concrete. |
| Verification | `verification-loop`, `eval-loop` | Keep one. My bias: keep `eval-loop` if it is your own workflow; stage `verification-loop`. |
| Diagnosis | `diagnose`, `diagnosing-bugs` | Keep `diagnosing-bugs`; drop or alias `diagnose`. |
| Python | `python-patterns`, `python-data-analysis` | Different use cases: keep `python-data-analysis` project/global where analysis is needed; stage/route `python-patterns` to coding agents only. |
| Data Hub stages | `knowledge-claim-extraction`, `knowledge-candidate-review`, `knowledge-materialization`, `knowledge-daily-weekly-synthesis`, `knowledge-hygiene-audit`, `knowledge-source-ingestion` | Keep as project references or manager-invoked stage skills; avoid global distribution. |

## 4. Drop candidates

These should not be in managed distribution. For external upstreams, prefer `distribution_state: disabled` first; physical deletion can be separate.

| Decision | Skills | Reason |
|---|---|---|
| DROP | `setup-matt-pocock-skills` | Installer/setup skill, not runtime. |
| DROP | `caveman.bak` | Backup artifact, not a skill. |
| DROP or alias | `diagnose` | Duplicate of `diagnosing-bugs`. |
| DROP after staging review | `pytorch-patterns`, `mle-workflow`, `clickhouse-io` | User marked drop; preserve source lineage in registry if upstream source remains. |

## 5. Project-level confirmation needed

This is the most important section before changing `skills-sources.jsonc` broadly.

### 5.1 Current concrete project scopes that look safe

| Project | Skills | Suggested action |
|---|---|---|
| `mac-bootstrap` | `mac-bootstrap-maintenance`, `network-path-triage`, `daily-tagger`, `python-data-analysis` | Keep. `python-data-analysis` is currently the internal project distribution test sample. |
| `mac-bootstrap` | `knowledge-record`, `knowledge-reuse-retrieval` | Keep project-scoped unless you want global knowledge-record/retrieval outside this repo. |
| `mac-bootstrap` | `knowledge-claim-extraction`, `knowledge-candidate-review`, `knowledge-materialization`, `knowledge-daily-weekly-synthesis`, `knowledge-hygiene-audit`, `knowledge-source-ingestion` | Merge/demote into manager references if you want slimming. Keep source, but do not globalize. |
| `product_strategy` | `sql-analysis`, `decrypt-materialize`, `guizang-ppt-skill` | Keep if product_strategy remains active. |
| `franchise_store` | `franchise-store-sankey-analysis`, `sankey-flow-analysis`, `web-video-presentation-delivery` | Keep if catalogue/Sankey/video-presentation workflow remains active. |
| `www` | `marimo-analysis`, `marimo-dashboard-create`, `marimo-etl-test` | Keep if www/marimo project remains active. |
| `playground` | `ottos-effect-analysis`, `ottos-north-star-metric`, `ottos-retail-ab-test`, `daily-claude-battle-boost` | Keep if playground is still the method sandbox. |

### 5.2 Marked `[project]` but project target is not yet explicit

Please confirm the target project for each. Without this, they should remain staged/routed, not project-scoped.

| Skill | Current origin | User mark | Needs decision |
|---|---|---|---|
| `aihot` | upstream `khazix` | project | `mac-bootstrap`|
| `beautiful-article` | upstream `garden` | project | `product_strategy`|
| `gpt-image-2` | upstream `garden` | project |  `product_strategy`|
| `kb-retriever` | upstream `garden` | project | `mac-bootstrap`|
| `web-design-engineer` | upstream `garden` | project | `product_strategy`|
| `baoyu-diagram` | local/internal | project | `product_strategy`|
| `baoyu-infographic` | local/internal | project | `product_strategy`|
| `web-video-presentation` | runtime-only | project | product_strategy|
| `decrypt-read` | runtime-only | keep-global||

## 6. Proposed additions

| Decision | Skill/source | Suggested scope | Notes |
|---|---|---|---|
| ADD | `find-skills` from `https://github.com/vercel-labs/skills` | global routed: Claude/Codex/OpenCode/Cross-agent | Already added to registry, gated. |
| ADD | `skill-audit-reviewer` | `mac-bootstrap` project | Helps review quarantined external skills. |
| ADD | `skill-router-maintenance` | `mac-bootstrap` project | Maintains `skills-sources.jsonc` / `skill-targets.jsonc`. |
| ADD | `data-analysis-reporting` | `product_strategy` or global routed | Analysis-to-narrative/reporting skill. |
| ADD | `retail-experiment-analysis` | `product_strategy` or `playground` | Generalize pharmacy/retail AB and effect-analysis methods. |
| ADD | `marimo-duckdb-dashboard` | `www` or data platform project | Matches precompute + DuckDB + Parquet + marimo workflow. |

## 7. Next registry-change rule

Before Task 6, update `agent/skills-sources.jsonc` in this order:

1. Add upstream lineage sources as first-class external sources.
2. Add `distribution_state`: `enabled`, `staged`, `disabled`, `merged`.
3. Apply confirmed project scopes from section 5.
4. Do not physically delete upstream content yet; stop distributing first.
5. Run dry-run distribution and compare action count before/after slimming.
