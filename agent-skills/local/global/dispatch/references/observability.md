# Sub-Worker Observability & 12-Factor Telemetry Reference

This reference details the three-dimensional zero-token metric collection architecture for sub-workers dispatched under Herdr, synthesized from real-world telemetry and 12-Factor Agent principles.

---

## 1. Metric Dimensions & Collection Architecture

```text
                  ┌────────────────────────────────────────────────────────┐
                  │                 Sub-Worker Telemetry Triad             │
                  └──────┬────────────────────┬────────────────────┬───────┘
                         │                    │                    │
                         ▼                    ▼                    ▼
                 【1. Wall Time】             【2. Token Usage】   【3. Host Resources】
                 (.dispatch/START_EPOCH       (Agent-specific      (Pane process group
                  vs .dispatch/DONE mtime)     session records)     ps pcpu / rss peak)
```

Data contract: Each lane produces `.dispatch/METER.json` upon completion:
```json
{
  "lane": "sim-writer",
  "role": "writer",
  "agent_kind": "opencode",
  "wall_time_seconds": 24.3,
  "tokens": {
    "input": 15878,
    "output": 420,
    "reasoning": 0,
    "cache_read": 0,
    "cache_write": 0
  },
  "resources": {
    "cpu_peak_percent": 14.2,
    "rss_peak_mb": 182.4
  }
}
```

---

## 2. Extraction Sources by Agent Kind

| Worker Kind | Token Telemetry Source | Wall Time Calculation | Process Resource Source |
| :--- | :--- | :--- | :--- |
| **Claude Code** | `~/.claude/projects/<slug>/<session>.jsonl` line `message.usage` (exact `input`, `output`, `cache_creation`, `cache_read`) | `.dispatch/DONE` mtime minus `.dispatch/START_EPOCH` | `herdr pane process-info --pane <PANE>` $\rightarrow$ PID $\rightarrow$ `ps -o pcpu,rss` |
| **Codex** | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` key `total_token_usage` (`input_tokens`, `output_tokens`, `reasoning_output_tokens`) | Same file-clock delta | Same PTY process tree sampling |
| **OpenCode** | `~/.local/share/opencode/opencode.db` SQLite table `message.data` JSON `tokens` | Same file-clock delta | Same PTY process tree sampling |
| **Agy** | Mandate `--log-file .dispatch/agy.log` during `herdr agent start` $\rightarrow$ parses JSON usage blocks | Same file-clock delta | Same PTY process tree sampling |

---

## 3. 12-Factor Design Rules Absorbed (from humanlayer/12-factor-agents)

1. **F8 (Own Your Control Flow)**:
   - Tool selection is decoupled from tool execution.
   - High-risk operations (e.g. `git push`, PR merge, deleting infrastructure) require an explicit interruptible approval gate (`Human Gate`).
2. **F3 & F9 (Context Efficiency & Error Budgeting)**:
   - Researchers MUST NOT dump entire terminal buffers or file contents to writers; output compact YAML (`path:line, claim, evidence`).
   - If a worker encounters 3 consecutive tool failures, it must write `NEED_HELP` to `.dispatch/progress.md` and escalate to the human rather than spinning.
3. **F10 (Small, Focused Steps)**:
   - Each lane's `.dispatch/TASK.md` MUST specify $\le 10$ checkable criteria. If a task exceeds 10 steps, the Planner must decompose it into sequential waves.
4. **F5 & F12 (Unified State & Reproducibility)**:
   - State is unified inside the Git worktree: `.dispatch/TASK.md` (contract), `.dispatch/progress.md` (append-only events), and `.dispatch/DONE` (verifiable proof).
   - Any lane can be replayed from the same commit and `TASK.md`.
