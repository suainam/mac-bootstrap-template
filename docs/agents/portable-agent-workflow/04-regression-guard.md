# Portable Agent Workflow: 真实失败固化为自动防回归约束

来源：issue #225（spec `portable-agent-workflow` 草稿，未发布）。把 #222/#223
复现的一次真实 shell 缺陷固化为可自动拦截的回归约束：下一次会话或 CI 无需
口头纠正，`make check` 的 pytest 会直接拦住同类缺陷。本文是该缺陷类的唯一
规则来源；其他规则文件只链接到这里，不复制条文。

## 失败与根因

`make doctor-agent` 在 OpenCode 段崩溃（#222 首次记录，#223 修复）：

```text
scripts/lib/agent-shared.sh: line 89: CLAUDE_RTK: unbound variable
```

两处缺陷同属一类：macOS 自带 `/bin/bash` 3.2（模板脚本全部以
`#!/usr/bin/env bash` + `set -euo pipefail` 运行，PATH 命中的 bash 版本随
机器而异）在 `set -u` 下对「未定义变量」和「空数组 `"${arr[@]}"` 展开」
同样报 unbound variable 并退出。实测（bash 3.2.57）：

```bash
/bin/bash -c 'set -euo pipefail; c=(); set -- "${c[@]}"; echo ok'   # unbound variable, rc=1
/bin/bash -c 'set -euo pipefail; c=(); set -- "${c[@]:-}"; echo ok' # 存活, 但 argv 含 1 个空串
```

1. `scripts/lib/agent-shared.sh` 的 `pick_rtk_source` 直接引用只在
   `install-agent-tooling.sh` 安装期定义的 `CLAUDE_RTK`/`CODEX_RTK`；
   doctor 独立运行时变量未定义即崩。
2. `scripts/agent-doctor.sh` OpenCode 段对可能为空的
   `opencode_rtk_arg`/`opencode_adv_arg` 用不带守卫的 `"${arr[@]}"` 展开。

bash 5 下两种写法都不报错，所以缺陷只在 `set -u` + 旧 bash 组合上暴露：
三条约束缺一不可——`set -u`、可选变量（安装期才定义或按文件存在性填充）、
数组在另一分支可能为空。

## 一般规则

- 可选环境变量一律带默认值读取：`local rtk_src="${CODEX_RTK:-$HOME/.codex/RTK.md}"`，
  不得裸引用 `$CODEX_RTK`。既属守卫也是语义：默认路径即该变量的既有约定。
- `set -u` 下的数组展开，按位置分两种守卫，选错会引入空串 argv 缺陷：
  - **作命令行参数传给下游命令**（下游对 argv 数量敏感，如 argparse）：
    先判长度再追加，不要用 `"${arr[@]:-}"`——bash 3.2 下它在数组为空时
    仍产生一个空字符串参数（实测 `set -- "${a[@]:-}"` 得 `argc=1`），bash 5
    则得 0 个，行为随版本漂移。守卫形态：
    ```bash
    local -a cmd=(fixed --args)
    if [ "${#opt_arg[@]}" -gt 0 ]; then cmd+=("${opt_arg[@]}"); fi
    "$cmd[@]" 调用方式见下
    ```
    即 `run_cmd "${cmd[@]}"`。
  - **在 `if cmd ${arr[@]:-}` 这类无需保留空串的位置**（不进入下游 argv）：
    `"${arr[@]:-}"` 可用且必要，否则空数组即 unbound。
- 判断标准不是「当前机器跑得过」，而是 `/bin/bash 3.2 + set -u + 数组可能为空`
  三件套成立即需守卫；新写脚本或改 argv 构造时先按此自查。

## 现有拦截（修复后即回归约束）

