---
name: dispatch
description: Dispatch tasks to heterogeneous agents (Codex, OpenCode, Claude Code, Antigravity, OMP) running in Herdr-managed isolated worktrees. Features task-based model routing, quota failover, two-step trust handshake, zero-token watchdog supervision, and fire-and-yield handoff. Use when dispatching implementation, refactoring, review, PR release, or audit tasks to background agents.
argument-hint: '<task-description> [--kind <codex|opencode|claude|agy|omp>] [--model <model>] [--print] [--auto] [--push] [--base <ref>]'
---

# Unified Agent Dispatch & Orchestration Engine

You are the **Orchestrator**. You split work into isolated lanes, select the best agent kind and reasoning effort, dispatch via Herdr, supervise with a zero-token watchdog, and yield immediately to keep the conversation interactive.

---

## Quick Reference Navigation

- **Diamond Orchestration Integration**: [references/diamond.md](references/diamond.md)
- **Sub-Worker Telemetry & 12-Factor Rules**: [references/observability.md](references/observability.md)
- **Task-to-Model Routing & Quota Failover**: [references/routing.md](references/routing.md)
- **Two-Step Handshake & Notify-Back Signature**: [references/protocol.md](references/protocol.md)
- **Zero-Token Watchdog & Polling Principles**: [references/supervision.md](references/supervision.md)
- **Workflow Scenarios & Lifecycle Examples**: [examples/workflow.md](examples/workflow.md)

---

## 0. Diamond Architecture Governance & Real-World Hard Rules

Diamond (defined in `mac-bootstrap/AGENTS.md`) is the upper-level governance topology; Dispatch is the execution transport:

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

**Completion criterion**: A compliant task specification exists in `.dispatch/TASK.md` or a structured argument.

---

## 3. Phase 2: Dispatch Protocol (Two-Step Handshake)

Never pump prompts into a fresh agent pane immediately; pre-flight trust dialogs will swallow the text.

1. **Step 1 (Start & Trust Resolution)**:
   - Create worktree: `PANE=$(herdr worktree create --cwd <repo> --branch <branch> --label <name> --no-focus | jq -r '.result.root_pane.pane_id')`
   - Start agent: `herdr agent start <name> --kind <kind> --pane "$PANE" -- <args>`
   - Inspect screen: `herdr pane read "$PANE" --source visible`
   - If a trust dialog appears (`Accessing workspace...`), confirm: `herdr pane send-keys "$PANE" enter`
   - Verify that the active composer prompt (`>`, `›`, `Ask anything...`) is visible.
2. **Step 2 (Prompt Injection)**:
   - Inject the task prompt only when the composer is active and ready:
     `herdr agent prompt <name> "Read .dispatch/TASK.md and execute..."`

*Implementation Detail*: Automated dispatch helper `scripts/herdr-dispatch.sh` encodes this protocol and validates the Phase 1 Goal Contract before executing.

---

## 4. Phase 3: Standardized Notify-Back + Handoff Signature

Every child agent MUST write `.dispatch/DONE` and a standard Handoff file, then notify with the exact coordinate signature:

```bash
# Worker mandatory closeout (no secrets; redact):
mkdir -p ~/Documents/handoffs
# Handoff file: ~/Documents/handoffs/${REPO_SLUG}-${NAME}-handoff-$(date +%Y%m%d).md
# MUST contain: task summary, core conclusions (one-liner each), evidence
# (paths with line numbers / test commands + results), residual risks.
herdr agent prompt <orch-pane> "\n[NOTIFY] [<pane_id>_<agent_kind>_<repo_slug>] <one-liner core conclusion> | Handoff: ~/Documents/handoffs/${HANDOFF_FILENAME}"
```

Example: `\n[NOTIFY] [w3:pAY_opencode_auroraops-control] JWT auth implemented, tests pass | Handoff: ~/Documents/handoffs/auroraops-control-jwt-auth-handoff-20260930.md`

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
