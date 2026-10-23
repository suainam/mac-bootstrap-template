# Factory Vocabulary

本文件给出一套讨论"agent 软件工厂"的通用词汇，来源于 mattpocock/skills#1316（draft，未合并）的 glossary 部分，去掉了它的教学语气，只保留术语与本仓映射。它是词汇约定，不是 skill、不注入模型上下文。

用这套词讨论工厂设计时，避免同义词漂移：`job`/`workflow`/`action` 一律说 **task**；`session` 一律说 **run**；`server`/`host`/`box`/`sandbox` 一律说 **runner**；`issue tracker`/`project board` 一律说 **ticket tracker**；`dispatcher`/`scheduler`/`control plane` 一律说 **orchestrator**。

## Tasks and runs

- **Task**：一类工作（review、explore、implement、ratchet），定义一次、运行多次。可作用于 ticket、PR 或整个 codebase。
- **Trigger**：启动一次 run 的事件——ticket tracker 或 git host 的变更、orchestrator 的时钟、或另一个 run。
- **Run**：一个 task 在一个 runner 上的一次执行，从 trigger 到结束，视为黑盒。run 通过 orchestrator 逻辑、或通过写 ticket tracker / git host 来触发后续 run。**run 永不等待人类**：它结束，人类后续的变更触发新的 run。
- **Runner**：run 执行的一次性机器。runner 上没有任何东西能活到下一个 run；run 对历史的唯一记忆是 ticket tracker、git host 和 orchestrator。

## Services

工厂 = 一组 service 槽位 + 让工作在它们之间流动的 task。每个槽位由一个产品填充；一个产品可以占多个槽位，一台服务器可以承载多个 service。术语命名角色，不命名机器。

- **Ticket tracker**：ticket 的存放地，工厂的人类界面。人类通过开 ticket 安排工作、在评论里和 agent 对话，对 ticket 的变更触发 run。
- **Ticket source**：工厂之外、向 ticket tracker 写 ticket 的任何东西——反馈按钮、监控、错误上报、收件箱。
- **Git host**：分支、PR、review 的存放地。
- **Orchestrator**：接收 trigger、在 runner 上启动 run、记录哪些 run 在排队/在飞/已结束的组件。
- **Observability platform**：runner 把日志、trace、状态发到的地方，让人能看到每个 run 内部发生了什么。可选：占据 runner 或 orchestrator 槽位的产品往往自带足够界面。run 永不直接决定写它，直到有东西写进 ticket tracker 或 git host。

## 设计准则

**Start slow**：每个 trigger 都是加速器。没有刹车的加速器 = slop cannon。三种刹车：

1. **Automated checks**：每次 run 必须过的确定性门禁（类型、lint、测试）。
2. **Automated review**：另一个 run 冷读 diff，对照本仓标准与 ticket。
3. **Human review**：人读 PR 才合并；它抓到的东西转化为新的 automated check 与更严的 automated review。

一次只加一个自动化 trigger，先节流（十条 bug report 取一条、时钟一天一次），每个 PR 都过人。刹车赢得信任后再放开，任何 run 循环都设重试上限，超限交还给人。

**Fill every slot**：每个 service 是一个槽位，填一个产品。优先买现成的 ticket tracker——它稳定、别人已经会用、放外部用户进来容易。买 service，自己写 task：task 承载你的设计，service 是通用的。

**Question every task**：对每个 task 回答五问——什么触发它？它做什么、读写哪些 service？它接着触发什么？人类在哪重新介入？什么阻止两个 run 做同一份工作？对每个 ticket source 回答一问：什么阻止它把同一张 ticket 开两遍？

设计完成的判据：每个槽位命名了产品（observability 可以是有意的"无"），且每个 task 和 ticket source 对上述问题都有答案。

## 本仓映射

| Slot | 现状 | 缺口 |
|---|---|---|
| Ticket tracker | GitHub Issues（template 仓 + 父仓） | — |
| Ticket source | 无 | **空槽**：无反馈按钮/监控自动开 ticket |
| Git host | GitHub | — |
| Orchestrator | Herdr pane + Dispatch（`dispatchctl`） | 时钟 trigger 未接入 |
| Runner | 本机 git worktree / herdr pane | **不符合定义**：runner 非一次性，状态在 run 间存活 |
| Observability | OMP session log、`agent://` / `history://` | 无独立 tracing 平台，依赖 runner/orchestrator 自带界面 |

刹车现状：automated checks = `make check` / CI `make ci`；automated review = `code-review` skill 与本仓 review 流程；human review = PR 人工合并门禁。

## 边界

本文只统一词汇与本仓映射。不引入上游 skill（draft 且 user-invoked），不复制它的槽位调研文档（内容为 2026-10 调研，时效性强，需要时直接去上游 `skills/in-progress/software-factory/` 读）。
