---
name: analytics-demand-intake
description: Intake and standardize data analysis demands from enterprise portals or verbal notes with Socratic probing and decision contracts. Use when capturing DevOps demands, clarifying ad-hoc requests via first principles, or archiving standardized demand markdown documents.
---

# 阶段一：需求收集 (Analytics Demand Intake)

统一收集并标准化数据分析需求。双模支持企业研发门户正式单据与口头沟通诉求，运用第一性原理与苏格拉底审问穿透表象，锁定真实业务决策，在对应专题规范归档。

## 核心主导词 (Leading Words)

- **`【证据着陆 / grounded】`**：以原始客观事实与系统工单记录为准，完整呈现背景、指标与期望交付物。
- **`【决策穿透 / socratic-probe】`**：运用第一性原理穿透索表表象，聚焦真实商业决策与反事实基准。
- **`【分母防卫 / denom-guard】`**：前置明确测算分母边界与有效样本范围，确保后续计算稳健可比。
- **`【接口直抓 / xhr-api-first】`**：微前端环境直调后台接口提取原始详情，确保全量字段与附件链接保真。
- **`【标准归档 / standard-archive】`**：统一落盘至对应专题的 `topics/<topic_id>/01_source_data/` 目录。
- **`【可选排期 / optional-wbs】`**：正式立项需求登记团队排期表；临时答疑与即时调研直接进入分析。
- **`【业务去黑话 / humanized-language】`**：需求阶段全面接入 `/skill:humanizer-zh`，使用业务现场大白话（如以“陈列架总长度”取代“延米”，以“门店编码”取代“实体主键”），杜绝 AI 腔调与工程黑话。
- **`【指标孪生 / twin-metrics】`**：零售决策中销售与毛利紧密绑定，提销售指标时必须强制伴随问询含税合计毛利额 (`total_profit_amt`)、毛利米效与销售毛利率，防止冲量低毛利排面误导。
- **`【命名空间契约 / scoped-demand-naming】`**：需求归档及后续所有阶段文档，强制采用 `demand-<adhoc|id>-<topic_id>-<datehour>-xxx.md` 命名，防多专题冲突。
---

## 迷雾探路机制 (Heavy Fog Routing)

当需求跨多个业务域、存在重大历史口径冲突或涉及核心政策重构时：
1. 调用 `/skill:wayfinder` 绘制决策地图，将不确定项拆解为独立决策票据，沉淀于 `topics/<topic_id>/00_context/wayfinder_map.md`；
2. 调用 `/skill:grill-with-docs` 交叉审讯专题 `docs/` 与 Wiki 规则，沉淀业务术语至 `00_context/GLOSSARY.md` 与 `ADR/`；
3. 决策收敛确立后，再生成正式需求文件进入下一步。

---

## 执行步骤 (AB - 1 - 2 - (3) - 4)

```mermaid
flowchart TD
    Start["发起需求收集任务"] --> Branch{"选择输入分支 (Branch A / B)"}
    Branch -->|正式 DevOps 单据| B1["Branch A: DevOps 门户 API 直调抓取"]
    Branch -->|口头/即时诉求| B2["Branch B: 苏格拉底审问靶向澄清"]

    B1 --> S1["Step 1: 原始信息捕获 (Capture)"]
    B2 --> S1
    S1 --> S2["Step 2: 决策导向要素结构化 (Synthesize & Scope)"]
    S2 --> S3Opt{"是否为正式立项需求?"}
    S3Opt -->|是| S3["Step (3): [可选] WBS 推进表增行登记"]
    S3Opt -->|否 (临时调研)| S4["Step 4: 规范归档落盘与阶段移交"]
    S3 --> S4
```

### Branch A: 正式 DevOps 单据提取 (DevOps Scrape)
输入包含 Story ID、Demand ID 或页面 URL 时触发：
1. **直调微前端 API 抓取**：
   ```bash
   node scripts/extract_devops_demand.js --demand <ID> --out <target_dir>
   ```
2. **提取完整字段**：需求编号、标题、创建人、量化目标描述 (`valueDescribe`)、需求正文 (`contentDescribe`)、关联工作项 (`jiras[]`) 及 OSS 附件。

