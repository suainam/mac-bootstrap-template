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
不污染热路径。失败默认最多 5 条诊断、约 4 KB；完整日志外置。

## 编辑反馈漏斗

`after.edit` 与 `after.batch` 是两个不同阶段，不允许用同一条 gate 混合声明：

- `stage=edit` 只匹配 `after.edit`，用于单文件 formatter、parser 和轻量 lint；默认 failure policy 是 `diagnose`。
- `stage=batch` 只匹配 `after.batch`，用于 typecheck、focused tests、生成物一致性和跨文件机械检查。
- edit-stage 不允许 `notice` severity；非紧急提示必须延迟到 batch 聚合，避免每次编辑重复输出。
- `action=check` 被视为只读操作。runtime 在进程前后比较全部目标文件；若命令修改目标，立即恢复原内容并报告 `restore-unapproved-mutation`。
- `action=safe-fix` 只允许在 edit stage 使用，并必须同时声明 `safe-fix` capability、全 registry 唯一的 operation ID 和 2–5 次最大收敛轮数。

受信 registry 中的 safe-fix 形状如下；仓库只能选择包含它的 profile，不能自行提交命令：

```json
{
  "stage": "edit",
  "action": "safe-fix",
  "events": ["after.edit"],
  "command": ["/absolute/path/to/formatter"],
  "mode": "sync",
  "capabilities": ["safe-fix"],
  "rule_revision": "formatter-v1",
  "safe_fix": {
    "operation_id": "python-format",
    "max_rounds": 2
  }
}
```

safe-fix 执行前必须确认 diagnostics、receipts 和 worktree lock 目录可写；否则拒绝
自动修改。每个文件使用 worktree-scoped exclusive lock，不同 session 也不能并发修改
同一文件。runtime 保存原始 bytes，逐轮运行 formatter，直到 content hash 不再变化；
超过最大轮数、timeout、命令失败或状态写入失败时恢复原内容并停止。成功只留下 receipt，
记录 operation ID、规则版本、输入/输出 hash、轮数和目标文件；成功日志会删除。重复事件
若当前 hash 已等于同一 operation/规则的 receipt 输出 hash，直接 0 字节 no-op。adapter
可在事件 `metadata.safe_fix` 中携带 operation ID 与 depth，runtime 据此阻止递归执行。

每次 `after.edit` 完成后，runtime 将最终 target hash 合并到
`session + repository + worktree` scoped accumulator。`after.batch` 在制定 gate plan 前将
accumulator 与事件 target paths 合并，因此多个 Edit/Write 只触发一次跨文件检查；batch
完成后无论通过或阻塞都清空该批次。不同 linked worktree 的 accumulator、file lock、
diagnostics 和 receipts 路径不同。

诊断 schema 固定包含 `severity`、`action`、`message`、`evidence`、`log_ref`、
`content_hash`、`rule_revision` 和稳定 `fingerprint`。fingerprint 同时绑定规则版本与目标
内容：相同规则、相同内容、相同问题只注入一次；内容或规则变化后允许重新报告。失败的
完整 stdout/stderr 写入外置日志，成功、重复诊断和成功 safe-fix 均保持 stdout/stderr
0 字节。

## Claude Edit 曳光弹

`scripts/agent_claude_edit_adapter.py` 是第一个宿主 adapter，但不是 Claude 专用 runtime。
它只接受 Claude Code `PostToolUse` 的 `Edit|Write` payload，将 `session_id`、`cwd`、
`tool_input.file_path` 和 `tool_use_id` 转换为标准 `after.edit`；不读取
`transcript_path`，不复制 gate 规则，也不调用任何 LLM。非 `PostToolUse`、非
`Edit|Write`、非法 cwd 或仓库外路径会确定性拒绝。

第一枪使用 `claude-edit-smoke` profile，只包含一个 `python-syntax-smoke` gate。该 gate
通过 `/usr/bin/python3` 的 `compile()` 检查 Python 源码，不生成 `__pycache__`，不修改
目标文件，也不承担完整 lint/typecheck 职责。仓库 opt-in：

