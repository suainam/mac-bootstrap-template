# Portable Agent Workflow: 独立审阅与退回

来源：issue #224（spec `portable-agent-workflow` 草稿，未发布）。在 #223 的
验证流程（见 `02-verification-flow.md`）之上定义独立审阅者如何复验实现者
交付的精确提交，以及 FAIL、BLOCKED、旧 PASS 作废与最多两轮修正的退回规则。
本文本身就是一次独立审阅的实测记录：作者即审阅者，运行在与票 01/02 不同的
新会话里，没有实现会话的上下文——独立上下文这一事实本身是本票证据的一部分。

## 审阅前提

- 实现者交付物必须包含：被测 SHA（模板子仓）、父仓 SHA、命令清单与
  退出码、unverified_checks（模板 `02-verification-flow.md` 第 4 阶段
  evidence 契约）。缺任何一项即 BLOCKED，不得开始复跑。
- 审阅者不信任实现者的结论，只复用其清单：每条命令在新上下文里重跑，
  以自测的退出码与输出判定。
- 审阅者与实现者不得是同一会话；同一会话内的"自查"不构成本流程的
  独立审阅。
- GPT-6.1 Terra 审阅项仅在宿主提供该模型时执行；本机模型目录无 Terra
  条目（#222 实测），该项保持 BLOCKED，不得替换模型或冒充已执行。

## 审阅流程

### 1. 检出被测版本

```bash
git worktree add --detach "$RT" <parent_sha>
git clone -q --no-checkout <template_path> "$RT/template"
git -C "$RT/template" checkout -q --detach <template_sha>
cd "$RT/template" && uv venv -q .venv && \
  uv pip install -q -p .venv/bin/python pytest pytest-cov pytest-xdist \
  chinese-calendar jsonschema openai pyyaml
```

- 子模块 URL 为 SSH，无网络凭据的干净检出无法 `submodule update`，
  以本地克隆代替（#223 已记录，属 stand-in，记入报告）。
- 就绪标准与 #223 第 1 阶段相同：`rev-parse HEAD` 等于被测 SHA、
  venv 可导入 pytest。达不到即 BLOCKED。

### 2. 复跑验收

按 `02-verification-flow.md` 的五阶段与判定语义重跑：

- 模板侧（与检出绑定，可 PASS）：`./scripts/privacy-audit.sh`、
  `skill_supply_chain.py check`、`check_docs.py`（改动文档）、
  相关 pytest 与全量 `pytest -m 'not machine'`。
- 机器侧（绑定主检出实例，干净检出上只能对照主检出结果）：`make doctor`、
  `make doctor-agent`、父仓 `make privacy-audit`。干净检出上这类命令的
  FAIL 证明"错误实例"检测生效，不是回归；但也不能在干净检出上把
  机器项报成 PASS。
- 每条命令记录原文、退出码、判定。任何一项与实现者证据包不符，
  即要求实现者解释；解释不能自证时判 FAIL。

### 3. 判定与退回

- **PASS**：全部可运行项通过，且机器侧项与实现者在主检出的基线一致，
  且 unverified_checks 与实现者交付一致或更少。
- **FAIL**：出现实现者未报告的 FAIL、缺陷类错误（如 `unbound variable`）、
  或实现者证据与实测不符。退回时必须给出修复交接：缺陷根因、复现命令、
  预期红转绿路径。
- **BLOCKED**：审阅前提缺失、依赖不可用、或命令因环境原因无法给出可信
  结论。BLOCKED 不是通过；对应项入 unverified_checks，审阅结论不能是 PASS。
- **旧 PASS 作废（stale-PASS）**：审阅基于精确 SHA。交付后被测分支出现
  新 commit，无论改动多小（含纯文档、空提交），旧 PASS 即对合并失效；
  合并前必须在新 SHA 上重跑。审阅者复查时以 `rev-parse HEAD` 为准，
  不以"上次审过"为准。
- **轮次上限**：每个交付最多两轮修正退回。两轮后仍 FAIL 即停止，报告
  人工介入；不得以第三轮继续自动循环。

## 注入实测（#224）

三次注入均在一次性 worktree/克隆内完成，事后删除，未触及主检出。

### 注入 1：缺陷使审阅返回 FAIL

