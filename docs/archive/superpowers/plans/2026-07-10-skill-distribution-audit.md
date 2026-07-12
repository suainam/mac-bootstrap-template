# Skill Distribution Audit Draft

> Historical record only; this draft is not an active distribution instruction. Use `docs/skill-supply-chain.md`.

> Purpose: classify the current production skill distribution before slimming or adding skills. This file is a review checklist, not an execution plan. Do not delete or redistribute anything until the checkboxes are reviewed.

## Key correction

The current registry draft cannot treat every skill under `agent/skills/personal/` as internally authored. Some production skills are upstream-origin skills promoted or copied into runtime views. The audit must track source lineage separately from local storage location.

## Current counts

| Surface | Count | Notes |
|---|---:|---|
| New draft registry | 41 | 2 external examples + 39 local skills |
| Draft registry global | 16 | Includes `knowledge-lifecycle-manager` as global |
| Draft registry project | 25 | Includes `python-data-analysis` as `mac-bootstrap` project sample |
| Production upstream `ecc` | 14 | Present under `~/.agent/skills/upstream/ecc` |
| Production upstream `mattpocock` | 7 | Present under `~/.agent/skills/upstream/mattpocock` |
| Production upstream `khazix` | 2 | Present under `~/.agent/skills/upstream/khazix` |
| Production upstream `garden` | 4 | Present under `~/.agent/skills/upstream/garden` |
| Production upstream `humanizer` | 1 | Present under `~/.agent/skills/upstream/humanizer` |
| Production upstream `obsidian` | 5 | Present under `~/.agent/skills/upstream/obsidian` |
| Production upstream `superpowers` | 7 | Present under `~/.agent/skills/upstream/superpowers`; not in old `skills-promote.txt` |

## Immediate implication

Before Task 6 replaces the old skill management surfaces, `agent/skills-sources.jsonc` needs an explicit source lineage model:

```jsonc
"sources": {
  "ecc": {"type": "external", "fetcher": "git", "ref": "everything-claude-code", "skills": {}},
  "mattpocock": {"type": "external", "fetcher": "git", "ref": "mattpocock-skills", "skills": {}},
  "khazix": {"type": "external", "fetcher": "git", "ref": "khazix-skills", "skills": {}},
  "garden": {"type": "external", "fetcher": "git", "ref": "garden-skills", "skills": {}},
  "humanizer": {"type": "external", "fetcher": "git", "ref": "humanizer-zh", "skills": {}},
  "obsidian": {"type": "external", "fetcher": "git", "ref": "obsidian-skills", "skills": {}},
  "superpowers": {"type": "external", "fetcher": "runtime", "ref": "superpowers", "skills": {}}
}
```

Exact repo URLs/refs can be filled from the old sync script or existing local upstream remotes. Do not guess them.

## Review labels

Use these labels when reviewing each skill:

- `[KEEP-GLOBAL]` keep loaded across most agents.
- `[KEEP-ROUTED]` keep, but route only to selected agents.
- `[PROJECT]` keep project-scoped only.
- `[STAGE]` keep as available source, but do not distribute globally by default.
- `[DROP]` remove from managed distribution.
- `[MERGE]` merge into another skill or manager skill.
- `[ADD]` add new source/skill.
- `[VERIFY]` needs user confirmation.

## Recommended default policy

1. Keep global only for cross-cutting meta workflow, daily coding/data work, and user-specific high-frequency capabilities.
2. Put domain/project skills under projects only.
3. Treat upstream bundles as source catalogs; only selected skills should be distributed globally.
4. External skills with scripts stay in quarantine/stage until manually approved.
5. Do not distribute the same conceptual skill from multiple upstreams unless one has a clearly different trigger.

---

# A. Production upstream skills

## A1. everything-claude-code / ECC

These are upstream-origin skills. They should not be classified as internal even if they are visible in global agent dirs.

