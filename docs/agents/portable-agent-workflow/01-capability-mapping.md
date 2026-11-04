# Portable Agent Workflow: 能力映射

来源：issue #222（spec `portable-agent-workflow` 草稿，未发布）。本文核对七项
pstack 能力与本仓已安装技能及 registry 分发状态，形成复用/缺口/宿主依赖清单。
基线绑定：父仓 mac-bootstrap @ `e3f4d0d18656856cf5fca201337b11de16727589`，
模板子仓 @ `5871c115ceffde3ba156caaed47b41555396411b`（main，当时分支尚未建立）。

## 核对方法

- 分发权威是 `agent-skills/registry/sources.jsonc` 与 `agent-skills/registry/targets.jsonc`；
  `agent-skills/external/quarantine/` 与各宿主技能入口目录是运行态投影，不是权威
  （见 `../../skill-supply-chain.md`）。
- 已安装技能以 registry 登记（`scripts/skill_supply_chain.py check`：
  skills=141 external=83 internal=58 global=98 project=43 targets=6，退出码 0），
  加上对本机三个技能入口目录的实际盘点交叉验证。
- 上游 pstack 七项能力名称不构成强制安装要求；判定基于能力意图与现有内容比较，
  不能仅凭名称断定缺失。

## 分发机制现状

- pstack 五个技能（`create-verification-skill`、`create-formal-verification-skill`、
  `maintain-verification-skill`、`maintain-formal-verification-skill`、`statechart`）
  位于 quarantine，且在三个本机技能入口（claude/codex/cross-agent）存在指向
  quarantine 的 symlink，但 **均未登记在 sources.jsonc**，quarantine 目录被
  git 忽略。即内容已到位、分发未纳入 registry 治理：reconcile 无法追踪其状态，
  清理逻辑可能将其视为无主链接。
- registry 中与验证流程最接近的登记项 `verification-loop`（everything-claude-code）
  状态为 merged（"merged with eval-loop / verification workflow"），
  `eval-loop` 为 disabled（"User-confirmed drop"）。

## 七项能力判定

| pstack 能力 | 判定 | 现有承载 | 分发状态 | 缺口 / 宿主依赖 |
| --- | --- | --- | --- | --- |
| poteto-mode | 缺口（待核上游语义） | 无同名或近义安装项。registry 仅登记了 poteto-noodle 来源的 `adversarial-review` | poteto-noodle 来源已登记并批准 | 上游语义未核验；按 spec 名称不构成安装要求，先记录不安装 |
| how（理解实现） | 复用 | CBM MCP（search_graph / trace_path / get_code_snippet）+ `agent/rules/common/memory-hierarchy.md` 强制路由 + `search-first`、`documentation-lookup` | 已登记，多宿主目标（claude/codex/opencode/antigravity/cross-agent） | 宿主依赖：CBM MCP 需被宿主挂载（claude 与 codex 已确认 enabled） |
| why（原因分析） | 复用 | `diagnosing-bugs`（诊断循环、先复现）+ `s-skeptic` 对抗评审 + `root-cause-prover` 类子代理 | 已登记分发 | 无特有宿主依赖 |
| architect（架构设计） | 复用 | `improve-codebase-architecture`、`codebase-design`、`domain-modeling`、`archify` + OMP `s-designer` 角色 | 已登记分发 | 无特有宿主依赖 |
| create-verification-skill | 复用内容 + 治理缺口 | 技能内容在 quarantine，三入口 symlink 可用；`docs/agent-subagents.md` 与 OMP `s-planner`/`s-designer` 已引用其 Launch/Doctor/Drive/Evidence/Cleanup 契约 | **未登记 registry** | `disable-model-invocation: true`：仅用户显式触发；缺口是登记/审批（audit + gate），补齐后分发才可被 reconcile 追踪 |
| reflect（复盘） | 复用 | `retro` + OMP `s-retro` + `knowledge-record` / KLM 技能族 | 已登记分发 | 无特有宿主依赖 |
| correct（纠错固化） | 复用（组合承载） | `diagnosing-bugs`（先复现）+ `tdd`（红绿验证）+ caveman 插件族（investigate-first / safe-refactor / verify-and-stop）+ `agent/rules/common/testing.md` verify-the-verification | 组合项均已分发 | 无单一同名技能；若上游语义要求独立技能，需先核验差异再决定 |

## 结论

1. 七项能力中六项可由已安装、已登记的技能或规则承载，不需要安装上游包。
2. 唯一实质缺口是 `create-verification-skill` 一族的 **registry 治理**：内容与
   入口已就绪，缺 sources.jsonc 登记、审计与审批记录。补齐登记属于后续票范围，
   本票只记录不修。
3. `poteto-mode` 是唯一无现有承载的能力，但其上游语义未核验，按 spec
   "名称不构成强制安装要求" 记录为待核验，不安装。
4. 宿主依赖集中在两点：CBM MCP 的挂载（how 类能力）与子代理机制
   （why/architect/correct 的独立复验路径），二者都是宿主能力而非技能内容差异。

## 证据

- `scripts/skill_supply_chain.py check`（模板子仓）：退出码 0，
  `ok skill supply check: skills=141 external=83 internal=58 global=98 project=43 targets=6`。
- registry 解析：`sources.jsonc` 中 31 个来源束、141 项技能无任何 pstack 技能名；
  `.gitignore` 第 27 行忽略整个 `agent-skills/external/quarantine/`。
- 本机入口盘点：`create-verification-skill` 在 claude/codex/cross-agent 三个入口
  均为指向 quarantine 的 symlink。
