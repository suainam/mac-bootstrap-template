# Skill Supply Chain

This runbook describes the registry-driven Agent Skill distribution system.

## Authority

Human-edited authority lives in two JSONC files:

- `agent/skills-sources.jsonc` owns skill source lineage, scope, project routing, distribution state, audit policy, and gate policy.
- `agent/skill-targets.jsonc` owns agent target directories, output format, and symlink/copy strategy.

Generated/runtime outputs are not authoritative:

- `agent/skills/quarantine/`
- `.agent-state/skills-lock.json`
- `.agent-state/skill-sync-runs/`
- `.agent-state/skill-snapshots/`
- `~/.claude/skills`, `~/.codex/skills`, `~/.config/opencode/skills`, `~/.pi/agent/skills`, `~/.reasonix/skills`, `~/.gemini/antigravity-cli/skills`, `~/.agents/skills`
- project `.agents/skills/` directories

## Source model

Each skill has a source record:

- `type: external` for skills fetched through skills.sh or tracked as external/manual references.
- `type: internal` for first-party skills stored inside this repository.
- `scope: global` for user-level agent distribution.
- `scope: project` for project-local `.agents/skills` distribution.
- `distribution_state: enabled | staged | disabled | merged`.

Only `enabled` skills are distributed. `staged`, `disabled`, and `merged` records preserve source lineage and review decisions without installing the skill.

External skills must enter repo-local quarantine first:

```bash
make skill-fetch SOURCE=vercel-skills SKILL=find-skills
make skill-audit SOURCE=vercel-skills SKILL=find-skills
make skill-diff SOURCE=vercel-skills SKILL=find-skills
```

The fetch command uses `npx skills add <ref> --skill <skill> --agent universal --copy --yes` in an isolated temporary work directory, then moves the result into `agent/skills/quarantine/<source>/<skill>/`.

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

## Stale runtime cleanup

Distribution updates enabled target paths but does not automatically delete old entries. Run reconcile before and after real distribution:

```bash
make skill-reconcile              # dry-run only
make skill-reconcile APPLY=1      # prune stale symlinks and flat .md copies
```

Reconcile only removes entries that are no longer `enabled` for that target surface. It skips real directories and leaves them for manual review. Like distribution, real cleanup is refused from a DevSpace worktree by default.

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

1. Edit `agent/skills-sources.jsonc`.
2. Run `make skill-check`.
3. Run `make skill-plan`.
4. For external skills, fetch/audit/diff before enabling distribution.
5. Run `make skill-distribute` only after review, and only from the real checkout, not an isolated DevSpace worktree.

Change an agent target path:

1. Edit `agent/skill-targets.jsonc`.
2. Ensure it still matches production expectations or explicitly document the migration.
3. Run `make skill-check` and `make skill-distribute --dry-run` equivalent through `python3 scripts/skill_supply_chain.py distribute --dry-run`.

## Safety rules

- Do not run non-dry-run distribution from a DevSpace worktree; merge to the real checkout first.
- Do not fetch external skills directly into user-level agent directories.
- Do not hardcode target directories in shell scripts or Python; use `agent/skill-targets.jsonc`.
- Do not delete staged/disabled/merged source records just to reduce visible count; those records are the audit trail.
- Do not treat `agent/skills/personal/` location as proof of internal authorship; use source lineage in the registry.
