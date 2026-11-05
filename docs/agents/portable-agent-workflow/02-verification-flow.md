# Portable Agent Workflow: 项目验证流程

来源：issue #223（spec `portable-agent-workflow` 草稿，未发布）。在 #222 基线上
定义 mac-bootstrap 试验仓的 launch、doctor、drive、evidence、cleanup 五阶段，
并记录一次干净检出的实际执行。静态检查不证明 agent 行为；本文只证明命令可运行、
结果可复现、判定可区分。

## 判定语义

- PASS：命令实际执行，退出码 0，且输出无 FAIL/MISS。
- FAIL：命令实际执行，退出码非 0 或输出含 FAIL/MISS；必须区分「代码缺陷」与
  「本机/实例 drift」，后者不得靠改判通过。
- BLOCKED：命令因缺依赖、缺 venv、错误实例而无法给出可信结论；记入
  `unverified_checks`，不得写成 PASS。
- 提交后任何新 commit 使旧结论失效，须在新 SHA 上重跑。

## 五阶段

### 1. launch

试验对象是仓库自身，无常驻服务。launch = 取得绑定提交的干净检出并备好解释器：

```bash
git worktree add --detach "$RT" <parent_sha>        # 临时目录，本次所有
git clone -q --no-checkout <template_path> "$RT/template"
git -C "$RT/template" checkout -q --detach <template_sha>
cd "$RT/template" && uv venv -q .venv && \
  uv pip install -q -p .venv/bin/python pytest pytest-cov pytest-xdist \
  chinese-calendar jsonschema openai pyyaml
```

- 就绪标准：`git -C "$RT" rev-parse HEAD` 等于目标 SHA，`.venv/bin/python` 可导入 pytest。
- 子模块 URL 为 SSH，干净检出无网络凭据时无法 `submodule update`，用本地克隆代替并记录。
- 未就绪（无 venv、无法 checkout）：BLOCKED。

### 2. doctor

只读，回答「这个实例值得驱动吗」。先确认是自己的实例：

```bash
git -C "$RT" rev-parse HEAD && git -C "$RT" status --porcelain   # SHA 正确且干净
make doctor          # 机器 formula/cask/symlink/MCP 健康
make doctor-agent    # 宿主（Claude/Codex/OpenCode/Reasonix）配置与 MCP 状态
```

- PASS：两者退出码 0。
- FAIL（drift）：MISS 指向本机运行态（如 `~/.ssh/config`、codex MCP 状态指向主检出）。
  这类检查绑定的是主检出实例，干净检出上出现 MISS 说明「错误实例」，
  结论是该项对干净检出 BLOCKED，不是 PASS。
- FAIL（缺陷）：`unbound variable`、`command not found` 等 shell 错误。

### 3. drive

驱动真实行为，不用 mock 替代：

```bash
make check                     # 父仓：repo-check + machine-check（含 template pytest、skill supply）
make privacy-audit             # 父仓 + 模板隐私审计
make devspace-status           # 仅当改动涉及 DevSpace；只读状态
cd template && ./scripts/privacy-audit.sh
cd template && .venv/bin/python scripts/skill_supply_chain.py check
cd template && .venv/bin/python scripts/check_docs.py <改动的 docs>
```

- 改动脚本时，先写失败测试再修复，展示红到绿（见下方 #223 实测）。
- `make check` 已知因 private overlay 的 external tools drift 返回 2：只允许这一类
  FAIL；出现新的 FAIL 项即为回归。
- 工具缺失（如无 devspace）：BLOCKED，写入 unverified_checks。

### 4. evidence

证据包必须绑定提交，包含：

- `tested_commit`：父仓 SHA、模板子仓 SHA、是否干净检出；
- 每条命令的原文、退出码、PASS/FAIL/BLOCKED；
- FAIL 明细（drift 逐项名称）与根因归类；
- `unverified_checks` 与缺失依赖；
- 日志位置：临时目录 `/tmp/*.log` 不入库，仅结论与关键行入报告。

任务契约与证据包的最小字段（缺字段即证据不足，不得报 PASS）：

```yaml
task_contract:
  goal: 一句话目标
  constraints: [范围、禁改路径、不得 push 等]
  observable_success: [可由命令或文件观察的通过条件]
evidence_package:
  - command: 原文命令
    exit_code: 0
    commit_sha: 被测提交（父仓/子仓）
    artifacts: [日志或报告路径]
  unverified_checks:
    - item: 未验证项
      reason: 为什么未验证（BLOCKED / 超范围 / 依赖缺失）
```

### 路由：何时用哪条路径

- 直接做：单文件、单一权威、可一条命令验证的改动。
- 先设计：涉及模块边界、数据模型或跨权威来源时，先用 `codebase-design`、
  `domain-modeling`、`improve-codebase-architecture`，需要图时用 `archify`；
  动手前先 `search-first` 查现有实现。
- 验证优先：缺陷修复或高风险行为改动，先 `diagnosing-bugs` 复现，再 `tdd`
  红到绿；需要新验证流程时参考 `create-verification-skill`（未登记 registry，
  见 `01-capability-mapping.md`）；收口走 `knowledge-record`。

### 5. cleanup

只清理本次创建的状态，不按名称杀进程：

