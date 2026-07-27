# Agent Quality Gates 与 Linked Worktree

本文是公开模板中 Agent quality gate 的运行与验收权威。Issue/PR 记录具体变更历史；本文只保留可跨任务复用的机制、边界和检查顺序。

## 标准事件运行时骨架

Agent Runtime 的受信入口是 `scripts/agent-runtime.sh`，实现位于
`scripts/agent_runtime.py`，Git context resolver 位于
`scripts/agent_git_context.py`，默认 registry 位于
`agent/runtime/registry.jsonc`。Git、Claude Code 和后续编辑器 adapter 只负责把宿主
payload 转换为同一个版本化事件；Git context、gate 匹配、profile、timeout、失败策略
和输出预算由受信 runtime 处理。

仓库必须通过 local Git config 显式启用并选择 profile：

```bash
git config --local agent.runtime.enabled true
git config --local agent.runtime.profile generic
```

未启用仓库的 `dispatch` 快速成功且输出 0 字节。仓库只能选择 registry 中已有
profile，不能提交 shell 字符串、可执行 hook 或越界 cwd。registry 中的 gate command
必须是 argv 列表，首个可执行文件使用绝对路径；runtime 永不使用 `shell=True`。

标准事件从 stdin 传入 JSON，当前 schema version 为 `1`，至少包含：

```json
{
  "schema_version": 1,
  "event_type": "after.edit",
  "event_id": "evt-001",
  "source_adapter": "claude-code",
  "timestamp": "2026-07-27T00:00:00Z",
  "cwd": "/path/to/repository",
  "target_paths": ["scripts/example.py"],
  "session_id": "session-001",
  "metadata": {}
}
```

CLI 提供五个公开动作：

- `dispatch`：执行匹配 gate；成功和未启用路径输出 0 字节。
- `dry-run`：输出计划但不执行。
- `explain`：输出 effective profile、Git context、命中 gate 和跳过原因，不执行 gate。
- `explain-context`：不读取事件，只输出当前 Git context；可通过 `--session-id` 同时解释隔离后的运行状态路径。
- `doctor`：输出 registry、schema、Git context、仓库 opt-in 和预算状态。

独立 resolver 的 `resolve` 动作只校验 context，成功输出 0 字节；只有
`explain-context` 才序列化 context：

```bash
scripts/agent_git_context.py resolve --cwd /path/to/repo
scripts/agent-runtime.sh --cwd /path/to/repo --session-id session-001 explain-context
```

同步 gate 在当前进程中按声明顺序执行并受 timeout 限制；异步 gate 立即外置执行，
stdout/stderr 写入 registry 指定基目录下的 repository/worktree/session diagnostics，
不污染热路径。失败默认最多 5 条诊断、约 4 KB；完整日志外置。Git context 解析错误
携带稳定指纹；跨事件诊断 accumulator 的实际写入与去重仍由后续编辑反馈 ticket 完成。

当前 repo-managed `pre-commit` / `pre-push` 仍由旧 quality-gate runner 负责。只有
commit/push dispatcher ticket 完成真实迁移与回滚验收后，才能移除旧入口；骨架阶段
不得让两套 hook 竞争。

## Git context identity 与状态隔离

Git hook 在发起操作的仓库上下文中运行。父仓、submodule、linked worktree、main
checkout 和独立 clone 不能通过 cwd、安装目录或父目录形态推断。resolver 动态清理
Git local environment 后，由 Git 自身解析：

```bash
git rev-parse --show-toplevel
git rev-parse --absolute-git-dir
git rev-parse --path-format=absolute --git-common-dir
git rev-parse --show-superproject-working-tree
git rev-parse --is-bare-repository
git rev-parse --is-inside-work-tree
```

context schema version 为 `1`，稳定字段包括 repo root、absolute git dir、absolute git
common dir、superproject、bare/worktree 状态，以及两个 identity：