```bash
git config --local agent.runtime.enabled true
git config --local agent.runtime.profile claude-edit-smoke
```

adapter 的 `settings` 动作输出一份只含单个 `PostToolUse` matcher 的 JSON，可直接作为
Claude Code 的附加 settings；当前使用 command-string 形式以兼容已验证的 Claude Code
2.1.212，不提前建立多版本 adapter framework：

```bash
CLAUDE_SETTINGS="$(
  /absolute/python3 scripts/agent_claude_edit_adapter.py \
    --registry agent/runtime/registry.jsonc \
    settings --python /absolute/python3
)"

claude -p \
  --setting-sources user \
  --settings "$CLAUDE_SETTINGS" \
  --tools 'Write,Edit' \
  'Edit a Python file and fix any hook diagnostic.'
```

真实验收顺序固定为：Claude 先写入 Python 语法错误；adapter 将 runtime diagnostic 映射为
Claude `decision=block` 与有界 `reason`；Claude 修复同一文件；成功 hook 输出 0 字节；
随后同一临时仓库通过可信 Git dispatcher 完成真实 commit/push。首次试点已验证 Claude
返回 `TRACER_OK`、最终文件可编译、bare remote SHA 与本地 SHA 相同、dispatcher doctor
为 healthy，且全程未使用 bypass 或 `--no-verify`。

完整 lifecycle、`PostToolBatch`、Stop、SessionStart、永久 installer 和第二宿主 adapter
不属于第一枪。下一宿主只能新增自己的 payload 转换与结果映射，不能修改标准事件 schema、
runtime gate 或诊断核心；由此用真实复用证明通用性，而不是预先设计 plugin framework。

## OpenCode Edit 曳光弹

`scripts/agent_opencode_edit_adapter.py` 是第二个宿主 adapter。OpenCode 1.18.5 的项目插件
通过 `.opencode/plugins/` 自动加载，并在 `tool.execute.after(input, output)` 中提供
`tool`、`sessionID`、`callID`、`args`、`directory` 和可改写的 `output.output`。adapter
只处理 `write`、`edit` 和单文件 `apply_patch`：前两者读取 `args.filePath`，后者从
`args.patchText` 的 `*** Add File:` / `*** Update File:` 标记提取唯一目标；多文件 patch、
非法目录和仓库外路径确定性拒绝。

`plugin` 动作输出一个最小 JavaScript shim，可直接写入目标仓库的
`.opencode/plugins/agent-runtime.js`。shim 仅把真实 hook payload 送入 Python adapter；
runtime 成功时不修改原工具结果，失败时只把有界 `additionalContext` 前置到
`output.output`，让 OpenCode 在下一轮看到并修复问题：

```bash
mkdir -p .opencode/plugins
/absolute/python3 scripts/agent_opencode_edit_adapter.py \
  --registry agent/runtime/registry.jsonc \
  plugin --python /absolute/python3 \
  > .opencode/plugins/agent-runtime.js
```

第二枪继续复用原有 `claude-edit-smoke` profile 和 `python-syntax-smoke` gate；该 profile
名称是首枪留下的历史命名，不代表 runtime 或 gate 绑定 Claude。此次实现没有修改标准
事件 schema、`agent_runtime.py`、registry 或诊断核心。

真实验收中，OpenCode 先通过 `write` 写入 Python 语法错误，工具结果收到一次
`python-syntax-smoke` 诊断；OpenCode 随即修复同一文件并返回 `TRACER_OK`，成功路径没有
再次注入诊断。随后同一临时仓库通过可信 Git dispatcher 完成真实 commit/push，本地与
bare remote SHA 相同，dispatcher doctor 为 healthy，且未使用 quality-gate bypass 或
`--no-verify`。这证明宿主通用性来自两个薄 adapter 复用同一标准事件和 runtime，而不是
来自预先建立的 adapter framework。