| 位置 | 约束 | 证据测试 |
| --- | --- | --- |
| `scripts/lib/agent-shared.sh` `pick_rtk_source` | `CLAUDE_RTK`/`CODEX_RTK` 带 `:-` 默认值 | `tests/test_agent_doctor_status.py::test_opencode_section_tolerates_unbound_rtk_paths` |
| `scripts/agent-doctor.sh` OpenCode 段 | `opencode_rtk_arg`/`opencode_adv_arg` 用 `"${arr[@]:-}"`（不进下游 argv 的位置） | 同上 |
| `scripts/agent-doctor.sh` Codex 段 | `codex_rtk_arg`/`adv_arg` 用 `"${arr[@]:-}"`（同上） | 同上 |
| `scripts/lib/agent-configure.sh` `ensure_codex_instructions` | `rtk_arg`/`adv_arg` 先判长度再追加进 `render_cmd`（进下游 argv 的位置，不用 `:-`） | `tests/test_agent_instruction_management.py::test_codex_instruction_generation_tolerates_missing_rtk_and_adv_files` |
| 反向约束（防倒退回 `auth_header`/`policy_args` 旧写法） | agent-doctor 不得出现 `"${auth_header[@]}"`/`"${policy_args[@]}"` | `tests/test_agent_doctor_config.py::test_agent_doctor_avoids_empty_array_expansion_under_nounset` |

任何一项被改坏，`make check`（父仓）或 `template` 内 pytest 即红，无需人工
口述「上次这里坏过」。#225 的红绿复演证明该拦截有效：在临时 worktree 检出
修复前提交 `ffdac2c^`，仅带入回归测试即红（stderr 含 `CLAUDE_RTK: unbound
variable`）；检出 `ffdac2c` 即绿。新守卫 `ensure_codex_instructions` 同样
红绿复演：回退该函数的修复后在 `/bin/bash` 3.2 下复现
`rtk_arg[@]: unbound variable`，恢复后通过。

## 同类审计结论（#225）

对 `scripts/` 全量 `set -euo pipefail` 脚本的 `[@]` 展开与可选变量审计：

- **已守卫，无需改动**：`install-pi-packages.sh`、`migrate-to-homebrew.sh`、
  `syntax-check.sh`、`neat-freak-ci.sh` 的数组均以固定字面量或先 `arr=()` +
  循环填充后经 `${#arr[@]}` 判断使用；`agent-doctor.sh` 的 `audit_args`/
  `scan_args` 声明即带非空元素（`local -a`），仅按 `+=` 追加；
  `agent-mcp.sh` 的 `render_args` 同为声明即非空。
- **同缺陷类，本票修复**：`agent-configure.sh` `ensure_codex_instructions`
  的 `"${rtk_arg[@]}"`/`"${adv_arg[@]}"`（数组按文件存在性条件填充，可能为空，
  且进入下游 argv）。红绿证据见上节。
- **同类但当前不触发**：`link_canonical_symlinks` 裸引用 `$CLAUDE_RULES_ADVERSARIAL_REVIEW`
  与 `$ADVERSARIAL_REVIEW_SRC`，但仅被 `install-agent-tooling.sh` 调用，该脚本
  在调用前用 `json_get_path` 全量定义这些变量；`link_canonical_symlinks` 无
  其他调用方（已 grep 验证）。若未来新增调用方且不预定义这些变量，即落入
  本缺陷类，须按上节一般规则补默认值。

## 过程能力映射

本票不发明新流程，复用现有 reflect/correct 等价能力（#222 能力映射的结论）：

- reflect：`retro` / OMP `s-retro` / KLM 技能族——本文档即复盘产物，走
  KLM 收口（`curate-repo-knowledge`）后由 `docs/README.md` 索引。
- correct：`diagnosing-bugs`（先复现）+ `tdd`（红到绿）+
  `agent/rules/common/testing.md` 的 verify-the-verification（注入故障必须
  看到测试变红再恢复）——本文的红绿复演即按该契约执行。

## 验证命令（#225 实测）

```bash
cd template && .venv/bin/python -m pytest tests/test_agent_doctor_status.py \
  tests/test_agent_doctor_config.py tests/test_agent_instruction_management.py \
  tests/test_agent_installer_config.py
cd template && ./scripts/privacy-audit.sh
cd template && .venv/bin/python scripts/check_docs.py docs/agents/portable-agent-workflow/
cd template && .venv/bin/python scripts/skill_supply_chain.py check
```

父仓侧：`make doctor`、`make doctor-agent`、`make check`（已知 4 项
external tools drift 与 3 项 AGENTS.md/MCP MISS，#222 起未变，属 private
overlay 范畴，不在本票修复）。
