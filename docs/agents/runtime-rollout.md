# Agent Runtime 推广经验与逐仓验收

本文负责 Agent Runtime 的推广顺序、经验教训、逐仓 checklist 与停止条件。运行机制、事件、profile、dispatcher、Git context、repository/machine 分层和安装回滚仍以 [`quality-gates.md`](quality-gates.md) 为权威；具体实施历史和证据保留在 GitHub Issues/PRs。

## 已验证的能力边界

当前公共 runtime 已在 mac-bootstrap 父子仓、普通 Python 仓库、main checkout、linked worktree、submodule checkout 和独立 clone 中完成真实进程级验收。已证明的稳定边界包括：

- 仓库通过 local Git config 显式 opt-in；未启用仓库快速静默放行。
- Git、Claude Code 和 OpenCode adapter 复用同一标准事件、profile 和诊断契约。
- commit 检查 staged snapshot，不因未暂存实验代码误阻断。
- push 前读取真实 ref stdin，首次 push 使用有界 target-path 预算。
- 仓库内 Git symlink 条目可以指向仓库外；通过 symlink 穿透到仓库外子路径仍会被拒绝。
- repository checks 与 machine checks 分层；linked worktree、submodule 和普通 clone 不误跑本机检查。
- trusted Python 来自安装时批准的仓库外路径，并保留 venv 入口，不退化为 base interpreter。
- 父仓 submodule pointer 只有在目标子仓 commit 可从远端获取时才放行。
- 成功路径新增输出为 0 字节；失败反馈有诊断条数和字节预算，完整日志外置。
- install、doctor、uninstall 和旧 hooksPath 恢复均有真实验收。
- local-only playground 根仓已验证无 permanent remote、脏管理 checkout、未初始化 gitlink、嵌套独立仓库和追加式实验资产边界；repository check 只读取 Git index，rollback 后既有软链与未跟踪仓库零变化。

这些证据说明 runtime 已具备逐仓推广条件，但不等于可以未经 inventory 和批准批量启用。

## 关键经验

### 1. 先跑曳光弹，再扩抽象

第一枪只应覆盖一条真实纵向链路：宿主事件、runtime、一个 gate、失败、修复、commit、push、doctor 和 rollback。只有真实链路暴露重复需求后才增加 profile、runner 或 installer 能力。按 transport、engine、migration 横向铺开，会让每个层都“看起来完成”，却没有任何仓库真正可用。

### 2. 进程级测试比内部 mock 更重要

临时真实 Git 仓库、bare remote、linked worktree、submodule 和首次 push 暴露了多项内部单元测试难以发现的问题：

- 新 ref 会从空树计算完整 target paths；
- `post-checkout` 的 old OID 可能是全零；
- gitlink 不能按普通文件 snapshot；
- target path 的仓库条目身份不能用最终 symlink 目标代替，否则合法的本机 skill 路由会被误判越界；
- remote-tracking ref 可能陈旧，不能替代 pre-push stdin；
- 独立 clone、linked worktree 和真实管理 checkout 的本机语义不同。

核心验收 seam 应始终是用户真实执行的 commit/push 和外部可观察状态。

### 3. “仓库形态”不能靠目录猜测

main checkout、linked worktree、submodule、独立 clone 和嵌套仓库必须由 Git 自身解析。策略绑定 common dir，session、锁、diagnostics 和 ledger 绑定当前 worktree。跨仓执行前必须清理调用方 Git local environment，再在目标仓库重新解析上下文。

### 4. 管理 checkout 必须显式声明

“看起来像主目录”不足以运行 machine checks。真实管理 checkout 使用 `agent.runtime.managementCheckout=true` 显式声明；runner 仍需确认当前不是 linked worktree 或 submodule。临时 clone 即使手动标记为 management，也会因本机 symlink 指向 canonical checkout 而正确失败，这属于保护，不应放宽。

### 5. trusted toolchain 必须保留入口语义

venv 入口是信任和依赖边界的一部分。若对可执行路径调用 `resolve()` 并展开到 base interpreter，会丢失 venv 的 site-packages。dispatcher 应保存安装时批准的原始入口路径，runtime 再把它显式传给仓库检查。目标 clone 不应被迫创建自己的 runtime venv。

### 6. 仓库拥有检查内容，runtime 只拥有调用边界

