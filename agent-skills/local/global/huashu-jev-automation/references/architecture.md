# 架构职责分工

外环→感知→内环→生成→直写，各层职责边界。查阅时机：外环编排需要判断把哪类任务交给哪一层时。

| 层级 | 承担方 | 职责边界 |
|---|---|---|
| **外环编排** | 主 Agent (Claude/Codex/OMP) | 目标分解、跨页面流程规划、失败重试决策、敏感提交人机确认 |
| **环境感知** | huashu-chrome | `snapshot`, `read_text`, `network`, `eval`（复用现有登录会话） |
| **内环微决策** | TypeSafe Jev | `Choice` 确定动作与元素映射，`Noul` 检验加载状态 |
| **文本生成** | magpie `group/group-daily` | 纯文本填充字段生成，轻量解耦 |
| **底层直写** | 页面原生 JS API | 腾讯企微表格 `SpreadsheetApp`、富文本编辑器原生 API |