### Branch B: 临时口头需求澄清 (Ad-hoc Socratic Probing)
输入为口述、即时消息或会议纪要时触发。聚焦 2~3 个核心致命点进行靶向确认：
1. **决策意图**：该分析支持的具体营运动作（如方案选型、异常排查、准入汰换、考核结算）；
2. **反事实基准**：衡量的对比基期（去年同期 H / 上线前 L / 合成控制 SCM / 纯净对照区）；
3. **样本边界 (Non-Goals)**：明确本次覆盖及主动排除的范围（如仅限成熟直营店、排除特定试点省区）。

> **轻量摸底诉求快速通道 (Status Probing Fast-Path)**：  
> 若业务明确诉求“仅为大盘摸底/看个数/查基线”，且无后续考核奖惩或策略反转决策：  
> - **免除**：复杂的因果推断（DID/SCM）与人工合成对照组构建；  
> - **聚焦**：实体粒度、空间覆盖范围、多级汇总层级（如使用 Grouping Sets 向上聚合成门店/营运区/大区/全国）与异常店过滤门禁。
---

### Step 1: 原始信息捕获 (Capture)
载入原始结构化 JSON 或沟通原文字符串至缓冲区，完整保留第一手数值与初始诉求。

### Step 2: 决策导向要素结构化 (Synthesize & Scope)
对齐为 5 大分析要素：
1. **业务背景与痛点**：触发背景与经营现状；
2. **核心业务决策**：分析产出直接驱动的管理决策；
3. **核心指标与假设**：预期的衡量指标与潜在业务假设；
4. **实体粒度与窗口**：主体粒度（如 `门店 + 品类`）与分析时间区间；
5. **明确 Non-Goals**：主动排除的范围，保证分析聚焦。

### Step (3): [可选] WBS 推进表卡片登记 (Optional Tracking)
> **说明**：**非必选（Opt-in）**。临时探索与轻量排查直接跳过；仅正式立项需求执行：
1. 调用驱动工具在团队推进表中增行：
   ```bash
   node scripts/wecom_sheet_driver.js --doc <WBS_URL> --action insert-rows
   ```
2. 登记里程碑、需求编号、责任人与计划完成日，严格保持已有合并单元格结构与汇总公式。

### Step 4: 规范归档落盘与阶段移交 (Archive & Handoff)
1. **全链路命名契约**：
   需求归档及后续 01~05 阶段文件必须遵循统一的带专题与时间切片命名：
   `topics/<topic_id>/01_source_data/demand-<adhoc|id>-<topic_id>-<datehour>-01-demand.md`
   - 临时需求：`demand-adhoc-<topic_id>-<datehour>-01-demand.md`（如 `demand-adhoc-auto_display-2026101614-01-demand.md`）
   - 正式需求：`demand-<id>-<topic_id>-<datehour>-01-demand.md`（如 `demand-31935-auto_display-2026101614-01-demand.md`）
2. **标准元数据 Frontmatter**：包含 `id`, `title`, `requester`, `priority`, `created_at`, `target_date`, `deliverables` 7 项。
3. **输出【口径交接卡片】**，作为阶段二（`analytics-demand-analysis`）直通输入：
   - **分析主题与实体粒度 (Grain)**：明确核心主键；
   - **反事实对比期 (Counterfactual Window)**：明确基准窗口；
   - **分母防卫规则 (Denominator Guard)**：明确过滤门禁与排除条件；
   - **中台探查关键词 (Keywords)**：提供 3~5 个中台表与字段检索词。

**完成标准**：对应专题 `01_source_data/` 下生成非空规范 Markdown 文件，7 大元数据完整，口径交接卡片要素闭环。

---

## 内部资产引用 (Internal Assets)

- 接口抓取脚本：`scripts/extract_devops_demand.js`
- 协同表格驱动：`scripts/wecom_sheet_driver.js`
- 审问指南：[references/socratic_probing_guide.md](references/socratic_probing_guide.md)
- 表格规范：[references/wecom_sheet_patterns.md](references/wecom_sheet_patterns.md)
- 需求模板：[templates/demand_template.md](templates/demand_template.md)
- 提取范例参考：[examples/golden_demand_extraction.md](examples/golden_demand_extraction.md)
- 澄清范例参考：[examples/adhoc_socratic_clarification.md](examples/adhoc_socratic_clarification.md)
