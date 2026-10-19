---
name: ps-portal-sync
description: Automate enterprise portal workflows for product strategy via jev-browser-use: DevOps original demand extraction & timesheet logging, Confluence Wiki doc publishing, HPM review draft sync, Assortment board inspection, and WeCom/Tencent Sheet WBS project tracker maintenance. Use when scraping DevOps demands/stories, logging timesheets, updating Wiki, syncing HPM reviews, inspecting Assortment boards, or auditing WeCom sheets.
---

# 商品策略中台门户协同 (ps-portal-sync)

用于商品策略（Product Strategy）五大企业内网门户的一体化自动化操作：Wiki 业务文档沉淀、DevOps 需求管理与工时填报、HPM 绩效自评草稿录入、商品决策运营看板数据验收、企业微信 / 腾讯文档共享表格（WBS 推进表）结构化维护。

---

## 核心主导词 (Leading Words)

- **`grounded`（证据着陆）**：所有业务成果、指标数据与工时申报必须从仓库专题（`topics/*`）、Git 提交记录或数仓调度日志核验，严禁凭空编造。
- **`draft-only`（仅存草稿）**：所有填报与编辑操作严格限制为【保存草稿】或【暂存】，绝对禁止点击【提交审批】或【最终发布】（终审权归员工本人）。
- **`v-model-sync`（双向绑定同步）**：Element-UI 输入框赋值后必须派发 `input` 与 `change` 冒泡事件，禁止裸赋 `el.value` 导致状态未提交。
- **`popover-gate`（悬浮录入门禁）**：定性只读输入框必须先点击唤起 `.el-popover`，在其内部文本域录入并点击【确认】后关闭。
- **`timesheet-audit`（工时闭环审计）**：工时填报前必须通过本地 Git 日志与需求号完成交叉比对，单日上限 8.0 小时，整周合计严格等于 40.0 小时。
- **`wiki-sync`（增量结构更新）**：Wiki 文档必须采用定点章节追加或局部替换，严禁全量清空覆盖破坏历史版本与附件。
- **`xhr-api-first`（接口优先拉取）**：在 DevOps 批量提取原始需求时，优先在微前端 `pmp.dslbuy.com` 帧内拦截 XHR `Authorization` 头并直调 `devops-order.dslbuy.com/demand/manager/detail?demandId=<ID>`（本地 CLI 调用需加 `--noproxy '*'`），取代逐行点击抽屉的慢速且易截断 DOM 解析。
- **`extension-target-discipline`（扩展靶标隔离纪律）**：Jev 浏览器扩展通过 CDP 仅维护经由 `Target.createTarget` 显式创建并附加调试器的标签，绝不主动泄露或接管用户在 Chrome 中原生打开的其它标签。`browser.listPages()` 或 `targets: 0` 仅表示未注册活动调试靶标，严禁误判为“浏览器没有标签”或“系统不支持”。
- **`no-blind-getpage`（防盲目新建纪律）**：`browser.getPage(name)` 底层为 get-or-create 语义。当靶标失联时切勿原样循环重试，否则会不断产生同名/多重标签；必须先调用 `browser.newPage()` 获取稳定 handle，或复用已知 targetId。
- **`native-goto-first`（原生导航优先）**：在跨源（跨域）页面导航时，禁止裸用 `p.frames()[0].evaluate(url => location.href = url)`，跨源进程隔离（RenderFrameHost swap）会直接导致 Puppeteer 的 `LifecycleWatcher` 报 `Navigating frame was detached` 崩溃；必须统一使用 `await page.goto(url, { waitUntil: "domcontentloaded" })`。
- **`wbs-structure-gate`（WBS 结构与合并格门禁）**：在腾讯文档/企业微信共享表进行推进表维护前，必须先调用 `SpreadsheetApp.e2eTools.getCellEditValue` 与 `activeSheet.mergeManager.mergeList` 扫描结构、合并格及公式。严禁将大合并目标区（如 B21:B38 为单一大格「Q4目标」）误作任务明细行写入；按“里程碑 + Demand”规范组织时，必须按 `M 个里程碑 + D 个需求` 严格核验行容量，不够时显式增行，禁止削足适履为伪任务包。
- **`date-grain-discipline`（日期粒度审敛）**：清晰区分需求级实际字段（如实际研发开始）与工作项（Story）计划字段（`dev_start`、`dev_end`、`test_start`、`test_end`、`due`）。PRD 评审、UAT 无系统日期时严格留空，多工作项取最晚非空日期，严禁将计划测试通过当实际完成或根据日期猜测进度。

---

## 信息架构与关联指引

