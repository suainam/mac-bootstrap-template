# Skill Supply Chain

This runbook describes the registry-driven Agent Skill distribution system.

## Authority

Human-edited authority lives in two JSONC files:

- `agent-skills/registry/sources.jsonc` owns skill source lineage, scope, project routing, distribution state, audit policy, and gate policy.
- `agent-skills/registry/targets.jsonc` owns agent target directories, output format, and symlink/copy strategy.

Generated/runtime outputs are not authoritative:

- `agent-skills/external/quarantine/`
- `.agent-state/skills-lock.json`
- `.agent-state/skill-sync-runs/`
- `.agent-state/skill-snapshots/`
- `.agent-state/skill-bundles/`
- `.agent-state/skill-candidates/`
- `~/.claude/skills`, `~/.codex/skills`, `~/.config/opencode/skills`, `~/.pi/agent/skills`, `~/.reasonix/skills`, `~/.gemini/antigravity-cli/skills`, `~/.agents/skills`
- project `.agents/skills/` directories

Implementation is split by responsibility under `scripts/`:

- `skill_registry.py` — registry models, JSONC parsing, and validation.
- `skill_intake.py` — skills.sh fetch, inspection, bundle catalog, and audit gate.
- `skill_distribution.py` — source resolution, symlink reconciliation, and snapshots.
- `skill_supply_chain.py` — stable CLI entry point and compatibility exports.

## Source model

Each skill has a source record:

- `type: external` for skills fetched through skills.sh or tracked as external/manual references.
- `type: internal` for first-party skills stored inside this repository.
- `scope: global` for user-level agent distribution.
- `scope: project` for project-local `.agents/skills` distribution.
- `distribution_state: enabled | staged | disabled | merged`.

An external repository may additionally declare a bundle. A bundle is the
lifecycle unit for fetch, refresh, disable, and restore; its discovered catalog
still feeds individual skill audit, approval, scope, and target policy. The
Matt Pocock source is managed this way.

The intended engineering front door is `/wayfinder` for work larger than one
session, followed as needed by `/grill-with-docs`, `/to-spec`, `/to-tickets`,
`/implement`, and `/code-review`. `/wayfinder` maps uncertainty; it does not
replace the later specification, ticket, implementation, or review stages.

Only `enabled` skills are distributed. `staged`, `disabled`, and `merged` records preserve source lineage and review decisions without installing the skill.

External skills must enter repo-local quarantine first:

```bash
make skill-fetch SOURCE=vercel-skills SKILL=find-skills
make skill-audit SOURCE=vercel-skills SKILL=find-skills
make skill-diff SOURCE=vercel-skills SKILL=find-skills
```

Use `skill-fetch-bundle` for a source that declares bundle management; the
single-skill fetch command rejects those sources to prevent a second workflow.

`skill-refresh` runs `skill-ensure-bundles` before distribution. It fetches an
enabled bundle only when its catalog or source directories are missing, so a
fresh checkout can self-bootstrap while ordinary refreshes remain local. Use
`skill-update` to refresh an existing bundle from upstream.

The fetch command uses `npx skills@latest add <ref> --skill <skill> --agent universal --copy --yes` in an isolated temporary work directory, then moves the result into `agent-skills/external/quarantine/<source>/<skill>/`.

For a bundle, use the bundle entry point instead:

```bash
make skill-fetch-bundle SOURCE=mattpocock-skills
```

This runs `npx skills@latest add https://github.com/mattpocock/skills --all
--agent universal --copy --yes` only inside a temporary work directory, then
writes the candidate source and its catalog to
`.agent-state/skill-candidates/mattpocock-skills/`. It never overwrites active
quarantine. Promote a staged candidate explicitly with:

```bash
make skill-promote SOURCE=mattpocock-skills
```

