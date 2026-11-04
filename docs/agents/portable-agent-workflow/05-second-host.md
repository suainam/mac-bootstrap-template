# Portable Agent Workflow: 第二宿主复跑与推广决定

来源：issue #226（spec `portable-agent-workflow` 末票）。在 #222–#225 的单宿主
链路之上，于第二宿主复跑同一任务契约，检查技能分发边界，记录监督成本，
并发布采用/暂缓结论。本文只记录实际执行的事实；未执行项按
`02-verification-flow.md` 的判定语义记 BLOCKED，不以文档宣称作执行。

## 复跑前提（与首宿主共享的契约）

- 基线：父仓 `e3f4d0d18656856cf5fca201337b11de16727589`（main，主检出），
  模板子仓 `622566d069cb786dd89aa4666d12f51c66672581`
  （`feat/portable-agent-workflow`，本票起始 HEAD，即 #225 交付）。
- 任务契约：与首宿主相同的五条验证命令——模板 `./scripts/privacy-audit.sh`、
  模板 `skill_supply_chain.py check`、父仓 `make doctor`、父仓
  `make doctor-agent`、模板 pytest（`test_agent_doctor_status.py` +
  `test_agent_doctor_config.py`，即 #223 修复与 #225 守卫的测试面）。
- 判定语义与证据契约：`02-verification-flow.md`（PASS/FAIL/BLOCKED 三分、
  fail-loud、unverified_checks）。复跑不修代码、不改文件、不 push。
- 独立复验规则：`03-independent-review.md`——审阅者（首宿主会话）不信任
  第二宿主的结论，只复用其命令清单，以自测的退出码与输出逐条对照。

## 第二宿主可行性核查（实测）

| 宿主 | 非交互入口 | 实测结果 |
| --- | --- | --- |
| Codex CLI 0.166.0 | `codex exec --sandbox read-only "<prompt>"` | 可行。首次探测被账号配额拦截（`You've hit your usage limit ... try again at 9:06 PM`），21:26 重试成功（探测消耗 27,608 tokens，含宿主加载 AGENTS.md 等上下文的开销） |
| OpenCode v2.2.5 | `opencode run [--model <m>] "<prompt>"` | 可行，但默认模型（`opencode/*-free`）均报 `Free usage limit reached`；切换 `cloudflare/@cf/nvidia/nemotron-3-120b-a12b`（同为免费层）后可用 |

结论：两个第二宿主都具备真实的非交互执行能力。默认模型配额是当时的
环境事实（非流程缺陷），复跑依赖当时可用的模型配额——这一依赖本身
记入推广决定的支持边界。

## 复跑一：OpenCode（真实执行）

命令（任务契约全文写入临时文件后作为 prompt 传入）：

```bash
opencode run --model cloudflare/@cf/nvidia/nemotron-3-120b-a12b "<任务契约>"
```

- 运行约 3 分钟，原始日志 644 行（含五条命令的完整输出），保存在
  `/tmp/paw226/opencode-run.log`，不入库。
- 五条命令全部实际执行，退出码与首宿主当日基线逐条一致：

| 命令 | 退出码 | 第二宿主判定 | 首宿主复验对照 |
| --- | --- | --- | --- |
| 模板 `./scripts/privacy-audit.sh` | 0 | PASS | 一致（`privacy-audit: ok`） |
| 模板 `skill_supply_chain.py check` | 0 | PASS | 一致（skills=141 ... targets=6） |
| 父仓 `make doctor` | 0 | PASS | 一致（`Doctor passed.`） |
| 父仓 `make doctor-agent` | 2 | FAIL | 一致：仅 Codex/OpenCode 两处 `MISS AGENTS.md canonical rules content`，无 `unbound variable` |
| 模板 pytest 两文件 | 0 | PASS | 一致：`26 passed`（#225 守卫测试在第二宿主上独立转绿） |

- 证据质量复核（按 `03-independent-review.md`，首宿主为审阅者）：第二宿主
  如实报告了 `doctor-agent` 的 MISS 原文并给出 summary 表与 unverified
  检查清单，符合证据契约。发现一处根因分类偏差：它把 AGENTS.md MISS 归类
  为 defect；按 #222 起的既定分类该 MISS 是本机宿主指令内容 drift（private
  overlay 范畴），不是代码缺陷。表格层判定（FAIL）正确，退出码不受影响；
  记为 1 次判定核对，未触发退回重跑。

## 复跑二：Codex（真实执行，只读沙箱）

```bash
codex exec --sandbox read-only "<同一任务契约>"
```

- 全程 34,275 tokens（codex 自报）。五条命令全部尝试，判定
  `2 PASS / 1 FAIL / 2 BLOCKED`：

