# Review Rules

This skill does not auto-promote extracted items into permanent knowledge.

Use these rough rules:

- `summary` -> useful for daily digest, not usually a standalone knowledge artifact
- `decision` -> likely ADR candidate
- `action` -> daily note / task queue candidate
- `risk` -> review queue candidate
- `open_loop` -> review queue or later follow-up candidate
- `topic` -> navigation aid, usually not promotable alone
- `fact` -> supporting evidence, often needs aggregation before promotion

## Promotion boundary

Do not auto-upgrade agent-inferred content into validated long-term knowledge.

Expected future flow:

```text
extracted_items
  -> candidate selection
  -> review actions (accept / reject / merge / defer)
  -> knowledge artifacts
```

## What to inspect during review

- Did the extracted item preserve the original intent?
- Is it actually a task vs. just a discussion point?
- Is a "decision" truly a settled choice or only a proposed direction?
- Does the item need owner/due-date metadata?
- Is the item duplicated elsewhere in the same document?