Promotion is per skill and atomic at the bundle directory boundary. A known,
already-approved, script-free, `LOW`-risk skill with unchanged source identity
may use `gate.auto_update: true` to accept a changed upstream hash without a
new manual approval. New or unregistered skills, scripts, missing approval
baselines, higher-risk content, and gate/audit failures remain blocked in the
candidate directory. The active catalog is rewritten only after promotion.

The daily update entry point is:

```bash
make system-upgrade
```

It requires a real interactive terminal, runs `brew update` and `brew upgrade`
in that same terminal, and only then refreshes the configured source (default:
`mattpocock-skills`) and distributes approved skills. Homebrew owns any sudo
prompt; the wrapper does not capture, store, or supply passwords. Set
`BREW_BIN`, `PYTHON_BIN`, or `SKILL_SOURCE` only when the local installation
needs a non-default executable or bundle.

## Distribution

Plan and validate:

```bash
make skill-plan
make skill-check
```

Distribute approved/enabled skills from the real checkout only:

```bash
make skill-distribute
```

For an intentionally narrow rollout, use all relevant filters together:

```bash
python3 scripts/skill_supply_chain.py distribute \
  --surface global --agent codex --skill <skill> --dry-run
python3 scripts/skill_supply_chain.py distribute \
  --surface global --agent codex --skill <skill>
```

`--agent` scopes a global target. It is especially important for target-format
migrations: it prevents an unrelated target from being rewired while a single
runtime is being verified.

Do not run a real distribution apply from a DevSpace worktree. It would create user-level symlinks pointing at the temporary worktree path. The distributor refuses this by default; dry-run and snapshots are still safe in worktrees.

Compatibility wrapper:

```bash
scripts/skill-refresh.sh --dry-run
scripts/skill-refresh.sh
```

## Snapshot and comparison workflow

Before replacing or refreshing runtime skill dirs, snapshot the current state:

```bash
make skill-snapshot LABEL=pre-replacement
```

The snapshot records every configured global and project skill view, including:

- skill name
- target path
- directory/file/symlink kind
- symlink target
- resolved path
- `SKILL.md` SHA-256
- frontmatter `name` and `description`

After applying the new distribution, run another snapshot:

```bash
make skill-snapshot LABEL=post-replacement
```

Compare the two JSON files under `.agent-state/skill-snapshots/`:

```bash
python3 scripts/skill_supply_chain.py snapshot-diff --before <pre.json> --after <post.json>
```

The diff reports missing, added, and changed skill entries per target surface. It exits non-zero when the post snapshot is missing entries that existed before.

For an intentional retirement or format migration, record the expected missing
entries before treating that non-zero exit as a failure. The expected shape is
explicitly reviewed: added replacement entries, only planned missing legacy
entries, and no unexpected project-target changes.

## Stale runtime cleanup

Distribution updates enabled target paths but does not automatically delete old entries. Run reconcile before and after real distribution:

```bash
make skill-reconcile              # dry-run only
make skill-reconcile APPLY=1      # prune stale symlinks and flat .md copies
```

Reconcile only removes entries that are no longer `enabled` for that target surface. It skips real directories and leaves them for manual review. Like distribution, real cleanup is refused from a DevSpace worktree by default.

### Rename, retire, and delete safely

Do not delete a source record when a Skill is renamed or retired. Set the old
record to `disabled` with the canonical replacement in `reason`, then use a
narrow reconcile:

```bash
python3 scripts/skill_supply_chain.py reconcile \
  --surface global --skill <old-skill> --dry-run
python3 scripts/skill_supply_chain.py reconcile \
  --surface global --skill <old-skill> --apply
```

This removes only managed symlinks or managed flat copies. It never deletes a
real directory unless `--remove-real-paths` is explicitly supplied after manual
review. Verify every configured target afterwards: directory targets must
resolve to the canonical quarantine or local source; copy targets must byte-match
the source `SKILL.md`.

### Target-format migration

Some runtimes can load either `<skills>/<name>.md` or
`<skills>/<name>/SKILL.md`. Prefer the directory form when a Skill has auxiliary
Markdown, templates, examples, or scripts. It preserves relative references and
keeps one source tree for every target.

