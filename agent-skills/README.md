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

## Local taxonomy

- `local/global/`: reusable Skills distributed to configured global agent targets.
- `local/<project>/`: project-maintained Skills, normally distributed only to that project's `.agents/skills/`.
- `local/shadows/<source>/`: reviewed local shadows retaining external lineage.
- `local/deprecated/`: disabled sources retained for history and audit.
- `external/quarantine/`: ignored external fetch output pending review.

`knowledge-lifecycle-manager` is a global reusable command center. The current
adapter drives the mac-bootstrap Data Hub backend. Individual `knowledge-*` stage
Skills remain project-scoped; the manager may invoke them without globally
installing every stage.

## Operations

```bash
make skill-plan
make skill-check
python3 scripts/skill_supply_chain.py distribute --dry-run
make skill-snapshot LABEL=pre-change
make skill-reconcile
```

Run real distribution and reconcile apply only from the real checkout. Full
operations: [`../docs/skill-supply-chain.md`](../docs/skill-supply-chain.md).
