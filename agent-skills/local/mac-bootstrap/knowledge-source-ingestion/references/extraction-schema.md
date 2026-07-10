# Extraction Schema

Use extracted items as the bridge between raw source blocks and future candidate knowledge.

Canonical extracted item:

```json
{
  "item_type": "summary | decision | action | risk | open_loop | topic | fact",
  "title": "short label",
  "content": "full extracted text",
  "confidence": 0.0,
  "chunk_index": 0,
  "metadata": {
    "owner_hint": null,
    "due_hint": null,
    "source_format": "markdown"
  }
}
```

## Classification intent

- `summary`: document-level or section-level condensed overview
- `decision`: explicit choice, rule change, acceptance, cancellation
- `action`: concrete task, owner hint, next step, follow-up
- `risk`: downside, impact, uncertainty, blockage
- `open_loop`: unresolved issue, later discussion, pending validation
- `topic`: section header, theme, discussion area
- `fact`: descriptive content that should not yet be promoted to decision/action

## Drift control

When a source format changes, first ask:

1. Did block boundaries break?
2. Or did classification logic break?

Fix the layer that actually drifted.

## LLM fallback

When deterministic logic is not enough, constrain output with a typed schema.
Do not let the model emit free-form markdown as the primary extracted representation.
