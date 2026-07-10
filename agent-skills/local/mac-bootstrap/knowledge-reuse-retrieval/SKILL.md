---
name: knowledge-reuse-retrieval
description: Retrieve reusable context packets from Daily notes, ADRs, Cards, and open knowledge candidates before analysis, writing, planning, or decision work. Use when a knowledge-heavy workflow should start with "search before work" instead of drafting from scratch.
---

# Knowledge Reuse Retrieval

Run this skill before creating new knowledge artifacts or repeating prior analysis.

## Workflow

1. Derive a compact search intent from the current `task_goal`, keywords, project, and optional date window.
2. Run `scripts/run-retrieval.sh` to build `retrieval_packet.json`.
3. Read [references/packet-contract.md](references/packet-contract.md) when you need the exact output shape.
4. Use the packet as structured context, not as a free-form summary to copy blindly.
5. If the packet is empty, record that explicitly and continue with fresh work.

## Rules

- Query Daily, ADR, Card, and candidate layers together.
- Preserve "no reusable context" as a valid result.
- Prefer the highest-scoring reusable artifacts first.
- Treat open loops as constraints to resolve or acknowledge before promotion.
- Do not mutate notes or SQLite in this stage.
