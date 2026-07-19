---
name: curate-repo-knowledge
description: Curate repository knowledge when a cold-start project needs Agent routing, existing docs drift or conflict, a milestone needs cleanup, Agent memory should graduate, or a changed contract affects another project.
---

# Curate Repository Knowledge

Curate the smallest navigable knowledge surface. Keep each fact at one authority, route other mentions to it, and add machinery only after repeated evidence.

## 1. Audit

Read repository rules first and follow their project-native discovery and validation priority. Use the declared code graph for code discovery, Git's tracked/unignored set for document inventory, and existing language manifests, Make targets, and tests for stack facts. Use generic search only as a named fallback when the project supplies no suitable capability.

Run the bundled `python <skill-root>/scripts/audit_project.py <project-root> --format json` for mechanical checks. Read [references/audit-report.md](references/audit-report.md) only when interpreting findings. Read the human entrypoint, routed authorities, and structured sources they name. Inspect candidates before accepting them.

Complete when every existing knowledge surface has an audience, authority, loading tier, and current evidence source, with no project-native capability silently bypassed.

## 2. Select one branch

- When durable Agent guidance or ownership routing is missing, read [references/bootstrap.md](references/bootstrap.md) and run **bootstrap**.
- When a handbook exists or the request concerns cleanup, drift, synchronization, or a milestone, read [references/reconcile.md](references/reconcile.md) and run **reconcile**.
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
