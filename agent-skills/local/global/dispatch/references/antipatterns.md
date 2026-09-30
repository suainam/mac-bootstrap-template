# Orchestrator Antipatterns, Failure Modes & Hard Rules (Real-World Battle Tested)

This reference codifies the real-world behavioral bugs, blind spots, and architectural antipatterns observed in live multi-agent orchestration (specifically with GPT-6 Luna, Claude Sonnet, and OpenCode across `auroraops-control` and `mac-bootstrap`).

---

## 1. Top 5 Deadly Orchestrator Antipatterns

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   THE 5 DEADLY ORCHESTRATOR TRAPS                               │
├───────────────────────────────┬──────────────────────────────────┬──────────────────────────────┤
│ 1. Context Amnesia            │ Re-exploring the whole repo      │ Refuses to trust earlier     │
│    (失忆症与漫无目的探索)     │ every time human speaks          │ research/findings            │
├───────────────────────────────┼──────────────────────────────────┼──────────────────────────────┤
│ 2. Pre-Wait Busywork          │ Firing 5-8 probe tools           │ Panic-induced false          │
│    (派发后的虚假忙碌)         │ immediately after dispatching    │ diligence / anxiety loop     │
├───────────────────────────────┼──────────────────────────────────┼──────────────────────────────┤
│ 3. Child-Worktakeover         │ Re-reading codebase / re-running │ Destroys parallel execution  │
│    (编排者抢活越权)           │ tests when worker goes idle      │ contract; burns 20k+ tokens  │
├───────────────────────────────┼──────────────────────────────────┼──────────────────────────────┤
│ 4. Infinite Review Loop       │ Spawning Reviewer 2, 3, 4        │ Inability to recognize       │
│    (无限套娃审查死循环)       │ instead of stopping at Human Gate│ convergence and yield        │
├───────────────────────────────┼──────────────────────────────────┼──────────────────────────────┤
│ 5. Blind Interactive Flag     │ Passing `-m` to bare `opencode`  │ Confusing headless CLI flags │
│    (裸命令参数盲猜)           │ causing immediate exit 1         │ with interactive TUI flags   │
└───────────────────────────────┴──────────────────────────────────┴──────────────────────────────┘
```

---

## 2. Deep Dive: Manifestation, Root Causes & Hard Guards

### Bug 1: Pre-Wait Busywork Loop (派发后的虚假忙碌)
- **Manifestation**: Immediately after injecting a prompt via `herdr agent prompt`, the orchestrator does NOT yield control. Instead, it fires a flurry of calls: `herdr agent explain`, `test -s ...`, `herdr pane read`, writing review task drafts—burning turns while the child worker is just starting up.
- **Root Cause**: The LLM confuses "task dispatched" with "I must keep busy until it finishes".
- **Hard Guard**:
  > **Invariant**: `herdr agent prompt <worker>` with `[NOTIFY]` MUST be the terminal action of that phase. The orchestrator MUST immediately yield control or call non-blocking wait. All probe tools are strictly prohibited for 30s after prompt injection.

### Bug 1.1: The Todo Reminder Trap (Todo 催促引起的虚假忙碌)
- **Manifestation**: After dispatching a child agent, the orchestrator intends to yield, but the harness's `todo` reminder wakes the session up every turn with "You have open todos", forcing the orchestrator into a frenzy of useless probes.
- **Root Cause**: Leaving an active/pending todo unblocked during external background waiting.
- **Hard Guard**:
  > **Invariant**: When yielding for external agent execution, ALWAYS execute `todo(op="block", task="...", reason="Waiting for child agent <name> IPC [NOTIFY]")`. Never leave an open unblocked todo while waiting.

### Bug 2: The Infinite Review Loop (无限套娃审查死循环)
- **Manifestation**:
  1. Writer finishes code.
  2. Skeptic 1 reviews, identifies 2 real defects.
  3. Orchestrator correctly routes defects back to Writer.
  4. Writer fixes defects and commits (`9aee1df`).
  5. **THE TRAP**: Instead of recognizing that all Skeptic findings were addressed, the orchestrator spawns Skeptic 2, then Skeptic 3, getting stuck in an infinite review recursion!
- **Root Cause**: Missing a "Max Review Rounds" cap and failure to distinguish between "new code requiring review" and "verified defect closure".
- **Hard Guard**:
  > **Review Convergence Ceiling**: In Diamond governance, Skeptic review is strictly limited to **ONE round of review + ONE round of re-work verification**. Once the Writer commits the Skeptic's requested fixes, the orchestrator MUST NOT spawn another Skeptic session. It MUST transition directly to **Human Gate**.

### Bug 3: Sub-Shell Prompt Injection Quoting Failure (Shell 引号解析爆炸)
- **Manifestation**: Orchestrator puts bash commands, regexes like `{{.*?}}`, or multiline file paths into `herdr agent prompt <name> "..."`. The outer shell parses unescaped syntax and throws:
  `error: command not found: .github/workflows/gitleaks.yml`, `error: command not found: [extend]`.
- **Root Cause**: Shell expansion inside nested double-quoted strings.
- **Hard Guard**:
  > **External File Contract**: Task prompts exceeding 100 characters or containing YAML/TOML/regex syntax MUST be written to `/tmp/<task>.md` using the `write` tool first. The `prompt` command only passes a simple reference: `"Read /tmp/<task>.md and execute..."`.

### Bug 4: Silent Handoff Overwriting (时间戳精度丢失)
- **Manifestation**: Using date format `$(date +%Y%m%d)`. When Writer runs at 10:00, Skeptic runs at 10:15, and Writer fixes at 10:30, all three write to `repo-name-handoff-20260930.md`, overwriting each other and destroying evidence.
- **Hard Guard**:
  > **Mandatory Precision**: All Handoff filenames MUST use `$(date +%Y%m%d_%H%M%S)`.

### Bug 5: Sub-Worker Exit Amnesia (退出未检乱发乱等)
- **Manifestation**: An interactive agent exits (e.g. OpenCode exits after writing DONE). The orchestrator attempts to send `herdr agent prompt <exited_pane>` without checking if the agent is still registered, leading to stalled inputs or input leakage into the raw bash shell.
- **Hard Guard**:
  > **State Verification**: Before targeting an agent, verify `herdr agent get <name>` reports `agent_status` as `idle` or `working`. If `agent_not_found`, do NOT prompt; read the pane buffer directly.
