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
- `local/<project>/`: project-maintained Skills distributed to the project's
  `.agents/skills/` view and declared compatibility views such as `.claude/skills/`.
- `local/shadows/<source>/`: reviewed local shadows retaining external lineage.
- `local/deprecated/`: disabled sources retained for history and audit.
- `external/quarantine/`: ignored external fetch output pending review.

`knowledge-lifecycle-manager` is a global reusable command center. The current
adapter drives the mac-bootstrap Data Hub backend. Individual `knowledge-*` stage
Skills remain project-scoped; the manager may invoke them without globally
installing every stage.

## Implemented distribution contract

The registry owns one source tree per Skill. Distribution creates directory
symlinks only; every projection of the same Skill must resolve to that same
source realpath.

| Scope | Managed view | Consumers |
|---|---|---|
| Global | `~/.claude/skills/<name>/SKILL.md` | Claude Code; also discovered by OpenCode and OMP |
| Global | `~/.agents/skills/<name>/SKILL.md` | Codex, OpenCode, and OMP's canonical `agents` provider |
| Global compatibility | `~/.codex/skills`, `~/.config/opencode/skills`, and agent-specific targets in `registry/targets.jsonc` | Existing production compatibility views pending an explicit target migration |
| Project | `<repo>/.agents/skills/<name>/SKILL.md` | Codex, OpenCode, and OMP |
| Project compatibility | `<repo>/.claude/skills/<name>/SKILL.md` | Claude Code |

OMP has no separate registry target. It discovers the Claude, Agents, Codex,
and OpenCode views, de-duplicates identical files by realpath, then resolves
same-name collisions by provider priority. Do not add another OMP copy of the
same source.

Managed Skills follow the open Agent Skills format: a one-level
`<name>/SKILL.md` directory, a 1-64 character lowercase hyphenated `name`, and a
non-empty `description` of at most 1024 characters. Supporting `scripts/`,
`references/`, and `assets/` remain inside the same source directory. Claude
plugins are a different package type and are not silently flattened into this
standalone-Skill pipeline.

Official discovery references, verified 2026-08-13:

- [Agent Skills specification](https://agentskills.io/specification)
- [Claude Code Skills](https://code.claude.com/docs/en/slash-commands)
- [Codex Skills](https://learn.chatgpt.com/docs/build-skills)
- [OpenCode Agent Skills](https://opencode.ai/docs/skills/)
- [OMP Skills](https://github.com/can1357/oh-my-pi/blob/main/docs/skills.md)

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

Use the registry CLI for narrow rollout or cleanup; do not hand-edit runtime
skill directories:

```bash
python3 scripts/skill_supply_chain.py distribute --surface global --agent codex --skill <skill> --dry-run
python3 scripts/skill_supply_chain.py reconcile --surface global --agent codex --skill <retired-skill> --dry-run
```

`reasonix` is a directory/symlink target. Its `legacy_formats` declaration is
intentional: reconcile removes a legacy flat `.md` copy only when it byte-matches
a registered source `SKILL.md`, preserving user files and multi-file Skill
resources such as templates, examples, and scripts.
