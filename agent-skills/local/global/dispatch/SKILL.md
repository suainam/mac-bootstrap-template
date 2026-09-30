---
name: dispatch
description: Dispatch tasks to heterogeneous agents (Codex, OpenCode, Claude Code, Antigravity, OMP) running in Herdr-managed isolated worktrees. Features task-based model routing, quota failover, two-step trust handshake, zero-token watchdog supervision, and fire-and-yield handoff. Use when dispatching implementation, refactoring, review, PR release, or audit tasks to background agents.
argument-hint: '--task <file> [--role <writer|skeptic|researcher>] [--kind <codex|opencode|claude|agy|omp>] [--model <model>] [--name <name>] [--base <ref>] [--auto] [--cwd <path>]'
---

# Unified Agent Dispatch & Orchestration Engine

You are the **Orchestrator**. You split work into isolated lanes, select the best agent kind and reasoning effort, dispatch via Herdr, supervise with a zero-token watchdog, and yield immediately to keep the conversation interactive.

---

## Quick Reference Navigation

- **Diamond Orchestration Integration**: [references/diamond.md](references/diamond.md)
- **Orchestrator Antipatterns & Failure Modes**: [references/antipatterns.md](references/antipatterns.md)
- **Orchestrator Session Memory & Anti-Amnesia**: [references/orchestrator-memory.md](references/orchestrator-memory.md)
- **Sub-Worker Telemetry & 12-Factor Rules**: [references/observability.md](references/observability.md)
- **Task-to-Model Routing & Quota Failover**: [references/routing.md](references/routing.md)
- **Two-Step Handshake & Notify-Back Signature**: [references/protocol.md](references/protocol.md)
- **Zero-Token Watchdog & Polling Principles**: [references/supervision.md](references/supervision.md)
- **Workflow Scenarios & Production Cases**: [examples/workflow.md](examples/workflow.md)
## 0. Diamond Architecture Governance & Anti-Amnesia Redlines

Diamond (defined in `mac-bootstrap/AGENTS.md`) is the upper-level governance topology; Dispatch is the execution transport.

### Orchestrator Anti-Amnesia & Delegation Separation Redlines (Mandatory)
The Orchestrator must NEVER suffer from contextual amnesia or micromanagement degradation:
1. **Anti-Micromanagement (No Pseudo-Delegation)**:
   - The Orchestrator sets the **Outcome, Boundaries, and Verification Criteria (WHAT & ACCEPTANCE)**, NEVER the line-by-line patch code or exact keystroke steps (HOW).
   - If the Orchestrator writes the exact diff/code inside the prompt and treats the child worker as a mindless typist, **delegation is broken**. Either let the child worker inspect and implement autonomously, or do it directly if human approval authorizes single-agent execution.
2. **Trust Prior Discoveries**: Once a child agent (or previous step) extracts facts, paths, or root causes, the orchestrator MUST record and trust them in `.dispatch/ORCHESTRATOR_STATE.json`.
3. **Zero Redundant Exploration**: NEVER run `git status`, `herdr pane list`, `command -v ...`, `grep`, or read makefiles/catalogs to re-discover things already known!
4. **Anti-Worktakeover**: When a child agent finishes, NEVER redo its investigation by reading the codebase yourself. Read the child's output directly (`herdr pane read <pane> --source recent-unwrapped --lines 120`).
5. **Direct Task Handoff**: When delegating the next phase, issue a concrete outcome prompt directly targeting the verified files/lines. Do NOT perform a multi-round re-audit of the entire repository.
### Role Boundaries:
1. **Planner (Top Apex)**: Orchestrator + User formulate the plan, establish acceptance criteria, and enforce Occam Gate. Divergence begins only after human approval.
2. **Researcher (Divergence - Probe)**: Fast read-only inquiries. **Never create a git worktree**. Run via non-interactive print mode (`opencode run --auto` / `agy -p`) directly to stdout.
3. **Writer (Divergence - Implement & Ops)**: Implementation and ops lanes. Created via `herdr worktree create` (1 file, 1 writer, isolated branch).
   - **Worktree 隔离红线（最高优先级铁律）**：严禁将 Ops 运维、Secret 配置或临时排查任务误判为“不改源码”而在主工作区裸跑！只要是持续交互式 Agent，必须一律强制进入独立 Worktree！
4. **Skeptic (Convergence - Review)**: Independent adversarial review. **MUST use a fresh, independent pane/context** (never reuse the Writer pane). Re-runs tests, hunts assertion gaps, and reconciles documentation (`curate-repo-knowledge`).
5. **Cross-Agent Dynamic Coordination**: Orchestrator dynamically routes context across lanes (e.g. passing discovered nodes from Lane A to Lane B), and diagnoses cross-cutting blocks (e.g. clearing stale environment flags like `CHECKIN_PROXY_URL`).
6. **Proxy Defensive Sanitization**: Stale/unroutable proxy env vars cause `gh` / git network timeouts. Sanitize via `env -u http_proxy -u https_proxy -u all_proxy <cmd>` on network operations.
7. **Human Gate (Bottom Apex - Deploy)**: Orchestrator summarizes findings and presents high-risk actions (`git push`, PR merge, cleanup) to the human user for final authorization.
---