| Mark | Skill | Current production status | Recommendation | Reason |
|---|---|---|---|---|
| [merge] | `python-patterns` | global runtime | [STAGE] or [KEEP-ROUTED] | Useful for generic Python coding, but may duplicate `python-data-analysis`; route to coding agents only if retained. |
| [merge] | `python-testing` | global runtime | [KEEP-ROUTED] | Useful for test work; route to Claude/Codex/OpenCode, maybe not Pi/Reasonix. |
| [drop] | `pytorch-patterns` | global runtime | [STAGE] | Niche unless actively doing ML/deep learning. |
| [drop] | `mle-workflow` | global runtime | [STAGE] | Valuable but low-frequency; stage unless ML projects are active. |
| [stage] | `postgres-patterns` | global runtime | [STAGE] | Keep source, route only when PostgreSQL work is active. |
| [drop] | `clickhouse-io` | global runtime | [STAGE] | Keep source; route only if ClickHouse appears in actual work. |
| [stage] | `docker-patterns` | global runtime | [KEEP-ROUTED] | Useful for infra/data projects; could pair with internal `docker-data-project`. |
| [stage] | `database-migrations` | global runtime | [STAGE] | Less relevant to current data-analysis focus unless app/backend projects need it. |
| [stage] | `data-throughput-accelerator` | global runtime | [KEEP-ROUTED] | Relevant to ETL/backfill/data platform work. |
| [stage] | `data-scraper-agent` | global runtime | [STAGE] | Potentially useful, but not always needed globally. |
| [merge] | `tdd-workflow` | global runtime | [MERGE] or [DROP] | Duplicates superpowers `test-driven-development` and `tdd`; keep one TDD path. |
| [merge] | `verification-loop` | global runtime | [MERGE] or [DROP] | Duplicates internal `eval-loop`; keep one verification entry. |
| [keep-global] | `search-first` | global runtime | [KEEP-ROUTED] | Good default for coding/research before custom build. |
| [keep-global] | `documentation-lookup` | global runtime | [KEEP-ROUTED] | Useful if Context7/docs lookup remains part of workflow. |

Suggested slim default: keep routed `python-testing`, `docker-patterns`, `data-throughput-accelerator`, `search-first`, `documentation-lookup`; stage the rest.

## A2. mattpocock-skills

| Mark | Skill | Current production status | Recommendation | Reason |
|---|---|---|---|---|
| [drop] | `setup-matt-pocock-skills` | global runtime | [DROP] | Setup skill should not stay globally distributed after install. |
| [keep-global] | `diagnosing-bugs` | global runtime | [KEEP-ROUTED] | Good coding workflow skill. |
| [merge] | `tdd` | global runtime | [MERGE] | Duplicates other TDD skills; choose one canonical TDD skill. |
| [keep-global] | `grill-with-docs` | global runtime | [STAGE] | Useful for docs-heavy review, but likely not global default. |
| [keep-global] | `improve-codebase-architecture` | global runtime | [KEEP-ROUTED] | Useful for refactor/design review. |
| [keep-global] | `handoff` | global runtime | [STAGE] | Could be useful, but duplicates existing planning/summary behavior. |
| [keep-global] | `writing-great-skills` | global runtime | [KEEP-ROUTED] | Useful while rebuilding skill supply chain; later can stage. |

## A3. khazix-skills

| Mark | Skill | Current production status | Recommendation | Reason |
|---|---|---|---|---|
| [project] | `aihot` | global runtime | [KEEP-ROUTED] | User often tracks AI tools/news; but route to chat/coding agents, not necessarily all. |
| [keep-global] | `neat-freak` | global runtime | [KEEP-GLOBAL] | Directly useful for end-of-session docs/memory cleanup. |

## A4. garden-skills

| Mark | Skill | Current production status | Recommendation | Reason |
|---|---|---|---|---|
| [project] | `beautiful-article` | global runtime | [KEEP-ROUTED] | Useful for HTML article deliverables; route to agents that can work with files/UI. |
| [project] | `gpt-image-2` | global runtime | [STAGE] | Host image generation already exists; keep as reference unless local image workflow is active. |
| [project] | `kb-retriever` | global runtime | [KEEP-ROUTED] | Useful for local knowledge-base retrieval. |
| [project] | `web-design-engineer` | global runtime | [KEEP-ROUTED] | Useful for visual web artifacts and dashboards. |

## A5. humanizer-zh

| Mark | Skill | Current production status | Recommendation | Reason |
|---|---|---|---|---|
| [keep-global] | `humanizer-zh` | global runtime | [KEEP-ROUTED] | Useful for Chinese polishing; route to writing-capable agents. |

## A6. obsidian-skills

| Mark | Skill | Current production status | Recommendation | Reason |
|---|---|---|---|---|
| [drop] | `obsidian-markdown` | global runtime | [KEEP-ROUTED] | Useful if Obsidian vault work remains common. |
| [drop] | `obsidian-bases` | global runtime | [STAGE] | Niche; stage unless actively using Bases. |
| [drop] | `json-canvas` | global runtime | [STAGE] | Niche; stage unless canvas workflows are active. |
| [drop] | `obsidian-cli` | global runtime | [KEEP-ROUTED] | Useful for vault operations. |
| [drop] | `defuddle` | global runtime | [KEEP-ROUTED] | Useful for extracting clean markdown from web pages. |

## A. superpowers runtime skills

