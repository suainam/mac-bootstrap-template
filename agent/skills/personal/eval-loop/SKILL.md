---
name: eval-loop
description: >
  Structured evaluation and verification loop for agent output quality.
  Verifies solutions against criteria before delivering to user.
  Trigger: /eval, /verify, "run verification", "check your work"
---

# Evaluation & Verification Loop

## Purpose

Before delivering results, evaluate output quality against explicit criteria.
Prevents premature delivery and catches regression early.

## Loop Structure

```
1. DEFINE CRITERIA → What does "done" look like?
2. EXECUTE → Produce the output
3. EVALUATE → Score against criteria
4. FEEDBACK → If score < threshold, refine and loop
5. DELIVER → Once threshold met
```

## Criteria Checklist

- [ ] Solves the stated problem
- [ ] Handles edge cases (empty input, errors, boundaries)
- [ ] Follows conventions (project style, language idioms)
- [ ] Testable — can verify correctness independently
- [ ] Minimal — no dead code, no speculative features
- [ ] Documented intent — WHY not just WHAT

## Quick Commands

| Command | Action |
|---------|--------|
| `/eval [criteria]` | Evaluate current output |
| `/verify` | Run verification loop |
| `/checkpoint` | Save current state for rollback |
| `/quality-gate` | Run full quality gate |