全局 registry 不应硬编码某个项目的 pytest、npm、cargo 或业务脚本。可推广接口是只读、确定性的 `make repo-check`；仓库负责定义 compile、lint、typecheck、test 和 privacy 内容。runtime 只负责选择可信 profile、固定 target、trusted toolchain、timeout、输出预算和 fail-closed 语义。

### 7. 本地门禁不能替代发布仓库的 CI

本地 runtime 用于提前反馈、机械阻塞和审计。存在发布 remote 的仓库仍以 hosted CI、branch protection 和代码评审为最终权威，推广验收必须同时包含本地真实 push 和 hosted CI；二者不一致时先解释差异，不得只挑通过的一边。

显式定义为 local-only、没有发布 remote 的仓库可以将 hosted CI 记为不适用，但仍必须使用临时本地 bare remote 验证真实 pre-push 输入、失败时 ref 不前进、成功时本地与远端 SHA 一致。未来一旦增加发布 remote，必须重新补齐 hosted CI 验收。

### 8. child-first、pointer-second 是可执行规则

父仓 pointer gate 必须读取 index 中的 `.gitmodules` 和 gitlink OID，优先确认 OID 已由配置远端的 ref 公告，未公告时再回退精确 OID fetch。只存在于本机 object database 的子仓 commit 必须阻止父仓提交；子仓先 push 后，同一个 pointer commit 才能通过。工作区中的未暂存 `.gitmodules` 不能改变 staged 语义。

### 9. rollback 要在安装前设计

每次试点先 inventory hooksPath、legacy hooks、Git LFS、profile 和 opt-in，再安装。安装记录必须保留旧 hooksPath 和 approved chain；验收结束后必须实际执行 uninstall 或明确决定保留正式安装。无法写回滚资料时，不应开始替换旧入口。

### 10. 不为凑数量强行选择试点

候选仓库必须真实、有持续用途、可安全创建临时分支，并由用户明确批准。上游工具子仓、发布仓库或高活跃复杂仓库不能因为“手边存在”就被当作普通试点。当前 `tools/SkillOpt` 不默认作为第二个 Python 仓库；`www` 排在最后，且先做只读就绪度评估。

### 11. 工具回传失败不等于 Git 操作失败

长时间检查可能导致调用通道先断开。此时不能盲目重试原生 `git push`；应优先使用 Runtime 安装产物中的 `agent-git-push`，再通过 `--receipt <operation-id>` 或 `--receipt latest` 查询远端成功证据。wrapper 只在 Git 返回 0 且远端 refs 与目标 OID 一致后记录 `push.success`；pre-push 通过、工具回传或本地 SHA 都不能替代 receipt。远端已更新但 receipt 阶段失败时，使用同一 operation ID 恢复，不重复 push。

## 推广风险阶梯