- `repository_id` 由 canonical git common dir 派生；同一 repository 的 main checkout 与 linked worktree 共享。
- `worktree_id` 由 canonical absolute git dir 派生；不同 linked worktree 必须不同。
- `git dir != git common dir` 表示 linked worktree。
- `--show-superproject-working-tree` 非空表示 submodule checkout；resolver 同时验证 superproject 是真实 Git top-level 且包含当前工作树。
- bare repository 的 `repo_root` 为 `null`，但 git dir、common dir 和 identity 仍可解释；已 opt-in 的事件 dispatch 不允许从 bare repository 执行。

仓库 opt-in 与 profile 固定从 `<git-common-dir>/config` 读取，不从 worktree-specific git
dir 或 cwd 猜测。运行状态路径固定为：

```text
<state-root>/repositories/<repository-id>/worktrees/<worktree-id>/sessions/<session-id+hash>/
```

该目录下分别定义 changed-file ledger、lock、cache、diagnostics、accumulator 和 receipts。
即使 session ID 相同，两个 worktree 也不会共享这些路径。main checkout 才负责验证用户级
symlink、LaunchAgent、已安装应用等机器状态。

## 检查分层

质量门禁分为两个层级：

| Target | 职责 | 适用位置 |
|---|---|---|
| `make repo-check` | 语法、隐私、skill、非 `machine` 测试 | main checkout、linked worktree、submodule |
| `make machine-check` | strict doctor 与 `machine` 标记测试 | 真实管理 checkout |
| `make check` | `repo-check + machine-check` | 真实管理 checkout 的完整发布验证 |

linked worktree 或 submodule 的 pre-push 只运行 repository checks。临时 worktree 不应接管或重写真实机器上的 managed symlink，也不应因它们仍指向管理 checkout 而失败。

## 跨仓执行

父仓进入子仓执行命令前，必须调用 `git rev-parse --local-env-vars`，根据 Git 当前
版本返回的变量名动态清理环境；不要只硬编码 `GIT_DIR` 和 `GIT_WORK_TREE`。resolver
和 gate 执行统一复用 `clean_git_local_environment` / `run_in_repository` helper，清理后
再以目标仓库目录作为 `cwd` 解析 context 或执行命令。父仓注入完整 local environment
时，子仓的 `git ls-files`、diff、index 和 object lookup 仍必须读取子仓自身状态。

清理失败、目标 `repository_id` / `worktree_id` 与调用方预期 scope 不一致时拒绝执行，
不得静默回退到 cwd 猜测。

## Context 失败语义

resolver 对外返回稳定错误 code 和 `ctxerr-<hash>` 指纹：

| Code | 含义 |
|---|---|
| `not-a-repository` | 路径不是 Git repository；由事件入口决定 silent no-op 或 block |
| `broken-worktree` | `.git` gitfile 无效或 worktree git dir 丢失 |
| `missing-common-dir` | linked worktree 的 commondir 无效、为空或目标丢失 |
| `inconsistent-superproject` | Git 报告的 superproject 与真实 top-level/工作树关系冲突 |
| `context-conflict` | 实际 repository/worktree identity 与调用方预期 scope 不一致 |
| `environment-cleanup-failed` | 无法动态取得或验证 Git local environment 变量清单 |

已 opt-in repository 发生 context 解析错误时，runtime fail closed。内部 `resolve` 成功
保持 0 字节；显式 `explain-context` 才输出结构化 JSON。

## Python 与测试运行时

linked worktree 通常没有独立 `.venv`。允许通过 `PYTHON` 复用真实 checkout 的解释器，但需要遵守两条边界：

1. 使用指定解释器启动 pytest。
2. pytest 启动后，从测试子进程环境移除 `PYTHON` 和 `PYTHON_BIN`。

第二条可以避免外部解释器覆盖污染测试自己构造的 fake runtime。测试 helper 应使用当前 pytest 进程的 `sys.executable`，而不是重新拼接当前 checkout 的 `.venv/bin/python`。

## 最小验收顺序

不要只依赖 mock 或 dry-run。按以下顺序验证：