## 1. Task-to-Model Routing Matrix

When `--kind` is omitted, classify the task and assign the optimal worker kind:

| Task Class | Preferred Agent | Default Model | Reasoning Effort / Flags | Quota Fallback Chain |
| :--- | :--- | :--- | :--- | :--- |
| **代码实现 (Implementation)** | **Codex** | `gpt-6-luna` | `-c model_reasoning_effort="xhigh"` (or `"max"`) | Codex 5h 0% $\rightarrow$ **Agy** (`gemini-3.8-flash-medium`) $\rightarrow$ **OpenCode** |
| **代码重构 (Refactoring)** | **Codex** 或 **Claude** | `gpt-6-sol` / `claude-sonnet-5` | Codex: `low` effort; Claude: `--dangerously-skip-permissions` | Claude 额度不足 $\rightarrow$ **Codex** (`gpt-6-sol`) $\rightarrow$ **Agy** |
| **代码审查与前端 (Review/Frontend)** | **Agy** | `gemini-3.8-flash-medium` | `--effort medium`, `verbosity: "low"` | Agy $\rightarrow$ **Claude** $\rightarrow$ **OpenCode** |
| **轻量查询/PR/审计 (Lightweight/PR)** | **OpenCode** (免费池) | Free Pool | `--auto` (或单次直出 `opencode run --auto`) | OpenCode $\rightarrow$ **Agy** (`-p`) |

Quota detection patterns: Codex prints `You’ve hit your usage limit` / `5h 0% left`; Claude prints `credit balance is too low`. When seen, switch agent kind immediately.

---

## 2. Phase 1: Goal Contract Design (Pre-flight Gate)

Before any dispatch or script execution, the Orchestrator MUST formulate a structured Goal Contract adhering to `/skill:qiaomu-goal-meta-skill`.

### Redline: Goal Contract Completeness
Never dispatch a free-form or single-line prompt to an agent. The task definition must explicitly state:
1. **目标 (Outcome)**: Concrete end state, not activity or intent.
2. **验证 (Verification)**: Exact project commands and test assertions required to prove correctness.
3. **约束 (Constraints)**: Sensitive credential redaction, defensive proxy flags (`env -u http_proxy -u https_proxy -u all_proxy`), protected branches.
4. **写入边界 (Boundaries)**: Permitted directories and files vs. forbidden project areas.
5. **迭代策略 (Iteration Policy)**: Focus on one step at a time; rerun checks after changes; stop after 3 identical failures.
6. **完成条件 (Stop when)**: Observable evidence satisfying every acceptance criterion.
7. **暂停条件 (Pause if)**: External secrets, production mutation, ambiguous ownership, or severe merge conflicts.

**MANDATORY Execution Gate**:
Before creating worktrees or launching agents, the task specification file MUST pass linting:
```bash
python3 <skill-dir>/scripts/dispatch.py lint "$TASK_FILE" || exit 1
```
*(Linting mechanically asserts that all 7 sections contain non-trivial content and rejects any raw diff/patch blocks)*

Before spawning any agent, consult and advance the state machine:
```bash
# Check next permitted action:
python3 <skill-dir>/scripts/dispatch.py state next --repo "$PWD"
# Advance state to target phase (will enforce Review Convergence Ceiling):
python3 <skill-dir>/scripts/dispatch.py state advance --to-phase <writer_implementation|skeptic_review|awaiting_human_gate> --repo "$PWD"
```

---

## 3. Phase 2: Herdr Panel Topology & Dispatch Protocol (/skill:herdr)

Strictly follow `/skill:herdr` to create the target panel and launch the agent. Never guess CLI flags.

### 1. Panel & Layout Provisioning
- **Writer / Skeptic (Mandatory Worktree Isolation)**:
  ```bash
  CREATE_RES=$(herdr worktree create --cwd <repo> --branch <branch> --label <name> --no-focus)
  PANE=$(echo "$CREATE_RES" | jq -r '.result.root_pane.pane_id')
  ```
- **Interactive Sibling Pane (Same-Directory Inspection)**:
  ```bash
  SPLIT_RES=$(herdr pane split --current --direction right --cwd "$PWD" --no-focus)
  PANE=$(echo "$SPLIT_RES" | jq -r '.result.pane.pane_id')
  ```

### 2. Strict Agent Interactive Startup
Start the interactive agent CLI inside the pane. Pass only flags supported by the bare agent executable:
- **OpenCode**: `herdr agent start <name> --kind opencode --pane "$PANE" --timeout 60000 -- --auto`
  *(Crucial: bare `opencode` starts the interactive TUI. It does NOT take `-m` or `--model`; models are managed inside the TUI or configured via OpenCode config/plugins. Passing `-m` here causes immediate exit 1).*
