# DevOps 原始需求标准化导出范例 (Golden Example: Demand Extraction)

本范例展示如何使用 OMP eval `browser` + `tab.run` 从 DevOps 效能平台自动化提取需求及其关联工作项（Story），并输出为客观、克制的 `01_source_data/demand-<ID>-<所属板块>-<中文简称>.md` 原始底稿。

---

## 核心原则：保持克制与客观还原

`01_source_data/` 的定位是**客观事实源（Source Data）**，而非分析报告：
1. **严格还原原文**：对业务背景、需求描述、加急原因等，必须 100% 摘录系统原话，严禁臆造“矛盾归因”或添加主观过度拆解。
2. **纯粹字段对齐**：基础信息表格仅忠实呈现 DevOps/PMP 字段值（人天、月份、评分、负责人等），不添加演绎性评述。
3. **线索与指引清晰**：结尾仅提供知识库、DMP 终端与 ODPS 探查入口指针，具体的架构设计与代码方案全部推迟至 `03_analysis/demand-<ID>-rfc-*.md` 开展。


---

## 批量筛选与高速提取范式 (`xhr-api-first`)

当需要按模块/关键字（如“智能组货”、“缩铺”）批量拉取「数据智能」下所有活动需求（`待应答[3]`、`待排期[5]`、`排期中[11]`、`研发中[6]`）时：

1. **执行 `scripts/extract_devops_demand.js` 捕获令牌与列表**：
   - 在 `pmp.dslbuy.com` 微前端内自动读取当前默认视图全部行 `demandId` 并通过 XHR 拦截输出 `AUTH_B64`。
2. **宿主环境直连 API 拉取完整详情**：
   - 使用 `curl -s --noproxy '*' -H "Authorization: $AUTH" "https://devops-order.dslbuy.com/demand/manager/detail?demandId=<ID>"` 逐条或并发获取完整 JSON（避免浏览器 eval 沙箱的 4KB stdout 截断和 `require` 限制）。
3. **HTML 富文本清洗与底稿渲染**：
   - 将 `contentDescribe` 中的 `<p>`、`<ol>/<li>`、`<h3>`、`<a href>` 转换为纯净 Markdown，附上 `files[]` 中的 OSS 附件签名链接，按下方标准模板生成 `demand-<ID>-<所属板块>-<中文简称>.md`（`<所属板块>` 提炼自 `businessLineVo.lineName` 去除 `商品决策平台-` 前缀，如 `智能组货`、`智能选品`、`策略分析`；`<中文简称>` 剔除括号、斜杠与空格）与汇总索引 `demand-index-*.md`。
---

## 标准结构参考

```markdown
# 需求
[【模块】需求名称](https://devops.dslbuy.com/#/story/list?id=XXXXX)

## 1. 基础信息

| 字段 | 内容 |
| :--- | :--- |
| **需求编码** | Demand-XXXXX |
| **需求名称** | ... |
| **所属模块** | ... |
| **所属项目** | ... |
| **需求类型** | 产品需求 |
| **需求状态** | 待排期 / 进行中 |
| **提出人** | 姓名（部门） |
| **业务提出时间** | YYYY-MM-DD |
| **期望完成月份** | YYYY-MM |
| **需求负责人** | 姓名 |
| **加急情况** | 是 / 否（加急原因原文） |
| **价值分类** | 增加收入 / 降低成本 / 提升效率 |
| **目标导向** | 提取自系统登记的目标描述 |
| **毛估总体人天** | X 人天 |
| **总预估人天（最新）** | X 人天 |
| **总实际人天（最新）** | X 人天 |
| **计划上线月份** | YYYY-MM（审议状态） |
| **优先级 / 评分** | X星 / X.XX |
| **OA 编号** | ... |

## 2. 关联工作项 (Linked Stories)

| 工作项名称 | 工作项编码 | 状态 | 计划研发开始 | 计划研发完成 | 到期日 | 负责人 | JIRA 编号 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| ... | Story-XXXXX | ... | ... | ... | ... | ... | ... |

## 3. 需求原文

### 【背景】
（100% 摘录系统背景文本）

### 【需求描述】
（100% 摘录系统需求与验收说明文本）

## 4. 后续探索与口径线索 (Candidates)

* **项目权威知识库**：
  [`topics/assortment/202608组货模型复盘/README.md`](../../assortment/202608组货模型复盘/README.md)
* **DMP MCP 表查询终端**：
  - 终端地址：`dmp-search-mcp-vpc.dslbuy.com/mcp`
* **MaxCompute (ODPS) 数据库查询与验证**：
  - 遵循 `odps-query-uv` 规范（`uv run --with pyodps --no-project`）。
```
