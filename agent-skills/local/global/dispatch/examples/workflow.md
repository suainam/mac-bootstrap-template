# Golden Dispatch Workflows & Complete Real-World Cases

This reference provides end-to-end executable blueprints tested in production environments.

---

## Golden Case 1: Complex Multi-Step Task Dispatched to Interactive OpenCode Panel

### 1. Context & Task Formulation (Phase 1)
User requests: "Investigate GitHub Issue #120 and PR #125, audit code evidence, and formulate solutions without mutating repository files."

First, formulate a structured 7-section task specification via `/skill:qiaomu-goal-meta-skill` and write it to `/tmp/investigate_goal_task.md`:
```markdown
# 目标 (Outcome)
只读分析 GitHub Issue #11 与 PR #115，分别产出基于当前仓库与 issue/PR 记录的证据化解决方案。

# 验证 (Verification)
检查仓库 Profile、网络拓扑、Gitleaks 配置与 CI 入口，引用文件路径和行号；提出可复现的安全验证命令。

# 约束与脱敏 (Constraints & Security)
严格只读，不得修改代码、提交或推送；密钥必须脱敏；代理超时防御性使用 env -u http_proxy -u https_proxy -u all_proxy。

# 写入边界 (Boundaries)
仅允许读取当前仓库与相关文档，严禁写入代码文件。

# 迭代策略 (Iteration Policy)
先核实仓库事实与 PR 现状，证据不足最多补查 3 轮，同工具连续失败 2 次必须先读日志排查。

# 完成条件 (Stop when)
两项问题均有结构化结论、精准验证命令与预期输出，全部结论均有行号证据支撑。

# 暂停条件 (Pause if)
遇到需要生产变更、未知私有凭据或破坏性操作时立即暂停。
```

### 2. Read-only Research Dispatch
```bash
# Researcher mode is the supported zero-worktree path. The wrapper applies the
# shared role routing matrix and executes non-interactively; no raw Herdr prompt
# injection is part of the formal protocol.
agent-skills/local/global/dispatch/scripts/herdr-dispatch.sh \
  --task /tmp/investigate_goal_task.md \
  --role researcher
```

### 3. Monitoring, Recovery & Handoff
- Check live agent status at zero LLM cost: `herdr agent get issue-pr-solution`
- Read live reasoning stream: `herdr pane read "$PANE_ID" --source visible`
- When OpenCode finishes, retrieve markdown findings and notify orchestrator.

---

## Golden Case 2: Implementation Worktree Dispatched to Codex (luna / sol)

### 1. Goal Contract
When performing real code edits, worktree isolation is mandatory and is created by the dispatch wrapper. Prepare the seven-section contract outside the target worktree:
```bash
cat <<'EOF' > /tmp/jwt-auth-task.md
# 目标 (Outcome)
实现 JWT 鉴权模块并替换旧有的 Session 验证。
# 验证 (Verification)
pytest tests/test_auth.py 全部通过。
# 约束 (Constraints)
不改动数据库已有密码散列结构；保持现有接口入参格式向后兼容。
# 写入边界 (Boundaries)
仅允许修改 src/auth/ 和 tests/test_auth.py。
# 迭代策略 (Iteration Policy)
一次实现一个接口，每步重跑 pytest。
# 完成条件 (Stop when)
测试全部通过，写出 .dispatch/DONE 与 Handoff 文件。
# 暂停条件 (Pause if)
需要外部 OAuth 凭据时暂停。
EOF
```

### 2. Dispatch Codex Through the Unified Bus
```bash
# The wrapper provisions the isolated worktree, resolves the trust handshake,
# applies the shared role routing matrix, and performs formal delivery through
# dispatch_plugin.py with a bound callback target. Explicit --kind/--model remain
# authoritative when supplied.
agent-skills/local/global/dispatch/scripts/herdr-dispatch.sh \
  --task /tmp/jwt-auth-task.md \
  --role writer \
  --name 1-1-jwt-auth \
  --branch feat/jwt-auth \
  --kind codex \
  --model gpt-6-luna \
  --cwd "$PWD"
```

---

## Golden Case 3: Zero-Worktree Fast Print Mode (Researcher Only)

Used strictly for read-only ad-hoc inspections where spawning a full TUI or worktree is wasteful:
```bash
# Via OpenCode (Free Pool)
opencode run --auto "Check if nginx service is active on cc15 via ssh and report status."

# Via Antigravity (Gemini 3.8 Flash)
agy -p "Find where wireguard UDP port 30071 is overridden in inventories/" --model gemini-3.8-flash-medium
```

---

## Golden Case 4: Parent-Child Submodule Publication & Closeout

1. **Child First**: Verify child tests (`make check-parallel`), commit with Conventional Commits, push child branch, create child PR, merge PR to child `main`.
2. **Parent Gitlink Update**: In `template/`, fast-forward `main` to remote `origin/main`. In parent, commit gitlink update and parent changes together.
3. **Parent Gate**: Run `make privacy-audit` and `make check`. Push parent branch, create parent PR, merge to parent `main`.
4. **Local Sync & Prune**: Fast-forward local `main` on both repos. Delete merged local and remote feature branches safely.
