# 模板专题文档

本目录保存可跨机器复用的操作说明、机制说明与维护 runbook。当前机器的真实配置、私有地址、订阅和故障差异属于私有父仓，不写入本目录。

## 文档边界

- 模板用途和首次安装：`../README.md`。
- 模板架构与公共权威来源：`../CONTEXT.md`。
- agent 修改模板的约束：`../CLAUDE.md` 与 `../AGENTS.md`。
- 私有 overlay 契约：`private-overlay.md`。
- 父仓本机差异、验收和复盘：父仓根目录 `docs/`。

## 现有专题

- `private-overlay.md`：公开模板与私有父仓的覆盖契约。
- `devspace-local.md`：DevSpace 本地服务、LaunchAgent 与 home mirror。
- `clash-profile-flow.md`：Clash 源配置、profile 与运行态边界。
- `agent-prompt-mcp.md`、`agent-subagents.md`：agent 协作与 prompt MCP。
- `data-hub-record-knowledge.md`：知识记录路径。
- `manual-apps.md`、`shell-startup.md`、`imgup.md`：本机 bootstrap 的通用运维说明。

## 维护规则

1. 文档必须可公开；不得记录真实账号、订阅、token、内网域名、私网 IP 或机器专属路径。
2. 说明权威源、生成物、刷新动作和验证方式，避免读者直接改运行态。
3. 本机差异链接到父仓文档，不复制或反向合并私有细节。
4. `neat-freak` skill（当前 Codex：`$neat-freak`；其他宿主按已注册格式） 应检查路径、命令、链接、标题与脚本行为是否一致，并移除过期或重复说明。