1. **聚焦集成测试**：临时创建真实父仓、submodule 和 linked worktree，注入父仓 Git 环境，证明子仓仍读取自己的 tracked files。
2. **Repository checks**：使用外部 `PYTHON` 运行完整 `make repo-check`，确认 worktree 无本地 venv 也可完成非机器检查。
3. **真实本地 push**：创建临时 bare remote，从 linked worktree 执行真实 `git push`；不得使用 bypass 或 `--no-verify`。
4. **远端 CI**：子仓 Public CI 通过后合并。
5. **管理 checkout push**：父仓 main checkout 真实 push，确认 repository checks、machine checks、doctor 和 post-success 记录全部完成。

真实 push 验收必须同时证明：

- hook 确实被触发；
- linked worktree 只运行 repository checks；
- 子仓 index 未被父仓环境污染；
- 远端 ref 实际更新；
- bypass 未启用。

## 经验与教训

### 先跑真实验收，再提交最终 PR

临时 Git 仓库测试能验证核心上下文，但不能覆盖真实项目中 venv、test helper、文档门禁和 post-success side effect。最终 PR 前应先完成一次真实 linked-worktree push，避免用多个 follow-up PR 修补同一闭环。

### 每个 operational PR 都要携带当前文档变更

`neat-freak` 按当前 PR diff 判断。即使上一张 PR 已更新文档，下一张修改 Makefile、hook 或 runtime contract 的 follow-up PR 仍需在同一 PR 中同步对应权威说明。

### 父仓 pointer 必须引用远端可达的子仓提交

父仓 worktree 初始化 submodule 前，目标子仓 commit 必须已经 push 到可访问 remote。仅存在于本地 object database 的 commit 不能作为可复现验收输入。

### 解释器覆盖不能变成全局运行时覆盖

`PYTHON` 的作用是选择入口解释器，不应成为被测系统的隐式全局配置。启动 pytest 后清理覆盖变量，能同时满足 worktree 复用 venv和测试隔离。

### 验收不用 bypass

`QUALITY_GATES_BYPASS=1` 和 `--no-verify` 只适用于明确记录的紧急绕过，不是验收手段。修复 quality gate 时必须证明未绕过路径能够成功。

### 注意 post-success 的运行时写入

真实 pre-push 成功后可能写入知识记录或其他运行时状态。验收与 closeout 时应识别并保留这些预期脏改动，不要误纳入提交或误删。

## 复用检查表

- [ ] Git 上下文由 `git rev-parse` 解析，而非目录猜测。
- [ ] 跨仓命令动态清理 Git local environment variables。
- [ ] linked worktree 和 submodule 只跑 `repo-check`。
- [ ] 管理 checkout 跑 `make check`，包括 machine checks。
- [ ] pytest 可复用外部解释器，但子进程不继承 `PYTHON/PYTHON_BIN`。
- [ ] test helper 使用 `sys.executable`。
- [ ] 子仓 commit 在父仓 pointer 验收前已远端可达。
- [ ] 每张 operational PR 都包含当前公共文档同步。
- [ ] 至少完成一次无 bypass 的真实 linked-worktree push。
- [ ] 父子仓按 child-first、pointer-second 发布并完成 closeout。

## 参考证据

- Template Issue [#28](https://github.com/suainam/mac-bootstrap-template/issues/28)
- Template PRs [#46](https://github.com/suainam/mac-bootstrap-template/pull/46)、[#47](https://github.com/suainam/mac-bootstrap-template/pull/47)、[#48](https://github.com/suainam/mac-bootstrap-template/pull/48)、[#49](https://github.com/suainam/mac-bootstrap-template/pull/49)、[#50](https://github.com/suainam/mac-bootstrap-template/pull/50)
- Parent PR [#20](https://github.com/suainam/mac-bootstrap/pull/20)
- Hook policy：`agent/quality-gates/manifest.jsonc`
- Runner：`scripts/agent_quality_gate.py`
- Lifecycle：`docs/agents/issue-tracker.md`