- **Claude Code**: `herdr agent start <name> --kind claude --pane "$PANE" --timeout 60000 -- --model <model> [--dangerously-skip-permissions]`
- **Antigravity (Agy)**: `herdr agent start <name> --kind agy --pane "$PANE" --timeout 60000 -- --model <model> [--dangerously-skip-permissions]`
- **Codex**: `herdr agent start <name> --kind codex --pane "$PANE" --timeout 60000 -- -m <model>`
### 3. Inspect-on-Failure & Two-Step Handshake Gate
1. If `agent start` fails or times out:
   **MANDATORY**: Inspect the screen immediately:
   ```bash
   herdr pane read "$PANE" --source visible
   ```
   Diagnose the exact stderr or crash before retrying. Never retry blindly.
2. If trust modal appears (`Accessing workspace...`), confirm:
   ```bash
   herdr pane send-keys "$PANE" enter
   ```
3. Verify the active composer prompt is visible (`>`, `›`, `❯`, `Ask anything...`).

### 4. Prompt Injection & Protocol Enforcement
When injecting prompt into the child agent, the orchestrator MUST mandate the completion and notification protocol:
```bash
herdr agent prompt <name> "Read .dispatch/TASK.md (or specified contract). When finished, write findings to ~/Documents/handoffs/<name>-handoff.md, then run:
herdr agent prompt <orch_pane_id> '\n[NOTIFY] [<pane_id>_<agent_kind>_<repo_slug>] <one-liner conclusion> | Handoff: ~/Documents/handoffs/<name>-handoff.md'"
```
*(Failure to instruct the child agent to notify back results in orphaned completions where the orchestrator must poll manually).*

---

## 4. Phase 3: Standardized Notify-Back + Result Harvest Protocol

Every child agent MUST write `.dispatch/DONE` and a standard Handoff file, then notify with the exact coordinate signature:

```bash
# Worker mandatory closeout (no secrets; redact):
mkdir -p ~/Documents/handoffs
# Handoff file: ~/Documents/handoffs/${REPO_SLUG}-${NAME}-handoff-$(date +%Y%m%d).md
# MUST contain: task summary, core conclusions (one-liner each), evidence
# (paths with line numbers / test commands + results), residual risks.
herdr agent prompt <orch-pane> "\n[NOTIFY] [<pane_id>_<agent_kind>_<repo_slug>] <one-liner core conclusion> | Handoff: ~/Documents/handoffs/${HANDOFF_FILENAME}"
```

### Orchestrator Result Harvest Redline:
When the child agent enters `idle` (or sends `[NOTIFY]`):
1. **DO NOT take over the child's work**: The orchestrator must NEVER re-read the entire codebase or redo the investigation that the child agent already performed!
2. **Read the Child's Direct Output**:
   ```bash
   # If handoff file exists:
   read ~/Documents/handoffs/<handoff-file>
   # Otherwise capture from pane directly:
   herdr pane read <pane_id> --source recent-unwrapped --lines 120
   ```
3. **Synthesize & Deliver**: Summarize the child's findings directly to the human user.

---

## 5. Phase 4: Supervision Architecture (Fire-and-Yield + Two-Tier Watchdog)

- **Fire-and-Yield**: Once dispatched, **yield control immediately** to the user. Never block the main session with loops or waiting.
- **L1 Event Interrupt**: Child agent completes turn $\rightarrow$ fires Herdr IPC notify-back $\rightarrow$ Orchestrator woken as a new event.
- **L2 Zero-Token Watchdog**:
  - Run `herdr agent get <name>` only when investigating suspected hangs (costs 0 LLM tokens).
  - If `agent_status == blocked`: resolve modal dialog.
  - If `agent_status == idle` and no notification: sweep and verify completion.
  - If `state_change_seq` unchanged $\ge$ 10 min: process deadlocked, interrupt via `send-keys esc esc`.

---

## 6. Lightweight Non-Interactive Print Mode (Researcher Only)

For read-only investigations, system checks, or code queries:
- **OpenCode**: `opencode run --auto "<query>"`
- **Antigravity**: `agy -p "<query>" --model gemini-3.8-flash-medium`
Directly outputs results to stdout without spawning git worktrees or interactive TUI sessions.

---

## 7. Phase 5: Publication & PR Lifecycle Gate

Default posture: **Strictly NO PUSH and NO PR without explicit human approval.**
Upon approval:
1. Verify tests pass in worktree.
2. Push branch: `git push -u origin <branch>`
3. Create PR: `gh pr create --base main --head <branch> ...`
4. Merge PR: `gh pr merge --squash --delete-branch`
5. Sync root: `git checkout main && git pull origin main`
6. Closeout cleanup: `git worktree remove <worktree>` and `git branch -d <branch>`.