These exist in `~/.agent/skills/upstream/superpowers` and in production runtime dirs, but they were not represented in old `skills-promote.txt`. They need explicit treatment.

| Mark | Skill | Current production status | Recommendation | Reason |
|---|---|---|---|---|
| [KEEP-GLOBAL] | `using-git-worktrees` | global runtime | [KEEP-GLOBAL] | Required before isolated feature work; already used in this session. |
| [KEEP-GLOBAL] | `writing-plans` | global runtime | [KEEP-GLOBAL] | Required for plan creation. |
| [KEEP-GLOBAL] | `executing-plans` | global runtime | [KEEP-GLOBAL] | Required for plan execution. |
| [KEEP-ROUTED] | `finishing-a-development-branch` | global runtime | [KEEP-ROUTED] | Useful at completion; route to coding agents. |
| [KEEP-ROUTED] | `requesting-code-review` | global runtime | [KEEP-ROUTED] | Useful when review tooling exists. |
| [merge] | `test-driven-development` | global runtime | [MERGE] | Choose this or ECC/mattpocock TDD, not all. |
| [keep-global] | `brainstorming` | global runtime | [KEEP-ROUTED] | Useful before creative/dev work, but may be noisy if always global. |

---

# B. Local/internal skills in draft registry

## B1. Keep global by default

| Mark | Skill | Current draft scope | Recommendation | Reason |
|---|---|---|---|---|
| [KEEP-GLOBAL] | `knowledge-lifecycle-manager` | global | keep global | User corrected this: reusable knowledge sedimentation entry. |
| [KEEP-GLOBAL] | `caveman` | global | keep global | User appears to use token-compression/caveman workflow. |
| [KEEP-GLOBAL] | `caveman-help` | global | keep global | Useful discovery card for caveman family. |
| [keep-global] | `langgpt-prompt-writer` | global routed | keep routed | Already sensibly restricted to Claude/Codex/OpenCode/Cross-agent. |
| [KEEP-ROUTED] | `qiaomu-goal-meta-skill` | global | maybe route to Claude/Codex/OpenCode/Cross-agent | Goal writing is mostly coding-agent oriented; Pi/Reasonix/Antigravity may not need it. |
| [drop] | `docker-data-project` | global | route to coding/data agents | Relevant to user's Docker-first data workflows. |
| [drop] | `eval-loop` | global | keep or merge with verification-loop | Useful, but duplicate with upstream verification. |

## B2. Slim candidates among global internal skills

| Mark | Skill | Current draft scope | Recommendation | Reason |
|---|---|---|---|---|
| [project] | `baoyu-diagram` | global | [KEEP-ROUTED] or [STAGE] | Useful, but maybe only needed for visual/document work. |
| [project] | `baoyu-infographic` | global | [KEEP-ROUTED] or [STAGE] | Similar to diagram; route to visual-capable agents only. |
| [stage] | `cavecrew` | global | [STAGE] | Subagent delegation may not work in all hosts; keep source but route only where supported. |
| [KEEP-GLOBAL] | `caveman-commit` | global | [KEEP-ROUTED] | Route to coding agents only. |
| [keep-global] | `caveman-compress` | global | [STAGE] | Risky because it overwrites memory files; should be explicit, not broadly global. |
| [keep-global] | `caveman-review` | global | [KEEP-ROUTED] | Coding agents only. |
| [keep-global] | `caveman-stats` | global | [STAGE] | Claude-specific session log behavior; probably not all agents. |

## B3. Project-scoped internal skills: likely keep

| Mark | Project | Skills | Recommendation |
|---|---|---|---|
| [PROJECT] | `mac-bootstrap` | `mac-bootstrap-maintenance`, `network-path-triage`, `knowledge-record`, `knowledge-reuse-retrieval` | Keep. High relevance to this repo. |
| [PROJECT] | `product_strategy` | `sql-analysis`, `decrypt-materialize`, `guizang-ppt-skill` | Keep if product_strategy remains active. |
| [PROJECT] | `franchise_store` | `franchise-store-sankey-analysis`, `sankey-flow-analysis`, `web-video-presentation-delivery` | Keep if catalogue/Sankey work remains active. |
| [PROJECT] | `www` | `marimo-analysis`, `marimo-dashboard-create`, `marimo-etl-test` | Keep if www/marimo data-app work remains active. |
| [PROJECT] | `playground` | `ottos-effect-analysis`, `ottos-north-star-metric`, `ottos-retail-ab-test`, `daily-claude-battle-boost` | Keep if playground remains the sandbox for business-analysis methods. |
| [PROJECT] | `mac-bootstrap` | `python-data-analysis`, `daily-tagger` | Keep as test/sample or move later if no longer needed. |

