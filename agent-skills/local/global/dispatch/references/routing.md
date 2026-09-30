# Task-to-Model Routing & Quota Failover Reference

## 1. Task-to-Model Routing Matrix

When `--kind` is omitted, the orchestrator classifies the task and assigns the optimal worker kind, model, and reasoning effort:

| Task Class | Preferred Agent | Default Model | Reasoning Effort / Flags | Role & Rationale |
| :--- | :--- | :--- | :--- | :--- |
| **代码实现 (Implementation)** | **Codex** | `gpt-6-luna` | `-c model_reasoning_effort="xhigh"` (or `"max"`) | Deep multi-step architecture & greenfield coding |
| **代码重构 (Refactoring)** | **Codex** 或 **Claude** | `gpt-6.1-sol` / `claude-sonnet-5` | Codex: `low` effort; Claude: `--dangerously-skip-permissions` | Fast syntactic & structural refactoring with low token cost |
| **代码审查与前端 (Review/Frontend)** | **Agy** | `gemini-3.8-flash-medium` | `--effort medium`, `verbosity: "low"` | Astute code auditing, contract verification, taste-driven UI |
| **轻量查询/PR/审计 (Lightweight/PR)** | **OpenCode** | Free Model Pool (Cloudflare/Zen) | `--auto` | Deterministic git operations, PR release, zero-cost queries |

*Note on Dynamic Model Resolution*: Model IDs in this matrix are recommended targets. When `--model` is omitted, `herdr-dispatch.sh` relies on each agent's configured native default (e.g. `~/.codex/config.toml`, OpenCode native free pool), preventing startup failures when specific model IDs are unconfigured or unverified.

---
## 2. Quota Exhaustion Signatures & Failover Hierarchy

Rate limits and credit exhaustion are detected via visible terminal buffer (`herdr pane read <pane> --source visible`):

### Quota Signatures
- **Codex**:
  - `You’ve hit your usage limit`
  - `5h 0% left`
  - `try again at <time>`
- **Claude Code**:
  - `credit balance is too low`
  - `Rate limit reached`
  - `out of credits`

### Automatic Failover Chains
1. **Implementation Failover**:
   $$\text{Codex (6-luna)} \xrightarrow{\text{5h limit}} \text{Agy (gemini-3.8-flash-medium)} \xrightarrow{\text{quota}} \text{OpenCode}$$
2. **Refactoring Failover**:
   $$\text{Claude (sonnet-5)} \xrightarrow{\text{credit low}} \text{Codex (6-sol low)} \xrightarrow{\text{limit}} \text{Agy (gemini-3.8-flash-medium)}$$
3. **Review/Frontend Failover**:
   $$\text{Agy (gemini-3.8-flash)} \xrightarrow{\text{fallback}} \text{Claude (sonnet-5)} \xrightarrow{\text{fallback}} \text{OpenCode}$$
4. **Lightweight/PR Failover**:
   $$\text{OpenCode} \xrightarrow{\text{fallback}} \text{Agy (-p print mode)}$$

---

## 3. Non-Interactive Print Mode (Zero TUI Overhead)

For read-only investigations, system checks, or simple queries that do not modify repository code:
- **OpenCode**: `opencode run --auto "<query>"`
- **Antigravity**: `agy -p "<query>" --model gemini-3.8-flash-medium`

*Rules:*
- Do not create a git worktree or Herdr workspace for pure queries.
- Print output directly to stdout in milliseconds.