完整 OpenCode lifecycle、session/batch 事件、全局插件安装器和通用插件加载框架仍不在
当前范围内。

## 可信 Git hook dispatcher

`scripts/agent_git_hook_dispatcher.py` 提供独立的 inventory、install、uninstall、doctor
和 hook dispatch 接口。它不会执行仓库提交的 hook 文件；install 将 dispatcher、runtime、
registry 和显式批准的 legacy/LFS hook 复制到用户级受信目录，再把 repository common
config 的 `core.hooksPath` 指向绝对的用户级 `current/hooks`。仓库仍只能通过 common
config 选择受信 profile，不能修改安装后的命令、approved chain 或 digest。

```bash
make quality-gate-hook-inventory GIT_HOOK_REPO=/path/to/repo
make quality-gate-hook-install \
  GIT_HOOK_REPO=/path/to/repo \
  GIT_HOOK_REGISTRY=/trusted/registry.jsonc \
  GIT_HOOK_PYTHON=/opt/homebrew/bin/python3
make quality-gate-hook-doctor GIT_HOOK_REPO=/path/to/repo
make quality-gate-hook-uninstall GIT_HOOK_REPO=/path/to/repo
```

安装前先运行 inventory。结果明确列出当前 resolved hooks directory、事件、可执行状态、
SHA-256 和分类：`repository-self-hook`、`git-lfs` 或 `legacy-hook`。unknown hook 默认不
执行；tracked repository self hook 即使通过 `--approve-hook` 指定也会被拒绝。需要保留
的 Git LFS 或 legacy hook 必须由用户显式批准，例如把以下参数放入
`GIT_HOOK_APPROVALS`：

```text
--approve-hook pre-push=/absolute/path/to/approved-hook
```

dispatcher bundle 还固定一个绝对的 Python 3.10+ 入口。该解释器必须位于目标 Git
worktree 之外；目标仓库自己的 `.venv`、仓库脚本或任意 repository-controlled 路径都会
在安装阶段被拒绝。默认 `GIT_HOOK_PYTHON` 使用 shell 中的 `python3`，安装后 doctor 会
持续检查其存在性和可执行位。

批准顺序就是执行顺序。installer 将每个 hook 复制到 repository-scoped 受信状态区并
固定 digest；运行前再次验证文件存在、可执行位和 digest。所有 approved hook 获得原始
hook argv；pre-push stdin 先完整缓存，再向 runtime 和每个 approved hook 重放相同 bytes。
unknown hook、tracked self hook 和未批准 LFS hook 永远不会被隐式链接或执行。

dispatcher 当前映射以下标准事件：

| Git hook | Standard event | 失败语义 |
|---|---|---|
| `pre-commit` | `before.commit` | blocking |
| `commit-msg` | `before.commit-message` | blocking |
| `post-commit` | `after.commit` | diagnostic only |
| `post-checkout` | `after.checkout` | diagnostic only |
| `post-merge` | `after.merge` | diagnostic only |
| `post-rewrite` | `after.rewrite` | diagnostic only |
| `pre-push` | `before.push` | blocking |

`before.commit` 与 `before.commit-message` 的 target paths 来自 Git index。dispatcher 将
staged blobs 物化到 event-scoped、mode 0600 的 snapshot 目录，并在 metadata 中提供
staged tree、blob OID、mode 和 snapshot path；gate 不应把 unstaged working tree 当成
提交内容。blocking gate 运行前后还会比较 index tree 与完整 worktree fingerprint；任何
自动改写都会阻塞提交，要求用户检查并重新 stage。blocking Git 生命周期 gate 必须同步
运行，async 配置在 registry 校验阶段直接拒绝。

