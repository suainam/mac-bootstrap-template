---
name: full-stack-story-standardization
description: 科技门户全栈单申报与效能平台 Story 规范化五步流水线：命名与四岗认领、方案与数仓隔离、PRD 85+ 直写、Task 三栏工时拆解、测试平台阶段流转。用于全栈 Story 规范化改造、跨三岗积分申报、PRD 评分提升。
---

# 全栈 Story 规范化五步流水线

把一个已拆好的 Story 做到可申报全栈单：标题合规、四岗本人、方案与验收可观测、PRD 达标、Task 工时均衡、测试流转闭环。

## 积分规则基准

| 规则项 | 参数 |
|---|---|
| 每单分值 | 跨三岗 **+10**；跨二岗 **+8** |
| 跨三岗覆盖 | 需求负责人 + 后端 + 前端 + 测试 |
| 计分上限 | 单月最多 5 单、最高 50 分；超出仅累计全栈总单数 |
| 评审流程 | AI 自审 → 架构师评审 → 全栈委员会终审 |

## 流水线

```mermaid
graph LR
    S1["1 命名与四岗"] --> S2["2 方案与隔离"] --> S3["3 PRD 85+"] --> S4["4 Task 三栏"] --> S5["5 测试流转"]
```

### 1. 命名与四岗认领

标题以 `【开发全栈】` 开头，后接业务范围。一个 Story 只写一个业务范围，区域或批次不混写。

四岗在 ai-devops 人员计划里逐个认领：需求负责人、前端、后端、测试。控件交互与人员搜索见 `skill://story-decompose-ai-devops`。

**完成标准**：标题前缀正确且只含单一范围；四岗四格都回读到本人，无空格。

### 2. 方案与数仓隔离

- 探针、测算、临时表只写开发临时库，不写生产 ADS/DWS。
- 生产链路只引用最终规则产物，不改上游模型原生计算。
- 验收必须给出同快照基准数据集定义，以及 `FULL OUTER JOIN` 差集为 0 的可观测 SQL。

**完成标准**：Story 正文能指出每个中间结果的落库位置，且验收条款含明确的快照定义与差集判定。

### 3. PRD 85+

用 `huashu-jev-automation` 的 `scripts/prd_workbench.mjs`：

```bash
node ~/.agents/skills/huashu-jev-automation/scripts/prd_workbench.mjs audit <story_prd.md>
node ~/.agents/skills/huashu-jev-automation/scripts/prd_workbench.mjs save --tabId <id> --file <story_prd.md>
node ~/.agents/skills/huashu-jev-automation/scripts/prd_workbench.mjs score --tabId <id>
```

三条格式硬约束：

1. 章节标题用全角括号：`### 边界场景（edge_cases）`、`### 量化目标（baseline→target）`。
2. `### 每个功能的详细说明` 下 `#### N.` 与 `### 功能点列表` 一一对应。
3. 数据模型不写「示例」「依契约」「待定」。

**真源过滤**：评审器常对离线数仓需求提「补 Web 上传界面」「强制全量门店产出」。这类建议与真实链路不符，在 Non-Goals 写明边界，不为提分虚构业务。

**完成标准**：`audit` 无格式错误；平台评分 ≥ 85，且分数来自 `recalculate` 接口而非静态审计。

### 4. Task 三栏工时

| 栏位 | 内容 | 工时 |
|---|---|---|
| 前端/交互 | 配置交互、页面展示、参数表单 | 8~16h |
| 后端/算子 | 数据接入、准入门禁、计算引擎、结果落盘 | 20~30h |
| QA/对账 | 基准对账脚本、边界压力测试、异常隔离断言 | 12~16h |

**完成标准**：三栏都有 Task；总工时落在 40~60h。

### 5. 测试平台流转

在 `next.dslbuy.com` 用 `scripts/test_case_runner.mjs` 批量执行用例，再推进冒烟（P0）与系统测试阶段。

阶段流转按钮有业务副作用（触发工单流转、邮件通知），确认弹窗属人机终审。执行与门禁细节见 `skill://huashu-jev-automation` 模式 G。

**完成标准**：用例通过率 100%；冒烟与系统测试状态已回读确认。

## 边界

- 业务范围、Story 数量、批次划分由用户给定。给定后直接执行，不自行拆分或合并。
- 保存草稿可自动执行；提交正式 Story 需用户授权。
- 待办梯队与在手 Story 状态会变，记在 ai-memory 进度页而非本文。
