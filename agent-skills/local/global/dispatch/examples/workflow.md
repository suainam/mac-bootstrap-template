# Dispatch Examples

## Example 1: Full Two-Step Dispatch with Worktree & Quota Routing

### Scenario
User requests: "Implement JWT authentication in `src/auth/` and verify unit tests."

### Orchestrator Actions
1. **Routing Judgment**: Task is "代码实现 (Implementation)" $\rightarrow$ Select `codex` with `gpt-6-luna xhigh`.
2. **Execute Two-Step Dispatch**:
   ```bash
   PANE=$(herdr worktree create --cwd "$PWD" --branch feat/jwt-auth --label jwt-auth --no-focus | jq -r '.result.root_pane.pane_id')
   herdr agent start jwt-auth --kind codex --pane "$PANE" -- -m gpt-6-luna -c model_reasoning_effort="xhigh"
   # Verify composer ready
   sleep 2
   VISIBLE=$(herdr pane read "$PANE" --source visible)
   if echo "$VISIBLE" | grep -qE "trust|Trust|Accessing workspace"; then
     herdr pane send-keys "$PANE" enter
     sleep 1
   fi
   # Inject prompt with standardized notify-back + handoff
   herdr agent prompt jwt-auth "Read .dispatch/TASK.md and implement JWT auth. When done, write .dispatch/DONE plus ~/Documents/handoffs/myrepo-jwt-auth-handoff-$(date +%Y%m%d).md, then run: herdr agent prompt w3:p9H '\n[NOTIFY] [${PANE}_codex_myrepo] JWT auth implemented, tests pass | Handoff: ~/Documents/handoffs/myrepo-jwt-auth-handoff-20260930.md'"
   ```
3. **Fire-and-Yield**: Orchestrator immediately yields control back to user.

---

## Example 2: Quick Read-Only Query (Zero TUI Overhead)

### Scenario
User requests: "Check if Redis port is listening on cc15."

### Orchestrator Actions
1. **Routing Judgment**: Task is "只读查询 (Read-Only Query)" $\rightarrow$ Select `opencode` Print Mode (`--auto`).
2. **Execute Single-Shot**:
   ```bash
   opencode run --auto "Run ssh cc15 'ss -tlpn | grep 6379' and report the listening process."
   ```
3. **Report**: Output returned directly to orchestrator in milliseconds without creating git worktrees.

---

## Example 3: Full PR & Closeout Lifecycle

### Scenario
Child agent finishes work and reports: `\n[NOTIFY] [w3:pAY_opencode_myrepo] JWT auth implemented, tests pass | Handoff: ~/Documents/handoffs/myrepo-jwt-auth-handoff-20260930.md`

### Orchestrator Actions (Human Gate Approved)
1. **Verification**: Re-run tests in `.worktrees/jwt-auth`.
2. **Push & PR**:
   ```bash
   cd .worktrees/jwt-auth
   git push -u origin feat/jwt-auth
   gh pr create --title "feat(auth): implement JWT authentication" --body "..."
   gh pr merge --squash --delete-branch
   ```
3. **Sync & Closeout**:
   ```bash
   cd ../..
   git checkout main && git pull origin main
   git worktree remove .worktrees/jwt-auth
   git branch -d feat/jwt-auth
   ```
