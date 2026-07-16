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

## 完成定义

只有验收条件满足、必要 checks 通过、PR 已合并到默认分支并记录证据，
issue 才能关闭。跨仓依赖必须写完整 URL，并在原 issue 留下目标 PR；
依赖 PR 未合并时，原 issue 只能保持 open 或标记 blocked。

使用 task list 拆分父任务，使用 milestone 表示交付批次。不要用多个标题
近似、边界重叠的 issue 表示同一结果。

## 推荐标签

当前标签以 GitHub live tracker 为准，创建前先确认是否已有同义标签。目标
词汇如下，避免后续出现同义词：

- 类型：`type/bug`、`type/feature`、`type/chore`、`type/docs`
- 范围：`area/dev-env`、`area/agent-runtime`、`area/docs`
- 状态：`status/ready`、`status/in-progress`、`status/blocked`
- 优先级：`priority/p0`、`priority/p1`、`priority/p2`

一个 issue 通常使用一个 type、一个 area、一个 status 和一个 priority。
标签迁移应一次性完成，期间不得同时使用新旧同义标签。
