---
name: explain-changes
version: 1.0.0
description: Explain completed coding work so the user genuinely understands it. Writes a summary of changes and a manual testing checklist to a solo scratchpad, includes a mermaid diagram of database updates, then runs a 5-question comprehension quiz with grading and a retest on missed areas. Use when asked to "explain what you did", "walk me through the changes", or "help me understand this work".
---

# Explain Changes Skill

You are explaining coding work that was already done, well enough that the user could defend every change in a code review they didn't attend. Three deliverables, in order: a scratchpad (summary + manual testing checklist + database diagram), then a comprehension quiz, then a grade report with a retest if needed.

This skill changes no code. If you notice a bug or improvement while explaining, note it in the summary; do not fix it.

---

## STEP 1: Establish the work

Identify what "the changes" are:

1. **Session first.** If the work happened in this conversation, explain from that context. Still re-read the touched files — explain what is actually on disk, not what you remember writing.
2. **Git diff fallback.** If invoked cold (no coding work in this session), ask the user for a base ref, then read `git diff {base}...HEAD` (plus `git status` for uncommitted work) and read every touched file for surrounding context. This also covers "explain this branch" for work done by someone else.

If neither source yields any changes, say so and stop.

While reading, collect what the later steps need: the intent behind each change, the schema-touching pieces (migrations, models, schema files), the entry points a human would exercise to verify each behavior, and the decisions someone could plausibly misunderstand.

---

## STEP 2: Write the scratchpad

Write a **solo scratchpad** named `explain: {slug}` with the three sections below.

### Solo scratchpad conventions

- Call `mcp__solo__help(topic="scratchpads")` before first scratchpad use in a session.
- `scratchpad_write` always creates a new pad. To update in place, get the id via `scratchpad_list`, then use `scratchpad_edit` with a section target: `{"type": "section", "section_heading": "Heading text"}`.
- Appended content must start with a blank line or a leading `## Heading` glues onto the previous line.

### Fallback

If the solo MCP is not available in this session, write to `explanations/{slug}.md` in the repo instead (create the directory; use hyphens in the slug, no punctuation).

### Section 1: Summary of Changes

Organize by **intent, not by file** — each subsection is a thing the work accomplishes, with the files that serve it listed under it as `path:line` references. For each intent explain what changed, why this approach, and what the alternative would have been where a real alternative existed. Call out anything surprising: behavior changes a caller would notice, new dependencies, config or env requirements, data implications.

### Section 2: Database Updates

A fenced `mermaid` block with an `erDiagram` covering **only the touched tables**: new tables, added/modified/dropped columns, and new or changed relationships. Mark what changed — suffix changed items with a marker (e.g. `_NEW`, `_CHANGED` in the attribute comment position) and include a one-line legend below the diagram. Follow the diagram with a short prose note on data implications: backfills, destructive migrations, nullable-to-required transitions, index changes.

If the work touches no schema, the entire section is one line: **No database changes.** Do not draw an orientation diagram of untouched tables.

### Section 3: Manual Testing Checklist

Concrete checkbox steps the user can run or click through, covering the happy path, the edge cases, and anything automated tests can't cover (visual polish, feel, copy). Be specific: exact URLs, commands, inputs, and what to expect. If a step needs setup (a seeded record, a logged-in role), the setup is its own preceding step. Lead with the copy-pasteable run command if the project has one.

After writing, tell the user the scratchpad name and give a two-sentence orientation in chat — do not paste the scratchpad contents into the conversation.

---

## STEP 3: Quiz

Write 5 multiple-choice questions that test **understanding, not recall**. Good shapes:

- "What happens if X?" — trace behavior through the new code.
- "Why was Y done instead of Z?" — the reasoning behind a decision.
- "Which file would you touch to change W?" — can they navigate the result.
- "What breaks if this line is removed?" — do they know what's load-bearing.
- "What does the migration do to existing rows?" — data implications.

Rules for questions:

- Every question must be answerable from the scratchpad plus the code; never quiz on trivia (exact line counts, file names with no navigational value).
- Wrong options must be plausible — a reasonable misreading of the work, not filler.
- 3-4 options per question, exactly one correct.
- Cover different areas of the work; don't ask two questions about the same change unless it's the only change.

Deliver via **AskUserQuestion in two rounds: first 3 questions, then 2.** Do not reveal correctness between rounds — grading happens once at the end. Keep question text and option labels self-contained; the user may answer without the scratchpad open.

---

## STEP 4: Grade

After both rounds, present one grade report:

1. **Score**: N/5.
2. **Per question**: the user's answer, the correct answer, and a short explanation — for misses, explain why the chosen option is wrong, not just why the right one is right.
3. **For each miss**, re-explain the underlying change from the top: what it does, why it's built that way, where it lives. This is the point of the skill; don't compress it to one line.

### Retest

If the user missed **2 or more**, offer a retest: 2-3 **fresh** questions (never reworded originals) covering only the missed areas, delivered in one AskUserQuestion round, graded the same way. One retest round maximum — after that, summarize any remaining gaps in prose and stop.

If the user missed 0-1, congratulate briefly and stop. No retest offer.

---

## Revisions

If the user asks for more depth on any area, update the scratchpad in place via `scratchpad_edit` with a section target — do not create a second scratchpad.
