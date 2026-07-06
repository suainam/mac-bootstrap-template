---
name: knowledge-record
description: Record knowledge artifacts directly into the permanent SQLite knowledge base during conversation — decisions, reusable patterns, actions, and reference material. Use when you produce a concrete decision, actionable recommendation, reusable knowledge pattern, risk assessment, error pattern, or any structured artifact the user is likely to want in their knowledge base.
---

# knowledge-record

Record a structured knowledge artifact straight into the data hub's
`knowledge_records` table.  Written records are `status=accepted` and are
picked up by the nightly materialization step without human review.

## When to trigger

- An **architecture decision** the team should reference later (→ `adr`)
- A **reusable pattern, insight, or how-to** (→ `card`)
- A **notable event, decision, or outcome** from today's work (→ `daily`)
- An **error pattern / gotcha / workaround** discovered during debugging (→ `card`)
- A **cross-cutting guideline** that affects multiple subsystems (→ `adr`)

## When NOT to trigger

- Pure operation steps ("install X, then restart Y") — those belong in README
- Status reports ("today I fixed a typo") — already captured in daily notes
- Trivial one-liners with no reusability — be selective

## Steps

1. **Select type** — use `references/type-guide.md` to pick `adr`, `card`, or `daily`
2. **Draft the artifact** — write title + content with full context
3. **Collect metadata** — tags, background (user's original question), impact, references
4. **Call `scripts/record_knowledge.py`** — pass `--type`, `--title`, `--content` plus optional metadata
5. **Confirm** — tell the user what was recorded and encourage them to check the vault tomorrow

## Rules

- Write **one knowledge record per call** — do not batch multiple decisions
- Prefer `card` when unsure about `adr` vs `card` (cards are easier to promote later)
- Always fill `--background` — this preserves the user's original question for context
- Always fill `--tags` — enables Obsidian tag-based filtering
- Do **not** ask the user for permission or confirmation — the skill is designed to be autonomous

## Completion criterion

A new row in `knowledge_records` with `status='accepted'`, visible to the
nightly materialization pipeline.  Confirm to the user that the record was
saved and will land in the vault on the next `materialize_candidates` run.
