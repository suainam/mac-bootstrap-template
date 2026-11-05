---
name: analytics-result-delivery
description: Deliver analytics as Markdown and HTML, formatted workbooks or Sankey reports; publish authorized Wiki, WBS, timesheet and performance updates.
---

# 阶段五：结果交付

## 进入阶段

读取 [共享契约](../analytics-demand-analysis/references/ANALYSIS_CONFIRMATION_CONTRACT.md)：继承已确认范围与稳定资产身份，按六栏交付，技术事实自行查证，只确认新增业务选择。按当前任务进入本阶段，复用已有上游产物。

## 执行步骤

### 1. 汇总已验证结论

按 [交付模板](templates/delivery_report_template.md) 写 Markdown 真源，包含背景、结论、证据与行动。事实、预测和建议执行分开；销售重分类不算增长，历史无流水不直接认定因果增量。策略比较列门店数、增量及总条目、店均量、目录与全店动销率、销占/毛占和测算金额，说明口径。

完成标准：每个数字可追溯到阶段四产物，结论与已确认范围一致。

### 2. 生成默认 MD + HTML 双交付

使用 `answer-me-with-html` 从 Markdown 生成 HTML，工具参数以当前 skill 与帮助为准。按背景/结论、过程证据、行动组织页面；交付结构参考 [融合指南](references/DELIVERY_SYNTHESIS_REFERENCE.md)。技术开发交接列明输入输出、运行入口、验收证据与恢复步骤。

完成标准：两份文件均可打开，数字、口径、链接一致，HTML 实际渲染检查通过。

### 3. 生成任务所需附加资产

- Excel：汇总、明细、口径分层；深蓝白字表头、冻结表头、中文列名、列宽、千分位及百分比格式。按 [导出样例](examples/02_export_excel_with_dedup.py) 核对去重语义；逐 Sheet 回读行数金额。
- 桑基：读 [样式契约](references/sankey_style_contract.md) 和 [文案模板](references/sankey_wording_templates.md)，使用 `scripts/sankey_engine.py`；核验八类流向及 Ledger 守恒，图元与清单联动按样式契约验收。
- 跨年月份：读 [月份规则](references/CIRCULAR_SEASON_PARSER.md)，调用 `scripts/format_circular_months.py`。

完成标准：所选资产完成内容回读与视觉检查，证据随报告提供。

### 4. 核验发布实体与索引

按 [质量契约](../analytics-data-execution/references/DATA_QUALITY_CHECKLIST.md) 核对数据湖实体、稳定命名及软链接；更新专题 manifest 的 datasets/deliverables，使用项目索引入口刷新。配置交付链接差异、写入、调度、验收分区与最终导出，区分原库存、候选和最终建议数量。

完成标准：报告、索引、链接和实际回读文件一致，数据湖边界检查通过。

### 5. 执行已授权协同与复盘

外部回写按下表读取分支规约并回读状态；未授权项注明未执行，不阻断本地交付。交付末尾询问是否复盘，已有授权直接继承；获准后按 [复盘模板](templates/decision_postmortem_template.md) 记录决策、复用入口与已证实陷阱，挂入专题 README，保持交付口径不变。

完成标准：每项外部动作有回读证据或未执行状态；复盘状态明确。

## 协同分支

| 触发 | 读取与验收 |
|---|---|
| Wiki 发布/改写 | [发布契约](references/wiki_publishing_contract.md)：专项页面、附件预览、原行高亮改写与暂停项说明，回读页面和附件。 |
| WBS/工时 | [表格规约](references/wecom_sheet_patterns.md) 与 [门户流程](../../product-strategy/ps-portal-sync/SKILL.md)：基于真实提交及需求编号更新，核验整周工时守恒。 |
| HPM 自评 | [绩效规约](references/hpm_criteria.md)：先读在线责任书，逐项照录名称、类型、权重、档位、目标与计划；挂接证据，草稿未定项留空，核对权重 100%、突破类上限及责任书一致性。 |
| 视频汇报 | [视频流程](../../product-strategy/web-video-presentation-delivery/SKILL.md)：按所需渠道生成并验证可播放产物。 |

## 阶段验收

按共享契约 §2 的本阶段门槛逐项附证据，并执行 §2.0 产物审查。适用门禁全部通过、阻断为零才宣布完成；未验证项如实列明。中文业务正文按 `humanizer-zh` 润色，保留数字、口径与证据。

HPM 需要录入或保存时，继续读取 [完整自评流程](../../product-strategy/hpm-performance-review/SKILL.md)，继承已有授权并回读保存结果。
