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
├───────────────────────────────┼──────────────────────────────────┼──────────────────────────────┤
│ 6. Misrouted Notify Target    │ Prompting child without binding  │ Child broadcasts to user     │
│    (回报目标地址错乱)         │ actual `herdr pane current` ID   │ or wrong sibling pane        │
└───────────────────────────────┴──────────────────────────────────┴──────────────────────────────┘
```

---

## 2. Deep Dive: Manifestation, Root Causes & Hard Guards

### Bug 1: Pre-Wait Busywork Loop (派发后的虚假忙碌)
- **Manifestation**: Immediately after a successful unified-bus dispatch, the orchestrator does NOT yield control. Instead, it fires a flurry of probes and review drafts while the child worker is just starting up.
- **Root Cause**: The LLM confuses "task dispatched" with "I must keep busy until it finishes".
- **Hard Guard**:
  > **Invariant**: A successful `dispatch_plugin.py dispatch` delivery with a bound callback is the terminal action of that phase. The orchestrator MUST immediately yield control; it must not replace IPC waiting with busy polling.

### Bug 1.1: The Todo Reminder Trap (Todo 催促引起的虚假忙碌)
- **Manifestation**: After dispatching a child agent, the orchestrator intends to yield, but the harness's `todo` reminder wakes the session up every turn with "You have open todos", forcing the orchestrator into a frenzy of useless probes.
- **Root Cause**: Leaving an active/pending todo unblocked during external background waiting.
- **Hard Guard**:
  > **Invariant**: When the host exposes a real todo-block mutation surface, block the waiting task. OMP 18.5.0 does not expose that extension API, so the extension must report `NOT VERIFIED` rather than simulate blocked state with a model-waking aside.

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
- **Manifestation**: Legacy direct prompt injection put bash commands, regexes like `{{.*?}}`, or multiline file paths into a shell-quoted prompt. The outer shell parsed unescaped syntax and failed before delivery:
  `error: command not found: .github/workflows/gitleaks.yml`, `error: command not found: [extend]`.
- **Root Cause**: Shell expansion inside nested double-quoted strings.
- **Hard Guard**:
  > **External File Contract**: Keep the seven-section task in an external file and pass that file through the unified dispatch bus. Do not re-encode task contents into a raw shell prompt.

### Bug 4: Silent Handoff Overwriting (时间戳精度丢失)
- **Manifestation**: Using date format `$(date +%Y%m%d)`. When Writer runs at 10:00, Skeptic runs at 10:15, and Writer fixes at 10:30, all three write to `repo-name-handoff-20260930.md`, overwriting each other and destroying evidence.
- **Hard Guard**:
  > **Mandatory Precision**: All Handoff filenames MUST use `$(date +%Y%m%d_%H%M%S)`.

### Bug 5: Sub-Worker Exit Amnesia (退出未检乱发乱等)
- **Manifestation**: An interactive agent exits (e.g. OpenCode exits after writing DONE), but the orchestrator still targets the stale pane, leading to stalled input or leakage into the raw shell.
- **Hard Guard**:
  > **State Verification**: Before any supervised action, verify the Herdr lifecycle state. If the agent is absent or terminal, do not send input; preserve the lane evidence and surface the recovery path.

### Bug 6: Misrouted Notify Target (汇报目标地址错乱 / 占位符泄露)
- **Manifestation**: Child completion targets an unbound or guessed parent pane. The notification either fails or reaches the wrong session.
- **Root Cause**: The orchestrator failed to dynamically inspect and bind its own `pane_id` before constructing the child prompt.
- **Hard Guard**:
  > **Invariant**: Resolve `ORCH_PANE="$(herdr pane current | jq -r '.result.pane.pane_id')"` before dispatch and bind it into the dispatch identity. Completion must use `dispatch_plugin.py notify --target "$ORCH_PANE" --send` with the matching run/dispatch IDs, never a guessed placeholder.