`before.push` 只使用 Git 传入的 pre-push stdin 计算范围，不猜 upstream。首次 push、
无 upstream、多 ref push、删除和 force update 都按每条 local/remote OID 解析。新建远端
ref 的 `remote_oid` 为零，因此 dispatcher 保守地使用空树作为旧端；即使该分支来自已有
remote main，target paths 也可能覆盖完整提交树。这避免依赖可能陈旧的 remote-tracking
refs 而漏检。标准事件最多接受 4096 个 target paths；超限时 fail closed。该预算足以覆盖
当前约 931 个 tracked paths 的 template 首次分支 push，同时仍限制异常大事件。
metadata 保留 refs、remote name/URL、force classification 和缓存文件路径。多个 runtime
gate 与 approved hook 会全部执行，失败按声明/批准顺序聚合；非 1 legacy exit code 保留为
最终 exit code，完整 stdout/stderr 外置，终端仍受最多 5 条、约 4 KB 预算约束。成功输出
0 字节。

blocking hook 支持 break-glass：

```bash
QUALITY_GATES_BYPASS=1 \
QUALITY_GATES_BYPASS_REASON='incident recovery' \
git commit ...
```

reason 为空、审计文件不可写或 scope 无法解析时 fail closed。审计记录时间、事件、
repository/worktree identity、profile、staged/push target paths、refs 和 reason。bypass
会跳过 runtime 与 approved chains，但不会被静默接受。

install 使用 versioned release、原子 `current` symlink、repository-scoped transaction 和
common config rollback record。任何 state swap 或 `core.hooksPath` 更新失败都会恢复旧
release、旧 trust record 和旧 hooksPath；uninstall 仅在当前 hooksPath 仍指向该受信安装时
执行，并在恢复旧值后删除 approved copies、registry 与 installation record。doctor 验证
hooksPath、bundle release、runtime、registry、7 个 hook shim 和所有 approved digest。

### mac-bootstrap-template 迁移曳光弹

`mac-bootstrap-template` 是第一个仓库迁移 profile。它刻意只复用已经跑通的三段机械能力：

- `after.edit` 继续使用 `python-syntax-smoke`；
- `before.commit` 只编译 dispatcher 物化的 staged Python snapshot，不读取未暂存 working tree；
- `before.push` 只验证 dispatcher 提供的 ref 列表与 40 位十六进制 OID 元数据完整性。

该 profile 不等价于旧 `make repo-check`，也不提前加入 machine checks、父仓 pointer、文档
审计或 Public CI 模拟。首枪的公开验收是在独立临时仓库安装 dispatcher：坏的 staged Python
提交被阻止；已暂存有效代码而 working tree 另有无效实验时仍可提交；真实 push 到 bare
remote 后本地与远端 SHA 相同；doctor 为 healthy；uninstall 恢复安装前的
`core.hooksPath`。

profile 合并后，真实 template common config 仍需显式设置：

```bash
git config --local agent.runtime.enabled true
git config --local agent.runtime.profile mac-bootstrap-template
make quality-gate-hook-inventory GIT_HOOK_REPO=/path/to/template
make quality-gate-hook-install \
  GIT_HOOK_REPO=/path/to/template \
  GIT_HOOK_REGISTRY=/trusted/registry.jsonc \
  GIT_HOOK_PYTHON=/trusted/python3
make quality-gate-hook-doctor GIT_HOOK_REPO=/path/to/template
```

切换前记录旧 hooksPath；安装、真实 commit/push 或 doctor 任一步失败都执行 uninstall 回滚。
不得同时保留旧 repo-managed hook 与新 dispatcher 作为竞争入口，也不得由通用 bootstrap
自动改写现有 `core.hooksPath`。machine/repository 分层和完整父仓迁移继续留在
#55 的后续纵向切片。

### 普通 Python 仓库曳光弹

`python-repo-smoke` 是首个不绑定仓库名称的 profile。它只引用与
`mac-bootstrap-template` 相同的三个已验证 gate，不增加项目路径、命令或 installer：
编辑后检查单个 Python 文件，提交前编译 staged snapshot，push 前验证 ref/OID 元数据。
它适合先验证普通 Python 仓库的机械闭环，但不代表已迁移该仓库的 unittest、lint、业务
检查或 hosted CI。仓库仍需显式 opt-in、inventory、install、doctor，并在试点结束后用
uninstall 验证原 hooksPath 可恢复。

