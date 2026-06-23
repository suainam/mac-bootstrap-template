# Obsidian Vault Kit

Reusable Obsidian configuration for project-local vaults.

## Scope

This kit keeps portable vault behavior:

- daily, weekly, monthly, quarterly, yearly note locations
- template paths
- Dataview-friendly frontmatter
- Templater folder templates
- stable plugin enablement list

This kit intentionally does not manage local state:

- `.obsidian/workspace.json`
- plugin binaries under `.obsidian/plugins/*/main.js`
- sync state, cache files, and per-device UI layout

## Install

```bash
template/editors/obsidian/install.sh /path/to/vault
```

The vault path is required on purpose. The kit should never guess a project
vault or write into a private workspace by default.

## Agent Notes

Use open Obsidian formats first: Markdown, properties/frontmatter, Bases, JSON Canvas.
Keep machine-local Obsidian state out of reusable bootstrap config.