```text
skills/ps-portal-sync/
├── SKILL.md                          # 5大门户执行流程、路由状态机与质量门禁
├── references/
│   ├── element_ui_patterns.md        # Element-UI 与 Vue Hash 路由统一选择器与事件规范
│   ├── metrics_lineage.md            # 商品策略业务专题到责任书指标血缘映射
│   └── hpm_criteria.md               # HPM 考核标准、通用力六大要点与字数限制
│   ├── wecom_sheet_patterns.md       # 企业微信/腾讯文档表格 Canvas 模型、合并格与 WBS 规范
│   └── jev_extension_lifecycle.md    # Jev 扩展生命周期、靶标隔离、跨域防脱钩与清理 SOP
├── examples/
│   ├── golden_demand_extraction.md   # DevOps 原始需求底稿批量提取与转换黄金范例
│   ├── golden_hpm_sync.md            # HPM 绩效指标与四新复盘录入黄金范例
│   ├── golden_timesheet_log.md       # DevOps 需求流转与工时填报黄金范例
│   ├── golden_wiki_sync.md           # Confluence Wiki 知识沉淀与更新黄金范例
│   └── anti_patterns.md              # 门户操作 5 大典型反模式
└── scripts/
    ├── extract_devops_demand.js      # DevOps 原始需求单条/批量 API+DOM 提取脚本
    ├── portal_browser_sync.js        # 统一多门户浏览器自动化执行脚本
    ├── hpm_browser_sync.js           # HPM 兼容独立执行脚本
    ├── wecom_sheet_audit.js          # 企微/腾讯文档表格结构与合并格审计脚本
    └── wecom_sheet_driver.js         # 企微/腾讯文档驱动 (--doc 必填；sections/probe/audit/write-tsv/insert-rows/delete-rows/clear-range)
```

---

## 5 大门户分支执行协议

```mermaid
flowchart TD
    Start["发起门户协同任务"] --> Route{"选择目标门户分支"}
    Route -->|Wiki 文档| B1["分支 1: Wiki 知识沉淀 (Confluence)"]
    Route -->|DevOps 需求/工时| B2["分支 2: DevOps 原始需求提取与工时流转 (IT One)"]
    Route -->|HPM 季度绩效| B3["分支 3: HPM 绩效草稿同步 (HPM)"]
    Route -->|商品决策看板| B4["分支 4: 运营看板数据验收 (Assortment)"]
    Route -->|企微共享表格| B5["分支 5: WBS 项目推进表协同 (WeCom Sheet)"]

    B1 --> V1["格式保真与版本追加核验"]
    B2 --> V2["xhr-api-first 底稿保真 & timesheet-audit 核验"]
    B3 --> V3["popover-gate & draft-only 门禁"]
    B4 --> V4["指标卡片与目录对齐核验"]
    B5 --> V5["wbs-structure-gate & date-grain-discipline 核验"]

---

### 分支 1：Wiki 知识沉淀与文档更新 (`wiki.dslbuy.com`)

**触发条件**：沉淀策略逻辑、SOP 操作指引、算法说明（如三合一目录 V7.0 `pageId=122182137`、新店目录策略 `pageId=122182045`）。

1. **定位与提取**：
   - 导航至目标页面：`https://wiki.dslbuy.com/pages/viewpage.action?pageId=<ID>`。
   - 读取页面元数据（标题、最后修改时间、修改人），确认当前页面非锁定态。
2. **文本清洗**：
   - 剥离本地代码相对路径，转为绝对模块说明。
   - 核心 SQL 与逻辑段转换为标准代码块；表格必须包含完整表头。
3. **编辑与注入**：
   - 点击 `#editPageLink` 进入编辑模式。
   - 遵循 `wiki-sync` 原则：在正文末尾或目标章节使用 TinyMCE/ProseMirror 接口追加增量修订记录。
4. **发布校验**：
   - 点击 `#rte-button-publish`。
   - **完成标准**：页面恢复查看态，标题未变更，新增修订记录完整呈现，无转义坏损。

---

### 分支 2：DevOps 原始需求底稿提取与工时填报 (`devops.dslbuy.com`)

**触发条件**：拉取原始需求列表导出本地底稿 (`/#/story/list` → `01_source_data/demand-<ID>-<所属板块>-<中文简称>.md`)、编辑需求状态、周度工时申报 (`/#/timeWise/timeSheet`)。

#### 2A. 原始需求单条/批量提取 (`xhr-api-first`)
1. **微前端 Frame 穿透**：
   - 导航至 `https://devops.dslbuy.com/#/story/list`（使用 `f0.evaluate(url => location.href = url)` 规避跨进程崩溃），定位微前端子帧 `f1 = page.frames().find(f => f.url().includes("pmp.dslbuy.com"))`。
   - 页面默认激活 `常用` 视图（`产品线 = 数智中台部/数据智能`，`需求状态 = 待应答[3]、待排期[5]、排期中[11]、研发中[6]`，分页 100 条/页）。