### mac-bootstrap 父仓 pointer 曳光弹

`mac-bootstrap-parent` 在已验证的 Python staged syntax 与 push ref gate 之外增加三段
父仓能力。`parent-submodule-pointer-reachable` 只在 staged target 包含 `template` 时运行：
从 index 读取 `.gitmodules`，取得 mode `160000` gitlink 的 staged OID，并在临时 bare repo
中从配置远端按 OID fetch。仅存在于本地子仓 object database、尚未 push 的 commit 会阻止
父仓提交；子仓先 push 后，同一个 pointer commit 才能通过。删除 gitlink不需要远端可达性
检查。相对 URL 与 `ext::`/`fd::` helper 在该首枪中 fail closed。

pointer checker 随 dispatcher 的可信 bundle 发布，runtime 通过内部
`AGENT_RUNTIME_LIB_DIR` 指向当前 release 的 `lib/`，不引用父仓或 template checkout 路径。
阻塞 Git 生命周期中，gitlink目录不按普通文件复制；普通文件仍由 edit-feedback snapshot
保护，而 dispatcher 继续比较完整 index tree 与 worktree fingerprint，任何 gate 改写仍会
阻止提交。真实验收必须遵守 child-first、pointer-second，并在结束后 uninstall 验证原
hooksPath 可恢复。

`before.push` 另外固定调用 `make repo-check`。`make machine-check` 不再根据“看起来像
main checkout”自动运行，而必须由真实管理 checkout 显式声明：

```bash
git config --local agent.runtime.managementCheckout true
```

该值位于 git common config，因此 linked worktree 可以看到它；但 runner 同时要求当前
`git dir == git common dir` 且不是 submodule，linked worktree 与 submodule 始终降级为
repo-only。独立 clone 默认没有该标记，也只跑 repo-check。trusted bundle 只固定 target 名称
`repo-check` / `machine-check`，仓库不能通过 profile 或 local config 注入任意命令。
doctor 输出 `management_checkout`、`management_checkout_config_valid` 与
`effective_check_scope`；无效布尔值会使 doctor unhealthy，并在 push 时 fail closed。

repo/machine runner 不使用目标仓库自己的 `.venv`，也不继承调用者随意设置的 `PYTHON`。
dispatcher 从安装记录读取已经验证的 trusted Python，以显式 `--trusted-python` 传给 runtime；
runtime 再通过 `AGENT_RUNTIME_PYTHON` 强制覆盖 Make 的 `PYTHON`。venv 入口路径必须原样保留，
不得解析为底层 base interpreter，否则会丢失其 site-packages。用于 parent repo-check 的解释器
必须位于目标父仓之外，并已安装 pytest 等仓库检查依赖；本机试点使用 template 管理 checkout
中的 `.venv/bin/python`，独立 clone 无需建立自己的虚拟环境。

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
即使 session ID 相同，两个 worktree 也不会共享这些路径。只有显式标记的真实管理
checkout 才负责验证用户级 symlink、LaunchAgent、已安装应用等机器状态。新建 linked
worktree 时 `post-checkout` 可能传入全零 old OID；dispatcher 将其规范化为空树后再计算路径。

## 检查分层

质量门禁分为两个层级：

| Target | 职责 | 适用位置 |
|---|---|---|
| `make repo-check` | 语法、隐私、skill、非 `machine` 测试 | 普通 clone、管理 checkout、linked worktree、submodule |
| `make machine-check` | strict doctor 与 `machine` 标记测试 | 显式标记的真实管理 checkout |
| `make check` | `repo-check + machine-check` | 显式标记的真实管理 checkout 的完整发布验证 |

普通 clone、linked worktree 或 submodule 的 pre-push 只运行 repository checks。临时
worktree 不应接管或重写真实机器上的 managed symlink，也不应因它们仍指向管理 checkout
而失败。

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