- 注入方法：在一次性克隆（`1be4bd7` 检出）内把
  `scripts/lib/agent-shared.sh` 覆写为 `ffdac2c` 修复前的版本
  （`git show ffdac2c~1:scripts/lib/agent-shared.sh`，即 #223 修复的
  对象），模拟缺陷回归。
- 命令与结果：

```text
.venv/bin/python -m pytest tests/test_agent_doctor_status.py -q
  退出码 1；1 failed, 4 passed；stderr 含 CLAUDE_RTK: unbound variable
make doctor-agent（父仓 worktree）
  退出码 2；scripts/lib/agent-shared.sh: line 89: CLAUDE_RTK: unbound variable
```

- 判定：**FAIL**。修复交接（退回正文）：
  根因为 `pick_rtk_source` 在 `set -u` 下引用仅由
  `install-agent-tooling.sh` 导出的 `CLAUDE_RTK`/`CODEX_RTK`（#223
  已修复的同一缺陷）；复现命令即上两条 pytest/doctor-agent；预期修复为
  `ffdac2c` 对 `agent-shared.sh` 的默认值补丁，红转绿由
  `test_opencode_section_tolerates_unbound_rtk_paths` 守护。
- 复原与验证：`git checkout -- scripts/lib/agent-shared.sh` 后
  `git status --porcelain` 为空、`git diff --quiet` 退出码 0，
  pytest 同文件 `5 passed`（退出码 0）。主检出该文件保持修复后版本
  （`local claude_rtk="${CLAUDE_RTK:-...}"` 在位）。

### 注入 2：检查无法运行返回 BLOCKED

- 注入方法：删除一次性检出里模板 `.venv`，运行 `make check`
  （父仓）与模板 `make check`。
- 命令与结果：

```text
make check（父仓，无 venv）
  退出码 2；未出现 pytest 阶段即死于 parent-privacy-audit（worktree 权限位），
  未能给出被测代码结论
make check（模板，无 venv）
  退出码 2；bash: line 1: .venv/bin/python: No such file or directory；
  make[1]: *** [fresh-check] Error 127
```

- 判定：**BLOCKED**，不是 PASS。缺 venv 时无法执行任何 Python 检查，
  按 #223 判定语义记入 unverified_checks；退出码 127 与缺文件证据是
  BLOCKED 而非 FAIL（缺陷）的判据。恢复 venv 后同一命令可运行并给出
  可信结论，证明判定区分依赖的是依赖存在性而非退出码数字本身。

### 注入 3：新提交使旧 PASS 作废

- 注入方法：审阅完成 `1be4bd7` 后，在一次性克隆内执行
  `git commit --allow-empty` 产生新提交
  `2d313a95d1c3ba8a365009864e98b80e3169afc0`（空提交，代码零改动），
  再在新 HEAD 上重跑同一检查。
- 命令与结果：

```text
git rev-parse HEAD
  2d313a9...（≠ 被审 SHA 1be4bd7...）
.venv/bin/python -m pytest tests/test_agent_doctor_status.py -q
  退出码 0；5 passed
```

- 判定：新 SHA 上检查本身仍绿，但这只对 `2d313a9` 有效；对 `1be4bd7`
  的 PASS 不可用于合并 `2d313a9`。按 stale-PASS 规则，合并前必须在
  `2d313a9` 上完成整套复跑。空提交也触发作废：规则绑定的是 SHA 移动，
  不是 diff 内容。主检出的 `feat/portable-agent-workflow` 仍停在
  `1be4bd7`，分支未被污染。

## 独立审阅实测：复验 1be4bd7（票 02 交付）

审阅者上下文：与票 01/02 不同的新会话（Claude Code 2.1.311），仅凭
issue 与文档清单执行，未接触实现会话。

### 绑定提交

- 父仓：`e3f4d0d18656856cf5fca201337b11de16727589`（`git worktree add
  --detach`，`status --porcelain` 干净）。
- 模板子仓：被测交付 `1be4bd749dd036f1b9c22fc07e505dced5d110d8`
  （本地克隆，stand-in 记录同 #223）。

### 模板侧（干净检出 1be4bd7）

