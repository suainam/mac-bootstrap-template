# Session Compact Checklist

Run when approaching token budget (30K per session, 4K per task).

## Before Compacting

1. [ ] Extract key decisions → `instincts/active/`
2. [ ] Save in-progress state → `~/.agent/artifacts/`
3. [ ] Note blockers and next steps

## Compaction Strategy

1. **Summarize**: What was done, what was learned, what's next
2. **Drop**: Resolved issues, verbose tool outputs, confirmed configs
3. **Preserve**: Unresolved bugs, pending decisions, active design docs
4. **Tag**: Referenceable checkpoints (`agent:checkpoint:<hash>`)

## After Compacting

1. [ ] Verify critical context retained
2. [ ] Update status line
3. [ ] Continue with clear next step