| 命令 | 退出码 | 第二宿主判定 | 首宿主复验对照 |
| --- | --- | --- | --- |
| 模板 `./scripts/privacy-audit.sh` | 0 | PASS | 一致 |
| 模板 `skill_supply_chain.py check` | 0 | PASS | 一致 |
| 父仓 `make doctor` | 2 | BLOCKED | 首宿主实跑为 0；差异源于沙箱拒绝 Homebrew 临时文件/锁写入（`Operation not permitted`），非被测代码差异 |
| 父仓 `make doctor-agent` | 2 | FAIL | 退出码一致；沙箱内额外出现 `MISS Context7 private config or permissions` 与内嵌 `FAIL skill supply-chain check`（后者根因即 `agent-doctor.sh:462` 的 /tmp 写入被沙箱拒绝）。两症状在沙箱外的首宿主与 OpenCode 复跑均未出现，判为沙箱环境影响 |
| 模板 pytest 两文件 | 1 | BLOCKED | 首宿主实跑为 0；pytest 在测试收集前死于 `No usable temporary directory found`（沙箱拒绝临时目录写入） |

- 正向证据：Codex 拒绝把沙箱拒绝执行的项目报成 PASS，按
  `02-verification-flow.md` 语义给出 BLOCKED 并写明原因——fail-loud 与
  「缺依赖不得报 PASS」在第二宿主上得到行为级验证，而非仅文档约定。
- Codex 还如实报告主检出非干净（父仓 `ssh_config` 既有改动、子模块指针
  变动、2 个未跟踪 analytics 草稿），与实际 git status 一致；其 `tested_commit`
  字段主动声明 not clean，符合证据契约对实例状态的披露要求。

## 分发边界检查（registry/quarantine/distributor/reconcile）

只读盘点 + dry-run 预演，未修改任何运行态：

- 第二宿主技能入口实测：`~/.codex/skills` 55 项、`~/.config/opencode/skills`
  54 项，全部为指向模板 checkout 的 symlink，来源覆盖 `local/global`、
  `local/shadows`、`external/quarantine` 三类（与 registry 权威模型一致）。
- 工作流相关技能可达性：`ponytail`、`caveman`、`find-skills`、
  `documentation-lookup`、`search-first`、`grilling`、`ste` 在两个第二宿主
  入口均有指向模板的 symlink（`ls` + `readlink` 实测）。通用技能只维护
  一处（模板 checkout），第二宿主入口是投影，未复制。
- 再分发入口（仓库自支持）：`make skill-refresh`（= skill-check +
  ensure-bundles + skill-distribute，Makefile 4.21）与 `make agent-sync`
  （skill-refresh + prompt-sync）；`scripts/skill-refresh.sh --dry-run` 提供
  预演。本票运行了 dry-run 全套，未运行实际分发——当前投影已一致，无需。
- dry-run 实测：`skill_supply_chain.py distribute --dry-run` 共 322 个动作，
  其中 46 个指向 `~/.config/opencode/skills`（ste、find-skills、typesafe-ai
  等均幂等重建）；`reconcile --dry-run` total=57 removable=41
  skipped_real_paths=16。removable 集中在 reasonix/antigravity 未启用入口
  与 pstack 五技能（未登记 sources.jsonc，`#01-capability-mapping.md` 已
  记录的治理缺口，状态未变）；没有任何动作指向本工作流的五篇文档所
  依赖的已登记技能。
- 已知限制：`skill-refresh.sh` 是 bash 脚本，须以 bash 执行（用 venv python
  直接调用会 SyntaxError）；在系统 python 3.9 下脚本 import 失败
  （`type | None` 语法），须用 `.venv/bin/python`——均已在实测中确认并
  规避，未修脚本（非本票范围）。

## 监督成本记录

| 票 | 子代理/第二宿主 token | 修正轮次 | 备注 |
| --- | --- | --- | --- |
| #222 | 75k | 0 | 记录值（orchestrator 交接），宿主未逐票计量 |
| #223 | 96k | 0 | 同上 |
| #224 | 56k | 0 | 同上 |
| #225 | 89k | 0 | 同上 |
| #226 本票 | OpenCode 复跑约 30–40k（宿主未报告，按 Codex 同任务 34.3k 推断，估计值）；Codex 复跑 34,275 + 探测 27,608（codex 自报）；首宿主编排会话未计量（量级估计，标注为估计值） | 重跑退回 0 次；判定核对 1 次（OpenCode drift/defect 分类，首宿主复核纠正，无需重跑） | |

- 人工介入：执行期 0 次（任务整体委派给子代理，无人工纠偏）。环境事件
  2 起，均为等待/重试而非人工决策：安全分类器临时故障（`group/group-daily`
  不可用约 20 分钟，恢复后重试成功）；两宿主模型配额窗口（Codex 21:06 后
  恢复，OpenCode 切换免费模型）。
- 墙钟：#222–#225 同日 18:14–20:25 提交跨度约 2 小时 11 分；#226 约
  45 分钟（含约 20 分钟分类器故障等待）。
- 模型可用性：GPT-6.1 Terra 全程不可用（#222 起实测未变）；第二宿主默认
  模型受当日配额限制。

## 采用/暂缓决定