```bash
git worktree remove --force "$RT"      # 只删本次 launch 创建的 worktree
git worktree prune
rm -f /tmp/<本次创建的日志>             # 证据结论已写入报告后才可删
```

- 不改动主检出、`~/.ssh`、LaunchAgent、`private/`。
- 清理后确认报告仍存在。清理吞掉证据即本阶段 FAIL。

## 实测执行（#223）

### 绑定提交

- 父仓：`e3f4d0d18656856cf5fca201337b11de16727589`（git worktree，detach，status 干净）。
- 模板子仓：干净检出为本地克隆 `ffdac2c5e336f32157262a67fefb1653a923963f`
  （分支 `feat/portable-agent-workflow`，含下述修复）。父仓指针 `9065c11` 是修复前版本。
- 本文档随后提交只增加文档，不改变被测代码；代码结论仍绑定 `ffdac2c`。

### 缺陷修复：红到绿

`make doctor-agent` 在 OpenCode 段因 shell 缺陷退出（#222 已记录）。根因有两处，
同属 `set -u` 下的未绑定展开：

1. `scripts/lib/agent-shared.sh` 的 `pick_rtk_source` 直接引用只在
   `install-agent-tooling.sh` 里定义的 `CLAUDE_RTK`/`CODEX_RTK`。
2. `scripts/agent-doctor.sh` 对空数组 `"${opencode_rtk_arg[@]}"` 展开（macOS bash 3.2
   下同样触发 unbound）。当时的临时修法是 `${arr[@]:-}`，后续复核发现它在 bash 3.2
   下仍会把空串带入 `agent-instructions.py verify` 的 argv；Codex/OpenCode 两段现均
   改为先判长度的累加数组，见 `04-regression-guard.md`。

新增 `tests/test_agent_doctor_status.py::test_opencode_section_tolerates_unbound_rtk_paths`。

| 步骤 | 结果 |
| --- | --- |
| 修复前 | 红：stderr 含 `CLAUDE_RTK: unbound variable` |
| 只修 1 | 仍红：stderr 含 `opencode_rtk_arg[@]: unbound variable` |
| 修 1 和 2 | 绿：doctor/config/installer 三个测试文件共 30 通过 |

### 命令与结果

主检出（含修复，父仓 `e3f4d0d` 脏工作区）：

| 命令 | 退出码 | 判定 | 说明 |
| --- | --- | --- | --- |
| `make doctor` | 0 | PASS | 无 FAIL/MISS |
| `make doctor-agent` | 2 | FAIL（drift） | 不再出现 `unbound variable`；剩 Codex 与 OpenCode 两处 `MISS AGENTS.md canonical rules content`，属本机宿主指令内容 drift，未修（argv 缺陷修复后复跑仍是这 2 项，见 `04-regression-guard.md`） |
| `make check` | 2 | FAIL（已知 drift） | pytest 1024 通过（#222 为 1023，差值为新增测试），覆盖率 81.11%，skill supply 通过；失败仅 `fresh-check` 的 4 项 external tools drift |
| `./scripts/privacy-audit.sh`（模板） | 0 | PASS | |
| `skill_supply_chain.py check` | 0 | PASS | skills=141 targets=6 |

干净检出（worktree，`ffdac2c`）：

| 命令 | 退出码 | 判定 | 说明 |
| --- | --- | --- | --- |
| `make doctor-agent` | 2 | FAIL（错误实例） | 无 `unbound variable`（缺陷已不复现）；MISS 为 codex MCP 状态指向主检出和 AGENTS.md 内容 |
| `make doctor` | 2 | FAIL（错误实例） | 仅 `~/.ssh/config points to unexpected target`，指向主检出的路径 |
| `make privacy-audit` | 2 | FAIL（实例） | `parent-privacy-audit`：27 项 private 文件权限 644（期望 600），worktree 检出不保留权限位 |
| `./scripts/privacy-audit.sh`（模板） | 0 | PASS | |
| `skill_supply_chain.py check` | 0 | PASS | 重跑单独捕获退出码 |
| 三个测试文件 pytest | 0 | PASS | 30 通过 |

结论：干净检出证明验证不依赖会话状态，也证明机器类检查（doctor、doctor-agent、
parent privacy-audit）绑定主检出实例，不能在干净检出上被报告为 PASS。

### unverified_checks

- 干净检出上的 `make check`、`make machine-check` 未跑：machine 测试绑定本机
  profile，且 fresh-check drift 已知。
- 修复前 `make doctor-agent` 在干净检出上的结果取自基线指针 `9065c11`（
  缺 venv 的 BLOCKED 项与 unbound 缺陷混在同一输出），未单独隔离。
- Codex/OpenCode 的 `AGENTS.md canonical rules content` MISS：已确认 argv 缺陷
  修复后仍在，来源是 `~/.codex/AGENTS.md` 与 `~/.config/opencode/AGENTS.md` 内容
  与模板权威不一致；刷新这两个宿主文件需 agent 配置刷新决策，未执行。
- `make devspace-status` 未跑：本票改动不涉及 DevSpace。
- 第二宿主（Codex/OpenCode）复跑、GPT-6.1 Terra 均未验证。
- 子模块 SSH URL 在干净检出无法拉取，改用本地克隆，属 stand-in。
- private 路径需求：4 项 external tools drift 与权限位，需父仓 private overlay 决策，
  本票未改 `private/`。
