# mac-bootstrap 模板上下文

> 本文件解释公开模板的架构、公共边界和权威来源。当前机器的真实配置与运行层级属于私有父仓，不写入本仓。

## 定位

模板提供可重复、尽量幂等的 macOS 开发环境 bootstrap 能力；`template/` 只拥有可公开复用的能力与默认值，私有父仓通过 `private/` overlay 提供机器差异。能脱离当前机器成立的改动进入模板，否则进入父仓 `private/`。

## Bootstrap 入口

- `Brewfile`、`brew-bundle.sh`：formula、cask、npm 包与字体。
- `install.sh`：zsh、git、vim、neovim、tmux 与 VS Code。
- `infra/docker/install.sh`：Colima、代理与 Docker Compose。
- `scripts/install-agent-tooling.sh`：skills、MCP、RTK、caveman、OMP、Pi 兼容层与 Codebase Memory。
- `install-pi-packages.sh`、`editors/obsidian/install.sh`、`terminals/ghostty/repair-fonts.sh`：各自专题安装与修复。

## 控制边界

- tmux 是日常终端工作区与会话层；首个验证路径是 `make tmux-workspace`，复用日常 shell startup。
- Hammerspoon 负责全局快捷键、窗口编排、剪贴板辅助与终端启动；全局快捷键以 Hyper 为主，不能与 tmux pane 快捷键竞争。
- 输入法由 macOS 与用户控制；模板不引入自动切换行为。

## 公共权威来源

| 内容 | 权威来源 |
|---|---|
| 软件与工具清单 | `Brewfile` |
| Pi 兼容包 | `agent/pi-packages.txt` |
| Python 公共依赖 | `infra/python/requirements-common.txt` |
| VS Code 扩展 | `editors/vscode/extensions.txt` |
| Agent Runtime | `agent/`、`agent/agent-manifest.json` |
| Agent quality gate | `docs/agents/quality-gates.md` |
| Skill 来源与分发 | `agent-skills/registry/sources.jsonc`、`agent-skills/registry/targets.jsonc` |
| CI 与本机检查 | `Makefile`、`.github/workflows/ci.yml` |
| Data Hub | `data-hub/` |
| doctor 检查 | `scripts/doctor-manifest.json` |
| 私有覆盖契约 | `docs/private-overlay.md` |
| Issue/PR 生命周期 | `docs/agents/issue-tracker.md` |

清单保持独立；不要把清单内容复制进脚本、README 或 agent 规则。

## Agent 与 Overlay

- `scripts/install-agent-tooling.sh` 是顶层 orchestrator；可复用 shell 逻辑在 `scripts/lib/`，skill 分发由 `scripts/skill_supply_chain.py` 负责。
- `agent/agent-manifest.json` 描述受管 agent 路径；OMP 是 Brewfile 默认 CLI，使用自身发现层，不由该 manifest 接管。
- `scripts/agent_mcp_runtime.py` 是受管 agent MCP server desired-state 权威；安装与 doctor 必须消费同一状态，不能各自维护 server 清单。DevSpace 是网页访问的本地服务，不属于 agent MCP；遗留配置应被清理。
- `agent/mcp-policy.json` 只管理 Codex 默认启用状态与按需 profile；Codex hook 只写 `~/.codex/hooks.json`，`config.toml` 不重复定义 hook。
- Codex managed-section rewrite 只保留用户 TOML；`codex-mcp` launcher 将 profile 转成单会话 `-c` 覆盖。
- Data Hub 与 Agent Runtime、Skill supply chain 并列；knowledge Skills 调用它，但不属于 `agent/` runtime 配置。
- 真实账号、订阅、token、内网地址、私网 IP、绝对路径和运行状态只属于父仓 `private/`；覆盖规则以 `docs/private-overlay.md` 为准。

## 文档边界

| 文件 | 职责 |
|---|---|
| `README.md` | 用途、首次安装、常用入口与检查命令 |
| `CONTEXT.md` | 架构、公共权威来源、边界与术语 |
| `CLAUDE.md` / `AGENTS.md` | 稳定执行约束 |
| `docs/` | 跨机器复用的专题操作与 runbook |

机制只在一个权威文档详述；其他文档保留必要指针。

## 防漂移

使用 neat-freak 检查：规则按宿主支持的显式入口调用。每次改动检查私有事实是否进入模板、README/CONTEXT/规则/docs 是否按职责分层、清单/脚本/文档是否一致、路径引用是否存在，以及 `AGENTS.md` 与 `CLAUDE.md` 是否同源。

## Issue 与 PR

公开模板工作使用 GitHub Issues/PRs；标题、标签、关联、完成和关闭规则以 `docs/agents/issue-tracker.md` 为准。父子仓发布遵循 child-first、pointer-second；默认分支合并且 checks 与验收证据齐全后，才清理已合并分支，不删除 Issue 历史。