结论：**采用（有界）；无人值守并行维持暂缓**（未过关不得进入，per spec
与 issue #226 验收项）。

已证明（证据绑定上表与 #222–#225 各文）：

- 单宿主完整链路：基线 → 验证流程 → 独立审阅与退回 → 回归守卫，
  含 #224 三次注入与 #225 红绿复演。
- 守卫拦截有效：#225 守卫测试在第二宿主（OpenCode）上独立转绿（26 passed）。
- 第二宿主可真实非交互执行并交付符合证据契约的包：OpenCode 全量五命令
  且退出码与首宿主逐条一致；Codex 五命令且 BLOCKED 语义行为级正确。
- 分发边界：registry → 两第二宿主入口的 symlink 投影实测可达，dry-run
  分发/清理可预演，通用技能单处维护成立。

未证明（保持 BLOCKED/未执行，不得写成通过）：

- 第二宿主在干净检出（worktree + 本地克隆）上的复跑：两次复跑均用主
  检出；#223/#224 已定义该流程，本票未在第二宿主上重复执行。
- GPT-6.1 Terra 验证：模型不可用，#222 起未变，未替换模型。
- 无人值守并行与定时接单：spec Out of Scope，本票不进入。
- 模型等价性：第二宿主复跑使用免费层模型（nemotron-3-120b-a12b），
  判定质量弱于首宿主（一次 drift/defect 误分类）。跨宿主结论以退出码等
  硬证据为准；弱模型只承担执行与如实报告，不承担根因裁决。

支持边界与回退：

- 支持面：纯文档流程（本目录五篇）+ 既有 registry 分发与 make 目标；
  无新增运行态、无新依赖、无新技能。第二宿主复跑依赖当时的模型配额
  与非交互入口（`codex exec` / `opencode run`），这是环境前提，不是本仓
  可保证的 SLA。
- 回退：revert 本票文档提交即完全回退（文档票，无代码/运行态改动）；
  整个 spec 的回退同理（#223 的 shell 修复除外，它由独立测试守护，
  回退 spec 不建议连带回退该修复）。
- 进入无人值守并行的前置条件（下次运行可复验）：干净检出第二宿主复跑、
  Terra 或用户另行指定的模型验证、并行任务的独立审阅闭环，各至少一次
  实测通过。

## 验收项判定（issue #226）

| 验收项 | 判定 | 说明 |
| --- | --- | --- |
| 第二宿主以同一基线、任务契约与验收条件复跑并独立复验 | PASS | 基线/契约/验收与首宿主相同并显式传入；OpenCode 全量五命令一致，Codex 沙箱受限项如实 BLOCKED；独立复验由首宿主按 `03-independent-review.md` 完成（退出码逐条对照）。注：本票无代码实现面，「实现」即证据包交付 |
| 通用技能只维护一处；新增宿主适配按 registry/quarantine/distributor/reconcile 验证，不直接改运行态 | PASS | 只读盘点 + dry-run 全套实测；未运行非 dry-run 分发/清理；pstack 未登记缺口为 #01 已知状态，未变 |
| 记录人工介入、修正轮次、运行时间及实际成本或估计来源 | PASS | 见监督成本记录；估计值均已标注来源 |
| 发布采用/暂缓结论、支持边界与回退；未过关不得进入无人值守并行 | PASS | 采用（有界）；无人值守并行维持暂缓并给出前置条件 |

## unverified_checks（本票）

- 第二宿主在干净检出上的复跑未执行（两次均为主检出）。
- GPT-6.1 Terra 未验证（模型不可用，未替换）。
- Codex 沙箱下 `MISS Context7 private config or permissions` 的根因未深挖：
  沙箱外两次复跑（首宿主、OpenCode）均无此症状，判为沙箱环境影响，记录不修。
- OpenCode 复跑与首宿主编排会话的 token 数无宿主报告，为推断/量级估计。
- 非 dry-run 的 `skill-refresh`/`reconcile` 未运行（当前投影一致，无需；
  其安全性以 dry-run 输出为准——无 real-path 删除动作涉及本工作流技能）。
- 全量 `make check` 本票未重跑（#223/#224 已实测已知 4 项 external tools
  drift；本票为文档票，模板侧以 privacy-audit + check_docs + supply check
  + 相关 pytest 为最小相关验证）。

## 证据包

- `tested_commit`：父仓 `e3f4d0d`（主检出，非干净——ssh_config 与子模块
  指针为既有私有改动，Codex 复跑已如实披露）；模板 `622566d`
  （`feat/portable-agent-workflow`，2 个未跟踪 analytics 草稿为 #223 起的
  既有状态）。本票新提交仅增加本文档，不改变被测代码。
- 命令与退出码：见前两表；原始日志在执行机 `/tmp/paw226/*.log`
  （`opencode-run.log`、`codex-run.log`、`distribute-dry.log`、
  `reconcile-dry.log` 等），不入库。
- 复现方式：在绑定提交上以本文两条第二宿主命令重跑，对照退出码表与
  MISS 明细。
