# 编排者实战总结：真实多 Agent 协作中的 6 大致命陷阱与插件化优化 Issue 提案

在本次 `nat-hk96` 生产交付与 `dispatch` 插件化落地的全流程中，我们经历了从多 Agent 内存爆炸、进程崩溃、状态机催促死循环、通信坐标错乱，到静默剔除陷阱的完整实战。

作为编排者，我在此沉淀出 **6 大核心教训**，并直接转化为面向 `herdr-plugin-dispatch-omp` 插件的 **具体优化 Issue 提案**，供后续持续演进。

---

## 一、本次实战踩出的 6 大核心教训 (Battle-Tested Lessons)

### 1. 虚假忙碌与催促死循环 (The Todo Reminder Trap)
- **现象**：子 Worker 在后台长任务执行时，底层系统每轮都会弹出“You have open todos”的催促提醒，导致编排者误以为“自己必须动手做点什么”，从而开始疯狂探状态、烧光 Token。
- **根因**：编排器自身行为在 Todo 中“无状态且隐形”。
- **解法**：建立**双层 Meta-Todos 机制**（`Phase 0 编排器大脑状态机` + `Phase 1 业务车道`）。派发后主动将编排器任务置为 `blocked`，直接掐断催促循环。

### 2. 多 Agent 宿主机内存暴涨与系统斩杀 (Host Memory Avalanche)
- **现象**：`1-1` 积累到 37.4 万 tokens 时，单个进程物理常驻内存高达 2G~3.5GB，直接被 macOS 内核执行了 `zsh: killed (SIGKILL)`。
- **根因**：Agent 对话上下文单调无界增长，多 Agent 并发的乘数效应打爆了宿主机物理内存。
- **解法**：阶段性**追加式剔除 (Pruning via ContextEditEntry)** 强制剥离历史命令回显；硬超限时触发 **Session 紧凑换代 (`/new` + 状态落盘断点恢复)**。

### 3. 通信坐标错乱与占位符泄漏 (Coordinate Misrouting)
- **现象**：由于 Pane 重命名或局部调整，提示词中残留 `<orch-pane>` 或旧坐标（如误发往 `w3:p3`），导致子 Worker 报文发错位置甚至打扰人类。
- **解法**：编排器派发前必须动态求值真实坐标 `ORCH_PANE="$(herdr pane current | jq -r '.result.pane.pane_id')"`，强制硬编码注入真实物理字面量（如 `w3:p1`）。

### 4. 进度黑盒与焦虑 (Black-box Execution Anxiety)
- **现象**：子 Worker 执行长达 10~15 分钟的排查时，没有中间反馈，编排者和人类无法分辨它是“在健康推进”还是“已经死锁”。
- **解法**：确立 **`[HEARTBEAT]` 轻量阶段心跳契约**，静默刷新侧边栏 Token（如 `s4@hk216`）并重置看门狗，不打断挂起态。

### 5. 提前关闭 Worker 导致收尾断裂 (Premature Pane Destruction)
- **现象**：功能跑通后，编排器急于释放内存提前关闭了 `1-3`，导致后续的“子仓推送、父仓指针更新、分支清理”标准收尾动作断层。
- **解法**：将**标准收尾生命周期 (Closeout Lifecycle)** 固化为不可跳过的硬门禁。只有在 PR 合并入 main 且验证干净后，才允许发出关闭信号。

### 6. 运行时被静默剔除的逻辑陷阱 (Silent Deletion in Resolver)
- **现象**：Ansible 的 `resolve_sub_store_providers.yml` 会在循环中无条件删除与 NAT 主机同名的 provider，导致配置明明写了，运行时却凭空蒸发。
- **解法**：任何动态解析器必须具备 fail-loud 告警机制，不能依赖隐式的自引用字典合并。

---

## 二、转化为 `herdr-plugin-dispatch-omp` 的 4 项具体优化 Issue 提案

请将以下 4 个 Issue 提案正式提交至 `suainam/mac-bootstrap-template` 仓库进行长期跟踪优化：

### 提案 1：[Feature] 插件内置 Phase 0 编排器大脑状态机与 Todo 拦截守卫
- **背景**：解决编排者在子任务运行期的虚假忙碌与抢活反模式。
- **范围**：
  1. `dispatch` 启动时，自动向宿主会话注入标准的 Phase 0 编排器元任务结构；
  2. 扩展内部自动拦截 `todo_reminder` 事件，在 `yield_and_guard` 状态下自动将待办置为 blocked，杜绝底层无脑催促；
  3. 收到标准 `[NOTIFY]` 唤醒后，自动将状态机推进至下一阶段。

### 提案 2：[Feature] 引入宿主机内存压力感知与 Session 紧凑轮换机制 (/new + Checkpoint)
- **背景**：防止多 Agent 并行打爆宿主机内存导致被系统 `SIGKILL`。
- **范围**：
  1. 插件在宿主机层面监控可用物理内存，当低于预警线（20%）时自动限制并发重量级 Agent；
  2. 当单 Agent 上下文突破 15 万 tokens 时，自动触发优雅换代：将现场事实落盘为 `.dispatch/CHECKPOINT.json`，执行 `/new` 开启轻量新会话并通过断点恢复。

### 提案 3：[Enhancement] 固化 [HEARTBEAT] 阶段心跳机制与侧边栏 Token 动态刷新
- **背景**：解决长任务执行期的黑盒状态，消除人类等待焦虑。
- **范围**：
  1. 在 `protocol.md` 中将 `[HEARTBEAT]` 设为标准规范；
  2. 扩展利用 `deliverAs: "aside"` 静默接收心跳，刷新 `ORCHESTRATOR_STATE.json` 与侧边栏徽标（`dstate`）；
  3. 自动重置单车道 10 分钟停滞看门狗，避免误判卡死。

### 提案 4：[Governance] 固化全流程标准收尾生命周期 (Closeout Lifecycle Gate)
- **背景**：杜绝“功能做完就提前关闭 Worker”导致子仓未推送、指针未更新、worktree 残留的烂尾现象。
- **范围**：
  1. 将“权威文档对齐、子仓分支推送、父仓指针更新、PR 合并、Worktree 物理清理”作为标准的 Phase 5 收尾门禁；
  2. 只有在收到 `[NOTIFY] Closeout Complete` 且父子仓 `main` 均已同步最新提交后，插件才允许执行 `herdr pane close` 回收面板。
