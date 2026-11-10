# Subagent delegation template (s- series)

Use this to spawn any `s-` agent from the main session. Fill **every** field; a
gap is exactly what causes a child to idle or spin. S agents run in a fresh
context and do not inherit the caller's conversation.

## Target
- Deliverable, non-goals, and the paths the child owns.

## Change
- Concrete steps, APIs, and seams.
- The executable boundary: what the child may and may not touch.

## Acceptance
- A falsifiable completion criterion, plus the exact command or evidence that
  proves it. Without this, the child cannot know when to stop.

## Context
- The main session's concluded findings (so the child does not re-run
  discovery), current repository state, and the Why behind the slice.

## Handoff rule
- Require the child to restate goal + acceptance + boundary + verification in
  its first message. On mismatch, correct before it works. This is the guard
  against long idle: a child that cannot restate the contract stops and asks,
  it never guesses.