2. **令牌捕获与接口直拉**：
   - 遵循 [`references/element_ui_patterns.md`](references/element_ui_patterns.md) 第 4 节或调用 [`scripts/extract_devops_demand.js`](scripts/extract_devops_demand.js)：通过拦截 `XMLHttpRequest.prototype.setRequestHeader` 点击首行唤起一次请求即可捕获有效 `Authorization` JWT，随后关闭抽屉。
   - 批量或单条请求 `https://devops-order.dslbuy.com/demand/manager/detail?demandId=<ID>`（本地 `curl` 必须带 `--noproxy '*'` 绕过代理），一次性获取结构化 JSON（基础字段、量化目标 `valueDescribe`、富文本 `contentDescribe`、关联工作项 `jiras[]` 及 OSS 附件 `files[]`）。
3. **底稿落盘 (`grounded`)**：
   - 严格对齐 [`examples/golden_demand_extraction.md`](examples/golden_demand_extraction.md) 模板写入 `topics/<topic_id>/01_source_data/demand-<ID>-<所属板块>-<中文简称>.md`（其中 `<所属板块>` 去除 `商品决策平台-` 冗余前缀，如 `智能组货`、`智能选品`、`策略分析`）及汇总索引。
   - **完成标准**：所有命中需求均生成独立底稿文件，包含完整 4 节结构（基础信息表、Linked Stories 表、100% 还原的需求原文与附件链接、口径线索），无 `null` 脏字符或 HTML 残留标签。

#### 2B. 周度工时日历填报 (`timesheet-audit`)
1. **凭据核对**：
   - 执行 `git log --author="$(git config user.name)" --since="7 days ago" --oneline` 提取当周真实交付分支与关联需求号（如 `Story-279258`）。
2. **工时日历填报**：
   - 导航至 `https://devops.dslbuy.com/#/timeWise/timeSheet`，匹配目标需求编号所在行。
   - 遵循 `v-model-sync`：对当周 5 个工作日单元格分别填入标准工时（单日 8.0h），派发 `input` 与 `change` 事件。
3. **安全保存 (`draft-only`)**：
   - 点击【暂存】或【保存】按钮，严格禁止点击【提交审批】。
   - **完成标准**：捕获 `.el-message--success` 提示，表格汇总栏数值严格等于 40.0 小时。
---

### 分支 3：HPM 季度绩效表单录入 (`xzapp.dslbuy.com/hpm`)

**触发条件**：季度绩效自评、定性指标打分与复盘录入。

1. **指标与基线核验 (`grounded`)**：
   - 查阅 `references/metrics_lineage.md` 核对量化数据（动销率、降本金额、覆盖店数）。
   - 查阅 `references/hpm_criteria.md` 确认各定性指标满分要求与字数限制（150 ~ 750 字）。
2. **责任书定性录入 (`popover-gate`)**：
   - 切换 `#tab-detail`。
   - 针对行 6 ~ 11（通用力 3.1 ~ 3.6）：下拉框选 `1档`；点击只读文本框唤起 `.el-popover`；填入纯文本事实（无档位前缀）；点击弹窗内【确认】。
3. **员工自评录入**：
   - 切换 `#tab-selfEvaluation`。
   - 填入“复盘和总结”（四新复盘）与“待提升点”（3~4项可落地攻坚点）。
4. **草稿保存门禁 (`draft-only`)**：
   - 定位器死锁 `aria/保存[role="button"]`，严禁触发提交。
   - **完成标准**：页面返回 `保存成功！`，核验当前自评分数（合理区间 1.05 ~ 1.10）。

---

### 分支 4：商品决策运营看板数据验收 (`assortment.dslyy.com`)

**触发条件**：策略上线后验收运营看板指标（`/#/operation/board`）、核验门店经营目录。

1. **筛选条件设定**：
   - 级联选择器（`.el-cascader`）选定目标省区/门店类型。
   - 点击 `button.el-button--primary:has-text("查询")`。
2. **卡片指标抓取**：
   - 抓取看板 KPI 卡片（全店动销率、销售占比、毛利额占比）。
   - 与数仓离线计算结果（如 `ads_item_store_cx_list_df`）进行偏差比对。
3. **完成标准**：输出格式化指标字典，明确记录抓取时间戳与环境版本（生产或测试）。

---

### 分支 5：企业微信共享表格 / 项目推进表 WBS 协同 (`doc.weixin.qq.com/sheet`)

**触发条件**：季度 WBS 推进表排期录入、状态同步、里程碑/需求结构化梳理。

