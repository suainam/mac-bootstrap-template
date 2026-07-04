---
name: knowledge-daily-weekly-synthesis
description: Generate daily or later weekly knowledge synthesis from Git activity, agent chats, external sources, candidates, and materialized notes. Use when the promotion step is done and the workflow needs the narrative summary layer refreshed without duplicating sections.
---

# Knowledge Daily Weekly Synthesis

This skill owns the narrative layer, not the extraction or promotion layers.

## Workflow

1. Confirm ingest and candidate state are current.
2. Run `scripts/run-daily-synthesis.sh YYYY-MM-DD` for the first-phase daily workflow.
3. Read [references/synthesis-scope.md](references/synthesis-scope.md) when deciding whether the task is daily or future weekly mode.
4. Rewrite the `## AI 总结` section in place instead of appending duplicates.
5. Keep weekly expansion separate until a dedicated weekly renderer exists.

## Rules

- First phase only guarantees Daily synthesis.
- Treat Git logs, chat logs, external source digests, and candidate digest as synthesis inputs.
- Keep the section idempotent.
- Do not re-ingest formal knowledge notes here.
- If LLM generation fails, surface the failure rather than writing partial text.
