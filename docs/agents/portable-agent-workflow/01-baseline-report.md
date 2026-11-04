# Portable Agent Workflow: 基线验证报告

来源：issue #222（spec `portable-agent-workflow` 草稿，未发布）。本文记录
试验仓基线任务的选定、命令、退出码、结果与未验证项，使下一次运行可复现。

## 试验仓与基线

- 试验仓：mac-bootstrap 父仓本身（per spec：不另建隔离仓）。
- 基线提交：父仓 `e3f4d0d18656856cf5fca201337b11de16727589`（main），
  模板子仓 `5871c115ceffde3ba156caaed47b41555396411b`（feat/portable-agent-workflow）。
- 基线任务：`make check`、`make doctor`、`make doctor-agent`（均在父仓根目录），
  外加模板子仓自身的 `make check`。选择理由：无需生产凭据、只读或可恢复、
  输出可观察且退出码明确。

## 结果

| 命令（父仓根目录） | 退出码 | 结果 | 说明 |
| --- | --- | --- | --- |
| `make check` | 2 | FAIL（已知偏差） | 模板 pytest 1023 通过（覆盖率 81.11%，≥80% 达标），skill supply check 通过；失败仅 `fresh-check` 的 external tools drift：4 项本机应用/二进制与 profile=work 清单不一致 |
| `make doctor` | 0 | PASS | 98 项 ok，含 formula/cask、symlink、SSH config、MCP stdio 命令、npm CLI |
| `make doctor-agent` | 2 | FAIL（缺陷） | OpenCode 段后 `scripts/lib/agent-shared.sh: line 89: CLAUDE_RTK: unbound variable`（`set -u` 下未定义变量），另有 Codex `AGENTS.md canonical rules content` MISS |
| `make -C template check` | 2 | FAIL（同 drift） | 与父仓同一 external tools drift 根因 |

`make check` 的 drift 明细（4 项，均为本机机器事实，属 private overlay 范畴）：

```text
FAIL external tools drift (profile=work):
  app '.TNwHelperEp': MISSING .TNwHelperEp.app
  binary 'dsh': UNEXPECTED in the user-local bin directory
  app 'Rex Beta.app': UNEXPECTED in /Applications
  app 'QwenWorkCN.app': UNEXPECTED in /Applications
```

## 判定

- 基线任务跑通：四个命令全部实际执行、输出与退出码已捕获。基线状态是
  FAIL 可解释（机器 drift + 一个 shell 缺陷），不是 BLOCKED。
- `doctor-agent` 的 `CLAUDE_RTK` 未绑定变量是模板脚本缺陷
  （`pick_rtk_source` 在 `set -u` 下引用未定义变量，近期 commit 9065c11
  只修了 agent-doctor.sh 的同类问题，未覆盖 lib 层）。修复属于后续票，
  本票只记录；相应 private-path 需求：无。
- drift 四项是本机应用事实，修正需要 private overlay 决策（增删 profile 清单
  或卸载应用），不在模板侧处理。

## 未验证项

- 未做任何代码/配置变更驱动的行为验证（本票是文档票，无代码逻辑，测试不适用）。
- `make check` 中的 drift 子项未逐项修复验证；`doctor-agent` 缺陷未修复验证。
- 静态检查不证明 agent 行为：本报告证明的是"基线命令可运行且结果可复现"，
  单代理任务执行路径的证明属于 spec 后续票。

## 宿主与模型可用性

- 首宿主：Claude Code 2.1.311（当前运行宿主）。
- 第二宿主候选（本机已安装，`command -v` 实测）：
  - Codex CLI `codex-cli 0.166.0`——支持子代理/MCP（`codex mcp list` 确认
    codebase-memory-mcp enabled），技能入口 `~/.codex/skills` 已由 distributor
    布线；
  - OpenCode `v2.2.5`——技能入口已布线（doctor-agent 的 OpenCode 段检查通过）；
  - Reasonix `v2.57.0`（`~/.reasonix/skills` 目标存在）。
  - 干净检出要求：三个候选均可在 fresh clone 上运行本仓 `make check`
    的 repo-check 部分；machine-check 依赖本机 profile，第二宿主复跑时
    需按 `docs/agents/quality-gates.md` 的 machine/repo 分界声明范围。
- GPT-6.1 Terra：**本机模型目录不可用**。`private/agent/omp/catalog/` 的
  cliproxy 模型清单含 `gpt-6.1-sol`、`gpt-6-luna`、`gpt-6-astra` 等，
  无任何 Terra 条目（grep 大小写不敏感，0 命中）。按 spec 不替换模型、
  不宣称已调用；记录为模型验证依赖。该项为私有配置事实，公开侧只记录
  "不可用"结论，不复制模型清单。

## 证据包

- 命令与退出码见上表；完整输出保存在执行机的临时日志
  （`/tmp/make-check-out.log` 等，非提交物）。
- 复现方式：在绑定提交上依次执行上表命令并比对退出码与 FAIL 明细。