| 命令 | 退出码 | 判定 | 说明 |
| --- | --- | --- | --- |
| `./scripts/privacy-audit.sh` | 0 | PASS | `privacy-audit: ok` |
| `.venv/bin/python scripts/skill_supply_chain.py check` | 0 | PASS | skills=141 external=83 internal=58 global=98 project=43 targets=6 |
| `.venv/bin/python scripts/check_docs.py docs/agents/portable-agent-workflow/` | 0 | PASS | 3 doc(s) clean |
| pytest `test_agent_doctor_status.py test_agent_doctor_config.py test_agent_installer_config.py` | 0 | PASS | 30 通过 |
| 全量 `pytest tests/ -q -p no:cacheprovider` | 1 | FAIL（错误实例） | 1095 通过、19 失败，全部为 `test_managed_symlinks.py::test_symlink_points_to_current_target`（machine 标记测试断言 symlink 指向 worktree 路径，机器实例事实），非缺陷 |
| `make check`（模板） | 2 | FAIL（实例 drift） | fresh-check external tools drift 12 项（worktree 下 UNEXPECTED 项比主检出多：代理/工具 symlink 指向主检出路径）；pytest 1024 通过 |

### 机器侧（对照主检出）

| 命令（位置） | 退出码 | 判定 | 说明 |
| --- | --- | --- | --- |
| `make doctor`（worktree） | 2 | FAIL（错误实例） | 仅 `~/.ssh/config points to unexpected target` 与 6 条 stale symlink（指向主检出路径），无缺陷类错误 |
| `make doctor-agent`（worktree） | 2 | FAIL（错误实例） | 3 处 MISS（AGENTS.md 内容 ×2、codex managed MCP state）；**无 `unbound variable`**，#223 缺陷修复在干净检出上复验成立 |
| `make privacy-audit`（worktree） | 2 | FAIL（实例） | 27 项 private 文件权限位（worktree 检出不保留 600/700） |
| `make check`（worktree） | 2 | BLOCKED→FAIL（实例） | 死于 parent-privacy-audit 权限位，未达 pytest 阶段；其中 omp 私有 pytest 3 失败源于 `config.yml` 为 git-ignore 文件、worktree 无此文件（错误实例，非缺陷） |
| `make doctor`（主检出） | 0 | PASS | |
| `make doctor-agent`（主检出） | 2 | FAIL（drift） | 与 #223 一致：无 unbound，剩同 3 处 MISS |
| `make privacy-audit`（主检出） | 0 | PASS | |

### 审阅判定

- **对 `1be4bd7`：PASS（带记录的机器侧偏差）**。模板侧四项全绿；
  机器侧失败全部归类为错误实例/实例 drift，与 #223 记录一致，没有新 FAIL、
  没有缺陷类错误，`unbound variable` 缺陷修复在干净检出上被独立复验不复发。
- 交付的 unverified_checks 与实测相符（干净检出 `make check`、
  machine-check、GPT-6.1 Terra、第二宿主均未验证）。本次审阅将
  全量 `pytest tests/`（含 machine 标记）单独跑了一遍，把 #223 的
  "machine 测试未跑"缺口补成可解释的 19 项错误实例失败。
- 该 PASS 绑定 `1be4bd7`；本票自身的新提交（本文档）使其作废，
  合并前需在新 SHA 上按本流程重跑——这由注入 3 的规则覆盖。

## 清理

- 审阅与全部注入仅使用 `/tmp/paw224-review-*` 一次性 worktree 与本地克隆；
  结束后 `git worktree remove --force` + `prune`，worktree 已不存在，
  主检出 `template` 工作区与 `feat/portable-agent-workflow`（`1be4bd7`）
  不含任何注入残留（`git status --porcelain` 仅原有的两份未跟踪
  analytics 草稿，与 #223 交付一致）。
- 日志保留在执行机 `/tmp/paw224-*.log`，不入库；结论与关键行已录入本文。

## unverified_checks（本票）

- GPT-6.1 Terra：宿主不可用（#222 实测），保持 BLOCKED，未替换模型。
- 第二宿主（Codex/OpenCode/Reasonix）上的独立审阅复跑未执行，属后续票。
- 干净检出上的 `make devspace-status` 未跑：本票改动不涉及 DevSpace。
- 主检出 `make check` 本次未整体重跑（#223 已在主检出实测退出码 2、
  已知 4 项 drift）；本票复验以干净检出 + 模板侧检查 + 机器侧单项为准。
- 父仓 hooks 状态、`config.yml` 等 git-ignore 私有文件导致的 omp 测试
  差异，属 private overlay 决策，本票未改 `private/`。
