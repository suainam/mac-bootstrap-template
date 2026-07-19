# Bootstrap

Use this branch when the project lacks durable Agent guidance or knowledge routing.

## Discover before proposing

1. Inventory existing rules, human docs, domain docs, decisions, operations docs, plans, generated projections, catalogs, schemas, configuration, tests, and tracker guidance through project-declared tools. Reuse code graphs, Git ignore semantics, package manifests, Make targets, and repository test entrypoints before fallback discovery.
2. Extract only project-specific facts that code does not make reliably obvious: red lines, authority boundaries, critical commands, domain distinctions, safety constraints, and known traps.
3. Label each extraction as verified fact, repeated-pattern candidate, or unresolved judgment. Cite the current source.
4. Ask for the smallest decisions that change authority, risk, or meaning. Keep other uncertainty visible.

## Default ownership fallback

Use only when existing project rules do not define an owner.

| Knowledge | Default authority |
| --- | --- |
| Human purpose and quick start | `README.md` |
| Agent red lines, commands, routing | one of `AGENTS.md` or `CLAUDE.md` |
| Compatibility Agent filename | relative symlink to the Agent authority |
| Stable vocabulary and distinctions | `CONTEXT.md` |
| Accepted decisions and rationale | ADR collection |
| Current operations | runbook or wiki collection |
| Temporary work | plans, specs, or issue tracker |
| Structured facts | catalog, schema, config, code, or tests |
| Generated prose | replaceable projection pointing to its source |

Use Markdown links between explanatory documents. Use filesystem symlinks only for compatibility files that must be byte-identical.

## Loading budgets

Use the budgets emitted by `scripts/audit_project.py`; it is the single mechanical authority for limits and measurements. Treat on-demand and human documents by responsibility, and propose a semantic split only when one document owns multiple stable responsibilities.

Split by audience or stable responsibility. Keep each routed fact only at its owner; an index names the owner without restating its contents.

## Minimal scaffold rule

Create only files justified by observed project needs. A small library may need one human entry and one Agent authority. Add context, ADRs, or operations docs only when the corresponding stable knowledge exists. Present the ownership matrix and patch before writing.

Bootstrap is complete when a new Agent can find the correct authority without repository-wide search, every generated statement has evidence, and persistent budgets pass.
