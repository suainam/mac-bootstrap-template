# ADR-0001: Skill promotion lists externalization

**Status**: Accepted  
**Date**: 2026-05-31  
**Driver**: Skill lists duplicated across manifest.yaml and sync-agent-upstreams.sh  

## Context

The agent skill promotion whitelist (14 ECC skills, 8 Matt Pocock skills, 4 personal
skills) was maintained in two places:
- `agent/manifest.yaml` — `upstreams.*.promote.skills` sections  
- `scripts/sync-agent-upstreams.sh` — bash arrays in the promote loops

Adding a skill required editing both files. In practice they drifted.

## Decision

Extract all three lists into `agent/skills-promote.txt` — a flat, sectioned text file.

- `sync-agent-upstreams.sh` reads the file via `awk` section parsing
- `manifest.yaml` keeps inline lists for documentation, with a comment pointing to
  the canonical source
- The format uses `# ── SECTION ──` headers + one skill name per line

This follows the pattern established by `agent/pi-packages.txt`.

## Consequences

**Positive**:
- Single source of truth — add a skill by editing one file
- Sectioned format is parseable by both bash (awk) and YAML consumers

**Negative**:
- `manifest.yaml` still has duplicates (documentation — manual sync risk if reader
  edits YAML instead of the data file)
- `awk` section parsing is less obvious than inline bash arrays

## Alternatives considered

- **Keep inline only in manifest.yaml, have sync-agent-upstreams.sh parse YAML**:  
  More complex parsing (YAML in bash), no clear benefit.
- **Generate manifest.yaml from the data file**:  
  Would require a YAML generation step; not worth the complexity for a static file.
