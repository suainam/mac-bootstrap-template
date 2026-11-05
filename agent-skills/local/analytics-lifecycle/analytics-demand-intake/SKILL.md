---
name: analytics-demand-intake
description: Capture analytics requests from portal tickets, messages or meetings; clarify the business decision and archive the demand.
---

# 阶段一：需求收集

## 进入阶段

读取 [共享契约](../analytics-demand-analysis/references/ANALYSIS_CONFIRMATION_CONTRACT.md)：继承已确认范围与稳定资产身份，按六栏交付，技术事实自行查证，只确认新增业务选择。按当前任务进入本阶段，复用已有上游产物。

## 执行步骤

### 1. 捕获来源

正式单据：使用 `scripts/extract_devops_demand.js`，保留编号、标题、创建人、目标、正文、关联工作项与附件；接口凭据只用于调用，不进入报告。口述或会议：保留原话，按 [澄清指南](references/socratic_probing_guide.md) 核对决策意图、对比基准与样本边界。

完成标准：原始信息可追溯，事实、诉求和未决项分开。

### 2. 锁定决策与范围

记录背景、业务决策、指标假设、实体粒度、时间窗与 Non-Goals。销售相关零售决策同时核对含税毛利、毛利率；涉及空间时核对毛利米效。仅摸底任务聚焦覆盖范围、汇总层级与异常过滤，因果评估按实际决策需要设计。

跨业务域或历史口径冲突：先列冲突证据、候选解释与待决项，在专题上下文记录已选口径再交接。配置范围变更：记录新增、保留、停用范围、策略版本、生效业务日与交付物，区分调度日和执行日。

完成标准：五项要素齐全；剩余问题仅为影响决策的业务选择。

### 3. 归档并交接

按 [需求模板](templates/demand_template.md) 归档，保留 id、title、requester、priority、created_at、target_date、deliverables。交接卡包含粒度、对比窗口、分母边界及 3–5 个元数据检索词；明确未开展的 story。

完成标准：需求文件非空、元数据完整，交接卡可供阶段二查证。

### 4. 登记排期（正式立项且已授权时）

读取 [协同表规则](references/wecom_sheet_patterns.md)，使用 `scripts/wecom_sheet_driver.js` 登记里程碑、编号、责任人与完成日，并回读；保留原表合并单元格及公式。

完成标准：已授权回写可回读核对；临时分析或未授权回写不阻断交接。

## 阶段验收

按共享契约 §2 的本阶段门槛逐项附证据，并执行 §2.0 产物审查。适用门禁全部通过、阻断为零才宣布完成；未验证项如实列明。中文业务正文按 `humanizer-zh` 润色，保留数字、口径与证据。