Declare the old form in `targets.jsonc` as `legacy_formats`, then run this
sequence from the real checkout:

```bash
make skill-snapshot LABEL=pre-target-migration
python3 scripts/skill_supply_chain.py distribute \
  --surface global --agent <agent> --dry-run
python3 scripts/skill_supply_chain.py reconcile \
  --surface global --agent <agent> --dry-run
python3 scripts/skill_supply_chain.py distribute --surface global --agent <agent>
python3 scripts/skill_supply_chain.py reconcile --surface global --agent <agent> --apply
make skill-snapshot LABEL=post-target-migration
```

`legacy_formats` lets reconcile remove a legacy flat file only when it
byte-matches a registered source `SKILL.md`. Unknown or same-name user Markdown
remains untouched.

All current configured runtime targets are directory/soft-link targets. Copy
actions are not a valid new distribution path; the only retained copy handling
is byte-matched legacy flat-file cleanup during target migration.

## External intake and acceptance checklist

Use this sequence for every external Skill, including skills.sh sources:

1. Verify the public listing and the canonical upstream path. Do not trust a
   historical slug when upstream renamed it.
2. Read every shipped file, including files referenced by `SKILL.md`; identify
   scripts, external writes, commits, tracker mutations, and runtime-specific
   assumptions.
3. Add the registry record with exact source, desired agents, audit policy, and
   a manual gate bound to the content hash.
4. Run `fetch`, `audit`, and `diff`; the observed hash must equal
   `gate.approved_hash` before distribution.
5. Add a regression test for state, target set, and exact hash. Test a required
   script allowance explicitly when the source ships scripts.
6. Snapshot, dry-run, apply narrowly, reconcile retired entries, snapshot again,
   then scan the real target paths.

Global scope means a reusable policy, not automatic compatibility with every
runtime. Record intentional target exclusions in the registry `reason`. A Skill
that requires a host capability such as parent-level parallel agents must not be
distributed to a runtime that cannot provide it.

## Data Hub policy

Data Hub skills are not disposable one-off helpers. They are managed as an industrialized, reusable, idempotent pipeline under the `mac-bootstrap` project scope.

Keep these stage skills managed and project-visible:

- `knowledge-source-ingestion`
- `knowledge-claim-extraction`
- `knowledge-candidate-review`
- `knowledge-materialization`
- `knowledge-daily-weekly-synthesis`
- `knowledge-hygiene-audit`
- `knowledge-record`
- `knowledge-reuse-retrieval`

`knowledge-lifecycle-manager` is global because it is the reusable command center and router.

Do not collapse Data Hub stages into a single one-off document unless the replacement preserves state contracts, idempotency keys, replay behavior, auditability, and clear operational boundaries.

## Common edits

Add or route a skill:

1. Edit `agent-skills/registry/sources.jsonc`.
2. Run `make skill-check`.
3. Run `make skill-plan`.
4. For external skills, fetch/audit/diff before enabling distribution.
5. Run `make skill-distribute` only after review, and only from the real checkout, not an isolated DevSpace worktree.

Change an agent target path:

1. Edit `agent-skills/registry/targets.jsonc`.
2. Ensure it still matches production expectations or explicitly document the migration.
3. Run `make skill-check` and `make skill-distribute --dry-run` equivalent through `python3 scripts/skill_supply_chain.py distribute --dry-run`.

## Safety rules

- Do not run non-dry-run distribution from a DevSpace worktree; merge to the real checkout first.
- Do not fetch external skills directly into user-level agent directories.
- Do not hardcode target directories in shell scripts or Python; use `agent-skills/registry/targets.jsonc`.
- Do not delete staged/disabled/merged source records just to reduce visible count; those records are the audit trail.
- Do not treat a `local/` directory location as proof of internal authorship; use source lineage in the registry.
