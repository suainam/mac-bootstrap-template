---
name: curate-repo-knowledge
description: Curate repository knowledge when a cold-start project needs Agent routing, existing docs drift or conflict, a milestone needs cleanup, Agent memory should graduate, or a changed contract affects another project.
---

# Curate Repository Knowledge

Curate the smallest navigable knowledge surface. Keep each fact at one authority, route other mentions to it, and add machinery only after repeated evidence.

## 1. Audit

Read repository rules first and follow their project-native discovery and validation priority. Use the declared code graph for code discovery, Git's tracked/unignored set for document inventory, and existing language manifests, Make targets, and tests for stack facts. Use generic search only as a named fallback when the project supplies no suitable capability.

Create a coverage ledger from the user's named directories and requested scenarios before consulting generated indexes. For each item record its actual entrypoint, nearest rules, authority, evidence, and unresolved gaps. A missing manifest or root README is a discovery gap, not permission to omit the directory or invent metadata. Inspect relevant ignored runtime views separately: record registry ownership, symlink targets, and source realpaths without recursively loading unrelated ignored data.

Run the bundled `python3 <skill-root>/scripts/audit_project.py <project-root> --format json` for mechanical checks. If it reports `ENCRYPTED_MARKDOWN`, use `$decrypt-materialize` to create an external verified output and retain its JSON result, then rerun with `--materialized-manifest <result.json>`. Read [references/audit-report.md](references/audit-report.md) only when interpreting findings. Read the human entrypoint, routed authorities, and structured sources they name. Inspect candidates before accepting them.

Complete when every existing knowledge surface has an audience, authority, loading tier, and current evidence source, with no project-native capability silently bypassed.

### Optional semantic judgment assistance

Use `$typesafe-ai` only when deterministic inspection has produced a bounded
semantic candidate that code cannot classify reliably. Keep the repository and
workflow authoritative:

1. Build a small JSON state from the inspected source excerpts, candidate
   authorities, ownership rules, and evidence paths. Redact secrets and raw
   operational logs before any model call.
2. Ask one narrow typed judgment at a time. Use a `Choice` for mutually
   exclusive classifications such as `keep`, `duplicate`, `stale`,
   `conflicting`, `misplaced`, or `dead`; use a `Noul` for an independent
   condition; use a `Score` only for an ordered relevance or confidence
   dimension. Include a no-match outcome where applicable.
3. Treat the result and probability as advisory evidence. Code still performs
   file inventory, link checks, ownership lookups, budgets, and mutations.
   Low-probability or destructive/review-required outcomes stop for human
   approval instead of silently changing an authority.
4. Record the candidate evidence, judgment, threshold, and final human or
   deterministic decision in the dry-run. Do not store prompts, raw logs,
   credentials, or private source material in repository knowledge.

If the TypeSafe SDK or live documentation is unavailable, do not invent an API
call or claim model verification. Continue with a tabletop classification,
label it as such, and keep the normal deterministic and human review gates.

## 2. Select one branch

- When durable Agent guidance or ownership routing is missing, read [references/bootstrap.md](references/bootstrap.md) and run **bootstrap**.
- When a handbook exists or the request concerns cleanup, drift, synchronization, or a milestone, read [references/reconcile.md](references/reconcile.md) and run **reconcile**. If current code, configuration, contracts, or authorities changed, finish this semantic alignment before commit or push.
- After remote success for a completed Issue/PR milestone or parent/submodule publish, run repository closeout: verify hosted and local Issue, PR, branch, and worktree state, then follow the project's issue-tracker lifecycle. A merge alone is not a complete handoff.
- When effectiveness must be proved, also read [references/evaluation.md](references/evaluation.md) before designing cases or claiming gains.
- When supported Agent memory must be cleaned, also read [references/memory-reconcile.md](references/memory-reconcile.md).
- When a verified change affects another project, also read [references/cross-project.md](references/cross-project.md).
- When an example would resolve an output or scope question, read [references/auroraops-example.md](references/auroraops-example.md).

Complete when exactly one mutation branch is selected and only its conditional reference is loaded.

## 3. Propose

Produce a dry-run containing:

1. current and proposed ownership matrix;
2. evidence for each fact or rule;
3. exact bounded patches, classified as safe, review-required, or prohibited;
4. before/after non-empty lines, estimated tokens, and bytes for persistent files;
5. validation commands and unresolved judgments.

Prefer deletion, consolidation, promotion, and links before creating a file. Create only a stable responsibility that no current authority owns.

Complete when every proposed line has one authority, one audience, evidence, and a size budget.

## 4. Apply the authorized patch

Apply safe changes after the user accepts the dry-run. Apply review-required changes only when the user resolves the named judgment. Preserve project-native authorities and edit the smallest relevant surface.

<!-- IMMUTABLE-GUARDRAILS:START -->
Require explicit approval to overwrite an authority, delete or rename a file, change hooks, change global agent configuration, resolve an ambiguous conflict, or exceed a persistent-context budget. Keep secrets, private prompts, and raw logs outside reports and generated docs.
<!-- IMMUTABLE-GUARDRAILS:END -->

Complete when the diff contains only authorized, evidence-backed changes.

## 5. Verify

Rerun the audit with `--strict`; run repository documentation checks and relevant tests. Inspect the diff for duplicated facts, narrative sediment, dead references, unexplained growth, and missing affected audiences. Report skipped checks as skipped.

Complete when mechanical checks pass, every semantic candidate is resolved or listed, and the final summary names changed authorities, evidence, budgets, and remaining decisions.

Match every requested outcome to direct evidence in the coverage ledger. Mechanical success does not prove semantic coverage, a help command does not prove a business run, and a registry entry does not prove distribution. For affected projections verify all intended targets resolve to the canonical source after distribution and repeat the bounded operation to check idempotence. Challenge wrong-directory, stale-index, missing-input, repeated-write, and read-versus-write cases before closing; label tabletop review separately from executed tests and independent review.