## B4. Data-hub skill consolidation candidates

Current project-scoped data-hub skills are detailed stage skills. For slimming, keep manager/retrieval/record globally or project-level, and demote stage skills to references if they are rarely invoked directly.

| Mark | Skill | Recommendation |
|---|---|---|
| [KEEP-GLOBAL] | `knowledge-lifecycle-manager` | Global command center. |
| [merge] | `knowledge-record` | Keep project-scoped unless you want global record capability. |
| [merge] | `knowledge-reuse-retrieval` | Keep project-scoped; maybe global later if useful outside mac-bootstrap. |
| [MERGE] | `knowledge-claim-extraction` | Consider reference under manager. |
| [MERGE] | `knowledge-candidate-review` | Consider reference under manager. |
| [MERGE] | `knowledge-materialization` | Consider reference under manager. |
| [MERGE] | `knowledge-daily-weekly-synthesis` | Consider reference under manager. |
| [MERGE] | `knowledge-hygiene-audit` | Consider reference under manager. |
| [MERGE] | `knowledge-source-ingestion` | Consider reference under manager. |

---

# C. Runtime-only or unmanaged production skills

These appeared in production agent skill dirs but are not currently represented in the draft registry or old source list. They need an explicit decision.

| Mark | Skill | Seen in | Recommendation | Reason |
|---|---|---|---|---|
| [keep-global] | `codebase-memory` | Claude runtime | [STAGE] or map to MCP docs | Might be plugin/runtime material, not a normal managed skill. |
| [keep-global] | `decrypt-read` | Claude runtime | [PROJECT] or [DROP] | Likely local/private or stale; inspect before managing. |
| [merge] | `diagnose` | Codex/OpenCode/Pi/Reasonix runtime | [DROP] or alias | Looks like duplicate of `diagnosing-bugs`. |
| [keep-global] | `playwright` | Codex runtime | [KEEP-ROUTED] | Useful browser automation skill; should be represented if intentionally installed. |
| [project] | `web-video-presentation` | Codex runtime | [PROJECT] or [KEEP-ROUTED] | Related to presentation work; decide whether it belongs in franchise_store/product_strategy. |
| [drop] | `write-a-skill` | Codex/OpenCode/Pi/etc. runtime | [STAGE] | Useful while rebuilding skills, but not necessarily global. |
| [drop] | `zoom-out` | Codex/OpenCode/Pi/etc. runtime | [STAGE] | Need inspect source and value. |
| [drop] | `caveman.bak` | Antigravity runtime | [DROP] | Backup artifact should not be a managed skill. |

---

# D. Suggested additions

These are additions to consider after pruning, not automatic installs.

| Mark | Skill/source idea | Suggested scope | Why |
|---|---|---|---|
| [ADD] | `skill-audit-reviewer` internal skill | `mac-bootstrap` project | Guides review of quarantined external skills: scripts, permissions, frontmatter, diff, and approval hash. |
| [ADD] | `skill-router-maintenance` internal skill | `mac-bootstrap` project | Maintains `skills-sources.jsonc` and `skill-targets.jsonc`, validates source lineage, and proposes route changes. |
| [ADD] | `data-analysis-reporting` internal skill | `product_strategy` or global routed | Your actual work often needs analysis-to-narrative/reporting, not just Python execution. |
| [ADD] | `retail-experiment-analysis` internal skill | `product_strategy` or playground | Generalize OTTOS/franchise AB/effect-analysis methods for retail/pharma scenarios. |
| [ADD] | `marimo-duckdb-dashboard` internal skill | `www` or data platform project | Directly matches your internal data app stack: precompute + DuckDB + Parquet + marimo. |

---

# E. Proposed next action

1. Add upstream source lineage to `agent/skills-sources.jsonc`; do not classify upstreams as internal.
2. Add `status` or `distribution_state` per skill: `enabled`, `staged`, `disabled`, `merged`.
3. Generate a review command that prints this audit table from registry + runtime dirs.
4. Apply slimming only after each `[VERIFY]` item is changed to `[KEEP-*]`, `[PROJECT]`, `[STAGE]`, `[DROP]`, or `[MERGE]`.

Recommended first slimming pass:

- Stage niche DB/ML upstreams: `pytorch-patterns`, `mle-workflow`, `postgres-patterns`, `clickhouse-io`, `database-migrations`.
- Drop setup/stale artifacts: `setup-matt-pocock-skills`, `caveman.bak`.
- Merge duplicate TDD/verification skills into one canonical path.
- Keep superpowers core: `using-git-worktrees`, `writing-plans`, `executing-plans`.
- Keep project domain skills project-scoped, not global.
