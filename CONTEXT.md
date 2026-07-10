# mac-bootstrap 模板上下文

> 本文件解释公开模板的架构、公共边界和权威来源。当前机器的真实配置与运行层级属于私有父仓，不写入本仓。

## 定位

这是一个可重复执行、尽量幂等的 macOS 开发环境 bootstrap 模板。它通过 Homebrew、Shell 脚本与数据清单安装 CLI、桌面应用、终端环境、agent 工具和常用配置。

模板只拥有可公开、可复用的能力与默认值；私有父仓通过 overlay 提供机器专属配置。所有修改都应先判断：它是否能脱离当前机器仍然成立？能，则属于模板；不能，则属于父仓 `private/`。

## Bootstrap 阶段

| 阶段 | 主要入口 | 负责内容 |
|---|---|---|
| Brew | `Brewfile`、`brew-bundle.sh` | formula、cask、npm 包与字体 |
| Shell | `install.sh` | zsh、git、vim、neovim、tmux 与 VS Code |
| Docker | `infra/docker/install.sh` | Colima、代理与 Docker Compose |
| Agent | `install-agent-tooling.sh` | skills、MCP、RTK、caveman、Pi 与 CRG |
| Pi | `install-pi-packages.sh` | Pi 原生包 |
| Obsidian | `editors/obsidian/install.sh` | 可复用 vault 配置与模板 |
| Ghostty | `terminals/ghostty/repair-fonts.sh` | 字体修复 |

## 终端与系统控制边界

- tmux 是日常终端工作区与会话层；首个验证路径是 `make tmux-workspace`，因为它复用日常 shell startup 路径。
- Hammerspoon 是系统级控制层：全局快捷键、窗口编排、剪贴板辅助与终端启动入口属于该层。快捷键应保持全局且以 Hyper 为主。
- tmux pane 快捷键只在终端内部生效；不得与 Hammerspoon 的全局快捷键竞争。
- 输入法保持由 macOS 与用户控制；不得引入 Hammerspoon 自动切换输入法的行为。

## 公共权威来源

| 内容 | 权威来源 | 说明 |
|---|---|---|
| 软件与工具清单 | `Brewfile` | 不把包名硬编码到安装脚本 |
| Pi 包清单 | `agent/pi-packages.txt` | 独立数据文件 |
| Agent Skill 来源与分发 | `agent/skills-sources.jsonc`、`agent/skill-targets.jsonc` | 来源血统、scope、gate、target 目录和格式；运行态目录是派生产物 |
| Python 公共依赖 | `infra/python/requirements-common.txt` | 供数据分析环境复用 |
| VS Code 扩展 | `editors/vscode/extensions.txt` | 仅维护扩展 ID |
| doctor 检查 | `scripts/doctor-manifest.json` | 数据驱动检查与 cask 覆盖 |
| 私有覆盖契约 | `docs/private-overlay.md` | 说明父仓 overlay 的边界与优先级 |

数据清单应保持独立；不要把清单内容复制进脚本、README 或 agent 规则。

## Private Overlay 边界

公开模板通过私有父仓中的 `private/` 接收机器差异。真实账号、订阅、token、内网地址、私网 IP、当前机器绝对路径和本机运行状态都不属于模板。

覆盖规则、刷新流程和发布前隐私检查以 `docs/private-overlay.md` 为准。修改模板时必须保持 overlay 可用，不得因重命名、硬编码路径或删去 fallback 破坏已有私有配置。

## Agent 架构

受管 agent 包括 Claude Code、Codex CLI、OpenCode、Pi、Reasonix 与 Antigravity；其路径与配置目标由 `agent/agent-manifest.json` 描述。Agent Skill 由 `agent/skills-sources.jsonc` 管来源血统、scope、gate 与分发意图，由 `agent/skill-targets.jsonc` 管各 agent 的 skill 目录、格式和软链/复制策略；最终的 agent 目录是派生产物，不是默认编辑入口。

顶层 orchestrator 是 `scripts/install-agent-tooling.sh`。可复用 shell 逻辑位于 `scripts/lib/`；skill 分发由 `scripts/skill_supply_chain.py` 负责；Codex MCP 渲染由专用脚本负责；doctor 检查由 `scripts/run-doctor-checks.py`、`scripts/agent-doctor.sh` 与 manifest/registry 驱动。

## 文档边界

| 文件 | 职责 |
|---|---|
| `README.md` | 模板用途、首次安装、常用入口 |
| `CONTEXT.md` | 本文件：架构、公共权威来源、边界与术语 |
| `CLAUDE.md` / `AGENTS.md` | agent 修改模板时的稳定执行约束 |
| `docs/` | 可跨机器复用的专题操作与 runbook |

不要在多份文档复制完整机制。保留一个权威详述，其余文档只保留必要指针。

## 防漂移

使用 `neat-freak` skill 时，检查。显式调用格式由宿主决定：当前 Codex 使用 `$neat-freak`；支持 slash command 的宿主可使用其已注册入口。

1. 模板中是否混入私有父仓事实或敏感信息。
2. README、CONTEXT、规则文件和 `docs/README.md` 是否仍按职责分层。
3. 清单、脚本与文档对同一机制的描述是否一致。
4. 引用的路径、命令与专题文档是否存在。
5. `AGENTS.md` 是否仍与 `CLAUDE.md` 同源；不能让两份规则各自演化。
