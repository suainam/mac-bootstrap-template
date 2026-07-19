# AuroraOps Example

Use this as output shape, not a universal file template.

## Evidence

- Repository rules required `AGENTS.md` to be a relative symlink to `CLAUDE.md`.
- `catalog/roles.yml` already owned structured Role facts; `docs/role-catalog.md` was its projection.
- The first audit found oversized routing files, dead links, long legacy copies, and identical platform compatibility files.

## Patch

- Compressed `CLAUDE.md` from 88 to 62 lines, `CONTEXT.md` from 298 to 77, and `docs/README.md` from 102 to 52.
- Replaced three legacy instruction copies with pointers to current authorities.
- Replaced byte-identical compatibility files with relative symlinks; retained Gemini variants whose required frontmatter differed.
- Repaired verified dead links and made total lines, not non-empty lines, enforce the Agent-file budget.

## Proof

- Strict audit: zero errors and warnings; semantic candidates remained for human judgment.
- Documentation and skill tests passed.
- One fresh-Agent A/B kept the target command correct while reducing total tokens from 101,934 to 30,529 and wall time from 18.98s to 10.13s. This proves the case, not universal effectiveness.