1. **靶标创建与原生导航 (`native-goto-first`)**：
   - 遵循 `extension-target-discipline`：通过 `const p = await browser.newPage()` 获取受控标签，并执行 `await p.goto(sheetUrl, { waitUntil: "domcontentloaded" })`，严禁使用 `evaluate(location.href = ...)`。
2. **结构与合并格前置扫描 (`wbs-structure-gate`)**：
   - 调用 [`scripts/wecom_sheet_audit.js`](scripts/wecom_sheet_audit.js) 提取 `SpreadsheetApp.workbook.activeSheet` 的行列数与 `mergeManager.mergeList`。
   - 核验目标区域的合并属性：确认列 A/B/Q/R/S 的大合并区间，锁定列 D（里程碑/任务）、列 E（需求编码 `Demand-<ID>`）、列 F（审计月份）、列 G（执行人）以及列 H~L（节点日期）的正确写入列。
3. **需求行容量计算与规范排布 (`row-capacity-gate`)**：
   - 遵循 `references/wecom_sheet_patterns.md`：设定所需行数 $R_{needed} = M + D$（$M$ 为里程碑数，$D$ 为需求数）。
   - 若预留行数不足（如现有 18 行不足以容纳 5 里程碑 + 20 Demand 的 25 行），在目标子项目**内部**用 `--insert-rows` 插入差额行，大合并格与下游公式自动平移；多出的行用 `--delete-rows` 删除，同样自动收缩。
4. **日期审敛填报 (`date-grain-discipline`)**：
   - 真实日期提取自 DevOps API 与界面确认；H（PRD评审）、I（研发提测 `dev_end`）、J（测试完成 `test_end`）、K（预完成 `due`）、L（业务UAT）。
   - 无系统事实依据时严格留空；同一需求含多工作项时取最晚非空日期；严禁将计划测试节点当作实际测试通过。
5. **原子写入与校验回读 (`behavior-api-first`)**：
   - 一律用 [`scripts/wecom_sheet_driver.js`](scripts/wecom_sheet_driver.js)（`--doc <e3_ID>` 必填，防误写生产表）：`--sections` 看子项目块 → `--probe <格>` 看类型与数字格式 → `--insert-rows/--delete-rows` 调行 → `--write-tsv` 写入 → `--audit` 回读。底层为 `behaviorApi.cellApi.setRangeValue` / `dimensionApi`，严禁剪贴板与模拟按键。
   - **格式自适应**：写入字符串按目标格既有数字格式解析（`2026-09` 自动成「2026年9月」，`2026-10-23` 成 `yyyy/m/d`，`=AVERAGE(..)` 成百分比公式），模板行格式随行移动，无需手设格式。
   - **P 列不填**：推进表不写备注列，追溯信息留在 `01_source_data` 底稿。
   - 每个需求只出现在一个子项目块；缩铺等品项优化类需求归「品项优化」块，不放入智能组货。
   - 仅调用 `await p.close()` 关闭本次创建的专用标签，严禁执行全局 `stop`；不用 AppleScript 关 Chrome 标签（触发 CDP 靶标脱钩）。
---

## 质量门禁 (Quality Gates)

| 门禁项 | 约束条件 | 违规处置 |
| :--- | :--- | :--- |
| **真实性门禁** | 所有填报数字与需求关联必须有 Git 或数仓文件证据 | 拦截并终止流程，禁止臆造 |
| **提交控制门禁** | 严禁自动化点击【提交】、【发布审批】等终审动作 | 定位器源码硬编码限制，仅允许【保存】 |
| **事件响应门禁** | 表单赋值必须派发 `input` 与 `change` 事件 | 拦截裸赋值，严格调用 `v-model-sync` 规范 |
| **格式清洗门禁** | 绩效与 Wiki 文本禁止遗留 Markdown 乱码或档位前缀 | 自动执行正则前置清洗：`^([0-9\.]+档.*?[\)）]\s*)` |
| **靶标判定门禁** | `listPages()` 为空或 `targets: 0` 不得断言 Chrome 无标签或页面不支持 | 严格遵循 `extension-target-discipline`，先核实扩展架构契约 |
| **合并格防覆盖门禁** | 严禁向纵向合并大格（如子项目目标区 B 列）逐行覆盖写入明细 | 强制调用 `wbs-structure-gate`，明细必须写入未合并列 |
| **行数削足适履门禁** | 严禁为了迎合既有空行而将独立需求强行压缩为伪任务包 | 强制满足 $R_{needed} = M + D$，不足时通过标准流程增行 |
| **日期审敛门禁** | 严禁将计划完成日当实际交付，系统无记录日期必须留空 | 严格执行 `date-grain-discipline`，多工作项取最晚非空日期 |