推广总票为 [#57](https://github.com/suainam/mac-bootstrap-template/issues/57)，父 spec 为 [#40](https://github.com/suainam/mac-bootstrap-template/issues/40)。当前执行顺序：

1. [#74](https://github.com/suainam/mac-bootstrap-template/issues/74)：已把 dailycheckin 从 smoke 升级为完整 `python-repository` profile。
2. [#75](https://github.com/suainam/mac-bootstrap-template/issues/75)：已在 local-only `product_strategy` 完成第二个独立 Python 仓库验收，包括真实 commit、临时 bare remote push、symlink 回归修复、doctor 和 uninstall/reinstall。
3. [#56](https://github.com/suainam/mac-bootstrap-template/issues/56)：已提供显式 `push.success` wrapper 和可查询 receipt，解除后续推广对远端成功推断的依赖。
4. [#76](https://github.com/suainam/mac-bootstrap-template/issues/76)：已完成 playground 根仓的 gitlink、无 remote、嵌套仓库和实验资产边界验收；本地恢复 bundle 指向 `464845d`。
5. [#77](https://github.com/suainam/mac-bootstrap-template/issues/77)：下一节点，用可靠 push receipts 支撑低风险 Python 小批量推广和默认 policy。
6. [#78](https://github.com/suainam/mac-bootstrap-template/issues/78)：定义非 Python repository profile 契约。
7. [#79](https://github.com/suainam/mac-bootstrap-template/issues/79)：迁移首个用户批准的低风险非 Python 仓库。
8. [#80](https://github.com/suainam/mac-bootstrap-template/issues/80)：只读评估 www 就绪度，默认不启用。

只有当前节点完成、证据回写并解除后继阻塞后，才给下一个节点添加 `ready-for-agent`。

## 逐仓迁移 checklist

### 1. Inventory

- 记录默认分支、remote、hooksPath、legacy hooks、Git LFS 和现有 opt-in。
- 记录 main、linked worktree、submodule、嵌套仓库和独立 clone 使用方式。
- 识别 push 是否触发发布、部署、数据库写入或真实外部副作用。
- 识别 CI、branch protection、trusted toolchain 和依赖缓存。
- 工作区已有修改、未跟踪文件和实验资产只记录，不清理。

### 2. Repository contract

- 提供只读、确定性的 `make repo-check`。
- 将 machine、GUI、symlink、LaunchAgent、VPN 或硬件检查留在 `machine-check` 或 CI。
- 不在 repo-check 中自动安装依赖、发布制品或修改 tracked files。
- 缺少 target、toolchain 不可信或 timeout 时 fail closed，并给出有界诊断。

### 3. Opt-in 与安装

- 使用 local Git config 显式启用和选择受信 profile。
- trusted Python/toolchain 位于目标仓库之外，且已具备检查依赖。
- inventory 未知 hook 不自动 chaining；明确批准后才复制到 trusted state。
- install 后立即运行 doctor，确认 repository identity、worktree identity、profile、scope、hooksPath 和 rollback record。

### 4. 失败验收

至少制造一个真实、可恢复的失败：

- staged syntax 错误；
- repo-check 中的 lint/typecheck/test 失败；
- pointer 远端不可达；
- runtime/profile/toolchain 配置损坏；
- diagnostics 或 bypass audit 不可写。

阻塞阶段必须 fail closed，HEAD 或远端 ref 不得错误前进。失败输出最多 5 条、约 4 KB，完整日志外置。

### 5. 成功验收

- 修复同一问题，不改变验收条件。
- 完成真实 commit，并使用 `agent-git-push --operation-id <id> ...` 推送临时远端分支；不使用 bypass 或 `--no-verify`。
- 使用 wrapper 的 `--receipt <id>` 核对本地 SHA、远端 SHA、repository/worktree identity 和 refs before/after OID。
- 有发布 remote 时运行 hosted CI，并解释本地与 CI 的任何差异；显式 local-only 仓库记录为不适用，并保留临时 bare remote 的 SHA 证据。
- 成功时 runtime 自身输出 0 字节。

### 6. Closeout

- 再次运行 doctor。
- 删除临时远端和本地分支，prune remote-tracking refs。
- 删除本轮隔离 worktree，不触碰无关 worktree。
- 执行 uninstall 回滚演练，或明确记录为何保留正式安装。
- 核对原工作区状态、hooksPath、opt-in、bypass audit 和未知 hook 均无意外变化。
- 将证据回写子 Issue 和 #57；只在默认分支、适用的 CI、真实验收和清理全部完成后关闭 Issue。

## 指标与推广决策

扩大决策必须使用 `agent-git-push` receipt，不能把 pre-push 通过、Git 命令已启动或工具通道返回当作远端成功。每仓至少记录：

- after.edit、commit、repo-check 和 push 的 p50/p95 延迟；
- 成功新增输出字节和失败反馈字节；
- 重复诊断率、误阻断次数和 bypass 次数；
- legacy hook 冲突、rollback 事件和人工干预；
- hosted CI 与本地 gate 的差异；
- trusted toolchain、依赖缓存和首次运行成本。

最终结论只能是以下之一：

- **扩大**：错误可解释、可回滚、性能和输出预算稳定；
- **继续观察**：能力正确，但耗时、缓存或候选覆盖不足；
- **收缩**：仅保留在特定仓库或 profile，不继续扩展。

不得用平均指标掩盖单个不可解释的数据丢失、hook 冲突或不可回滚事件。

## 立即停止条件

出现以下任一情况，停止扩大并先修复前置能力：

- 不可解释的数据丢失或 tracked/untracked 内容变化；
- 旧 hooksPath、legacy hook 或 LFS 无法恢复；
- repo-check 自动写文件、发布、部署或产生真实外部副作用；
- push receipt 与远端 ref 不一致；
- trusted toolchain 漂移到目标仓库可修改路径或错误 base interpreter；
- linked worktree、submodule 或嵌套仓库选择错误 profile；
- 持续误阻断、同步检查超时或成功路径污染 Agent 上下文；
- 需要常态 bypass 才能工作。

`www` 在全部前置完成前保持未启用；即使就绪度评估给出 go，也必须另开迁移票并再次取得用户明确批准。
