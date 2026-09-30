# Diamond Orchestration & Dispatch Integration

The **Diamond Model** (governed by `mac-bootstrap/AGENTS.md`) is the upper-level architectural governance pattern; **Dispatch** is the underlying execution and transport engine.

Together they form a closed-loop engineering system:

```text
                  【 User + Orchestrator 】
                             │  
                             ▼  [1. Top Apex: Planner]
                      ┌───────────────┐
                      │ 方案研讨与对齐 │   ← Occam Gate 极简门禁
                      │ 确认验收标准  │   ← 人类授权后方可发散
                      └───────┬───────┘
                              │
             ┌────────────────┴────────────────┐
             ▼  [2. Divergence: Researchers / Writers]
      ┌────────────────┐               ┌────────────────┐
      │ Researcher     │               │ Writer         │
      │ (只读探针)      │               │ (实现变更)     │
      │ • 免 Worktree  │               │ • 独立 Worktree│
      │ • Print Mode   │               │ • Two-Step 握手│
      │ • 输出事实与行号│               │ • .dispatch/   │
      └──────┬─────────┘               └───────┬────────┘
             │                                 │
             └────────────────┬────────────────┘
                              ▼  [3. Convergence: Skeptic]
                      ┌───────────────┐
                      │ Skeptic Lane  │   ← 必须全新独立上下文（新 Pane）
                      │ (对抗性审查)   │   ← 拦截假 DONE、抓断言漏洞、对齐文档
                      └───────┬───────┘
                              │
                              ▼  [4. Bottom Apex: Human Gate]
                      ┌───────────────┐
                      │  Human Gate   │   ← 仅管发布、git push、PR 合并等高风险动作
                      │ (人类哨卡决断) │
                      └───────┬───────┘
                              │
                              ▼
                      【 PR 合并与 Closeout 清理 】
```

---

## 1. Role-to-Primitive Mapping

| Diamond Role | Execution Primitive | Worktree Needed? | Output / Handoff |
| :--- | :--- | :--- | :--- |
| **Planner** | Orchestrator (Main Session) | 否（在主仓思考与制定计划） | 任务规划表、验收标准、拆分 $\le 3$ 支 $\le 2$ 轮 |
| **Researcher** | Non-interactive Print Mode (`opencode run --auto` 或 `agy -p`) | **严禁创建**（零污染、0 秒直出） | 证据行号、结构化事实，直接注入 Orchestrator 上下文 |
| **Writer** | Isolated Worktree (`herdr worktree create`) | **必须创建**（一文件一 Writer，单 Lane 单分支） | 提交代码到特性分支，更新 `.dispatch/progress.md` 与 `DONE` |
| **Skeptic** | Independent Pane + Worktree Reviewer | 挂载到 Writer 的 Worktree（或只读对比） | **必须拥有全新独立上下文**（绝不复用 Writer Pane），独立跑测试、查断言、对齐文档 |
| **Human Gate** | Orchestrator 呈报给用户 | 否 | 用户最终确认授权 `git push`、PR 合并与物理清理 |

---

## 2. Invariants & Battle-Tested Rules

### 1. Worktree 隔离红线意识（最高优先级铁律）
- **反模式警示**：绝对不能将任务误判为“纯查验/改 Secret 的 Ops 运维任务，不修改本地源码”，而偷懒在主仓库根目录下直接开 Pane 裸跑！
- **危害**：持续交互式 Agent 会随时拉取依赖、生成临时文件、写入构建缓存，甚至在误操作时污染主分支或引发 Git 脏状态。
- **绝对红线**：
  - **纯只读探索（Researcher）**：严禁启动持续交互式 Agent，必须一律走非交互 Print 模式（`opencode run --auto` 或 `agy -p`），0 污染秒级直出。
  - **持续交互 Agent（无论 Writer、Skeptic 还是 Ops/配置任务）**：严禁在当前主分支裸工作区运行，必须一律强制创建独立 Worktree（通过 `herdr worktree create` 挂载到 `.worktrees/` 隔离目录）！

### 2. 跨 Agent 动态协调（Orchestrator 核心价值）
- **管道输送**：Orchestrator 负责多工种之间的产出流转。例如提取 Lane A（如 OpenCode）探查出的有效节点与配置，加工后喂给 Lane B（如 Agy）消费执行。
- **全局故障定位**：当 Worker 遇到跨系统阻断（如 GitHub Actions 失败、网络连接拒绝），Orchestrator 需利用全局视角排查历史残留变量（如 `CHECKIN_PROXY_URL` 屏蔽），指导子 Agent 纠偏。

### 3. 网络与代理环境变量防御性隔离
- **风险**：本地未联通或残留的代理环境变量（`http_proxy`/`https_proxy`/`all_proxy`）会导致 `gh` CLI 或 Git 网络交互遭遇 TLS handshake timeout。
- **防御实践**：在需要直连 GitHub 或内网服务时，必须防御性地使用 `env -u http_proxy -u https_proxy -u all_proxy <cmd>` 剥离脏代理环境。

### 4. Skeptic 独立性原则
- 审查 Agent 必须在独立的 Herdr Pane 启动，拥有干净的上下文。
- 绝不可让 Writer Agent 自己审查自己的代码（防止上下文幻觉惯性覆盖真实错误）。

### 5. 汇聚门禁 (Merge Gate) 与人类哨卡
- 关键分支（Core Branch）失败必须立刻停止合并；非关键分支若证据不足，标记待决断，严禁猜测。
- 所有外部网络外泄、代码发布、`git push`、PR 合并、生产机器写操作，必须经 Human Gate 明确授权。

---

## 3. Doc-as-Code (代码即文档) 闭环与 Curate 门禁

任何工程变更在进入 Human Gate 决断之前，必须完成**代码即文档**的权威一致性对齐（调用 `curate-repo-knowledge`）：

1. **契约文档对齐**：
   - 源码、端口、环境变量发生变动时，必须同步更新权威真源（`CONTEXT.md`、`ports.yml`、`README.md`），杜绝文档漂移。
2. **决策证据沉淀**：
   - 审计排查、故障治理、服务退役等重大技术决策，必须将过程分析归档沉淀至 `docs/archive/<topic>.md` 或生成正式 ADR。
3. **Handoff 专属落盘与 Notify-Back 绑定**：
   - 每个 Lane 完成验证后，必须在 `~/Documents/handoffs/` 生成标准移交文档：
     `~/Documents/handoffs/${REPO_SLUG}-${NAME}-handoff-$(date +%Y%m%d).md`
   - Notify-Back 必须严格包含核心一句话结论与该 Handoff 文件路径：
     `\n[NOTIFY] [<pane_id>_<agent_kind>_<repo_slug>] <核心结论总结> | Handoff: ~/Documents/handoffs/<file>.md`

---

## 4. 单一真源 (SSOT) 维护原则

`dispatch` 技能及其附属执行脚本、配置、模板在仓库内部**只维护一份绝对真源**（`template/agent-skills/local/global/dispatch/`）：
- 严禁跨目录反向复制代码文件或在外部建立多余的快捷软链接；入口一律通过 skill 及其自包含的 `scripts/` 访问；
- 任何流程演进与优化只需就地修改真源，一次改动全局生效。
