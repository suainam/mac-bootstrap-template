# Topgrade Configuration

macOS 全生态统一更新工具配置，作为 `mac-bootstrap` 维护的唯一真源。

## 目标与架构

- **真源路径**: `template/system/topgrade/topgrade.toml`
- **目标软链**: `~/.config/topgrade.toml`
- **联动范围**:
  - **Homebrew**: Formula + Cask (安全策略 `greedy_cask = false`)
  - **Node 生态**: `npm -g`, `pnpm -g`
  - **Bun 生态**: `bun -g update` (自动更新 `opencode2` 等 Bun 全局 CLI)
  - **Python 生态**: `pipx upgrade-all`, `uv tool upgrade --all`
  - **Mac App Store**: `mas upgrade`
  - **终端/编辑器插件**: `zinit`, `tmux`, `nvim`, `yazi`, `claude code`

## 统一入口关系

- **`make system-upgrade`（推荐日常唯一入口）**: 权威编排脚本，依序执行 `topgrade`（全生态工具链更新） $\rightarrow$ `make patch-chrome-gemini`（Chrome 补丁） $\rightarrow$ `scripts/skill_supply_chain.py`（刷新并分发外部 Agent 技能）。
- **`topgrade`（底层执行引擎）**: 仅负责包管理器与运行时插件更新，不挂载仓库内部特化脚本，保持职责单一与幂等。

## 常用命令

```bash
# 日常推荐：一键全生态更新 + 补丁与技能分发
make system-upgrade

# 仅查看待更新项演练
topgrade --dry-run

# 仅更新各包管理器
topgrade
```
