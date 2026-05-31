# Instinct System (Continuous Learning)

Inspired by ECC v2. Instincts are lightweight learnings extracted from sessions.
Unlike skills (static), instincts evolve with confidence scores.

## Structure

```
~/.agent/instincts/
├── active/           # Live instincts with confidence scores
│   ├── <category>.yaml
├── archived/         # Deprecated or merged instincts
└── README.md
```

## Lifecycle

1. **Capture** — Agent notices a recurring pattern during session
2. **Store** — Written to `active/<category>.yaml` with confidence 0.3
3. **Reinforce** — Each successful reuse increments confidence
4. **Evolve** — When confidence > 0.8, consider promoting to dedicated skill
5. **Prune** — Instincts unused for 30 days → archive

## Category Tags

| Tag | Scope |
|-----|-------|
| `code:python` | Python-specific patterns |
| `code:general` | Language-agnostic patterns |
| `tool:rtk` | RTK usage patterns |
| `tool:cbm` | Codebase-memory MCP patterns |
| `workflow:build` | Build/deploy workflows |
| `workflow:test` | Testing patterns |
| `project:<name>` | Project-specific learned preferences |
