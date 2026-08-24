# Issue 与 Pull Request 规范

本仓库使用 GitHub Issues/PRs 跟踪公开模板工作。标题服务于列表浏览；
issue 描述可验收结果，PR 描述交付变更和关联关系。

## Issue

- 使用结果导向标题：`[范围] 动词 + 可验收结果`。
- 范围使用稳定领域，例如 `[开发环境]`、`[Agent Runtime]`、`[文档]`。
- 类型、状态、优先级使用 labels，不写入标题。
- 一个 issue 只承载一个可独立验收的结果；创建前搜索相近条目。
- 重复项在评论中写 `Duplicate of #<number>` 后关闭，不创建替代 issue。

示例：

```text
[开发环境] 建立本地容器测试与预览基线
[Agent Runtime] 统一 MCP desired state 与 doctor 检查
```

## Pull Request

- 使用 Conventional Commit 标题：`<type>(<scope>): <summary>`。
- PR 标题描述交付变更，不复制 issue 标题，不把 issue 编号塞进标题。
- 分支使用 `<type>/issue-<number>-<short-slug>`，例如
  `feat/issue-7-local-container-runtime`。
- PR 正文必须声明关系：完整交付用 `Closes #<number>`，前置工作用
  `Refs #<number>`。
- PR 合并到 `main` 后删除 feature branch；merge 不等于发布 tag 或生产发布。

```text
Closes #7
```

## 合并后收尾

- 只有默认分支已包含合并提交、必要 checks 通过、验收证据已记录，才算进入收尾。
- 父子仓按 child-first、pointer-second 完成：先合并子仓 PR，再合并父仓
  submodule pointer；两边都合并后才清理两边的分支。
- linked worktree 或 submodule 中的 pre-push 只执行 repository checks；真实管理 checkout
  才执行 machine checks。Git 上下文清理、Python 复用和真实 push 验收以
  [`quality-gates.md`](quality-gates.md) 为准。
- 收尾同时核对远端与本地：删除已合并 PR 的远端 head branch，prune remote-tracking
  refs，并用 `git branch -d` 删除已验证合并的本地分支；只清理已不存在路径的
  worktree 元数据，不移除活动 worktree。
- 不删除 Issue 历史；已解决 Issue 保持 closed，仍有验收项、阻塞项或活动依赖的
  Issue 保持 open。不得仅因 PR 合并就关闭它。

## 完成定义

只有验收条件满足、必要 checks 通过、PR 已合并到默认分支并记录证据，
issue 才能关闭。跨仓依赖必须写完整 URL，并在原 issue 留下目标 PR；
依赖 PR 未合并时，原 issue 只能保持 open 或标记 blocked。

使用 task list 拆分父任务，使用 milestone 表示交付批次。不要用多个标题
近似、边界重叠的 issue 表示同一结果。

## Wayfinding operations

本节定义 wayfinder / to-spec / to-tickets 技能族在本仓 tracker 上的落法。
GitHub Issues 没有原生父子与阻塞关系，用以下约定表达。技能读取的标签
使用其规范字面量（冒号形式），不套用本仓 type//area/ 前缀词汇：

- **Map**：一个 issue 打 `wayfinder:map` 标签，作为索引不存内容：
  只列已做决策的 gist 与对应 ticket 链接；决策细节只活在它的 ticket 里。
- **Ticket**：map 的子工单为普通 issue，打 `wayfinder:<type>` 标签
  （`research`、`prototype`、`grilling`、`task` 四类之一），
  正文首行声明 `Map: #<N>` 关联父地图。
- **阻塞边**：ticket 正文用 `Blocked by: #<A>, #<B>` 声明（to-tickets 产出）；
  解除后更新该行或删除。`status/blocked` 仅表示被外部因素卡住，
  不用于工单间依赖。
- **Frontier 查询**：当前可做的 ticket =
  `is:open label:wayfinder:task` 且正文无未解除的 `Blocked by`；
  map issue 的评论只记录决策里程碑，不做讨论串。
- **Spec 工单**（to-spec 产出）：打 `ready-for-agent` 标签表示
  可直接进入 implement，无需额外 triage；triage 词汇
  （needs-triage / needs-info / ready-for-human / wontfix）按技能规范原样使用。
- **收尾**：路线清晰后 map 保持 open 直到最后一个 ticket 关闭再关闭；
  决策历史随 ticket 保留，不迁移、不删注释。

## 推荐标签

当前标签以 GitHub live tracker 为准，创建前先确认是否已有同义标签。目标
词汇如下，避免后续出现同义词：

- 类型：`type/bug`、`type/feature`、`type/chore`、`type/docs`
- 范围：`area/dev-env`、`area/agent-runtime`、`area/docs`
- 状态：`status/ready`、`status/in-progress`、`status/blocked`
- 优先级：`priority/p0`、`priority/p1`、`priority/p2`
- 技能工作流（字面量，供 mattpocock 技能族识别）：`wayfinder:map`、
  `wayfinder:research`、`wayfinder:prototype`、`wayfinder:grilling`、
  `wayfinder:task`、`ready-for-agent`
一个 issue 通常使用一个 type、一个 area、一个 status 和一个 priority。
标签迁移应一次性完成，期间不得同时使用新旧同义标签。
