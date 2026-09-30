# Orchestrator Session Memory & Lifecycle State Machine

This reference governs how the **Orchestrator** maintains continuous memory across turns and avoids the **Amnesia Anti-Pattern** (re-exploring known facts, scanning existing panes from scratch, or re-reading repo rules after every user prompt).

---

## 1. The Amnesia Anti-Pattern & Root Cause

### What Amnesia Looks Like:
1. User gives instructions or advances the task $\rightarrow$ Orchestrator forgets all previous discoveries.
2. Runs `git status`, `herdr pane list`, `command -v ...`, `makefiles/bootstrap.mk` all over again.
3. Re-discovers that an agent was already running or that a worktree already existed.
4. Burns 20,000+ tokens and 5+ minutes on zero-progress re-exploration.

### Root Cause:
The Orchestrator treats each turn as a blank-slate task instead of maintaining a **Persistent Orchestration Ledger** (`.dispatch/ORCHESTRATOR_STATE.json`).

---

## 2. Persistent Orchestration Ledger Contract

The Orchestrator MUST persist its operational state inside `.dispatch/ORCHESTRATOR_STATE.json` at the repo root (or active session):

```json
{
  "task_id": "auroraops-pr115-fix",
  "phase": "writer_implementation",
  "active_panes": {
    "orchestrator": "w1R:p1",
    "writer_pane": "w1R:p2",
    "skeptic_pane": null
  },
  "discovered_facts": {
    "pr_number": 115,
    "pr_branch": "feat/add-gitleaks",
    "ci_failure_cause": "Missing permissions: { contents: read, pull-requests: read } in gitleaks.yml (403)",
    "gitleaks_toml_issue": "Missing [extend] useDefault = true and {{.*?}} allowlist is too broad",
    "working_models": {
      "opencode": "Muse Spark 1.3 Free (TUI via --auto, no -m flag)",
      "agy": "gemini-3.8-flash-medium",
      "codex": "gpt-6-luna"
    }
  },
  "worktrees": {
    "writer": "/Users/suai/work/projects/auroraops-control"
  },
  "completed_milestones": [
    "research_completed_by_opencode_w1R:p2",
    "findings_harvested_and_confirmed"
  ],
  "next_action": "instruct_opencode_in_w1R:p2_to_apply_fixes"
}
```

---

## 3. Orchestrator Cold-Start / Resumption Protocol

Before executing ANY exploratory tool call (`find`, `grep`, `herdr pane list`, `git branch`):

1. **Read Ledger First**:
   ```bash
   test -f .dispatch/ORCHESTRATOR_STATE.json && cat .dispatch/ORCHESTRATOR_STATE.json
   ```
2. **If Ledger Exists**:
   - **TRUST EXISTING FACTS**: Do NOT re-run `command -v gitleaks`, do NOT re-list `herdr worktree`, do NOT re-read `network_topology.yml`!
   - Directly target `.active_panes.writer_pane` or the next scheduled milestone.
3. **If Ledger Missing**:
   - Initialize ledger with current coordinates (`HERDR_PANE_ID`, target issue/PR, active worker).

---

## 4. Worktakeover vs Delegation Rules

| Role | Permitted Actions | Forbidden Actions |
| :--- | :--- | :--- |
| **Orchestrator** | 1. Formulate Goal Contract<br>2. Provision worktree & pane<br>3. Inject task prompt with notify-back<br>4. Supervise via `herdr agent get`<br>5. Harvest results & report to Human | 1. Editing source code files<br>2. Running build/test commands directly<br>3. Re-reading repo source files after child finishes<br>4. Re-exploring environment facts already discovered |
| **Worker (OpenCode/Codex)** | 1. Modifying target code in worktree<br>2. Running tests & syntax checks<br>3. Writing Handoff file & sending `[NOTIFY]` | 1. Mutating protected branches (`main`)<br>2. Merging PRs without orchestrator approval |

---

## 5. Decision Tree: Next-Step Handoff

```text
[Child Agent completes research (idle)]
           │
           ▼
[Orchestrator harvests output (0 new searches)]
           │
           ▼
[Human authorizes implementation]
           │
           ▼
[Orchestrator checks: Is existing pane reusable?]
   ├── YES (e.g. w1R:p2 already in clean repo/branch):
   │     ↳ Reuse pane directly! Send prompt to implement fixes.
   └── NO (requires fresh branch/worktree):
         ↳ herdr worktree create ──► start agent ──► prompt.
```
