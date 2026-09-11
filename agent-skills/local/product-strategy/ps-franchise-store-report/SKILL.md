---
name: ps-franchise-store-report
description: 加盟店组货汇报（同比与环比）：涵盖大盘基准对齐、店品组货可比同比、桑基流转图与省区明细看板，直接在 MaxCompute 计算并自动化产出格式化交付 Excel 与矢量图。
---

# 加盟店组货汇报 (Franchise Store Assortment Report)

用于 `topics/franchise_store/` 的周期性加盟店组货汇报（支持同比与环比）。集成大盘基准直算、店品宽表聚合、桑基流转图及模板化 Excel 交付。

## 业务契约 (Business Contract)

- **动态基准推导**：`project_et` 默认昨天；年度由 `project_et` 推导为本年和基期，严禁将具体年份（如 2025/2026）写死为业务常量。
- **大盘基准直算**：大盘 21 项核心指标默认由 MaxCompute (ODPS) SQL 直算，严格覆盖截止 `project_et` 的 90 天窗口；无需人工通过 FineReport 导出解密文件。
- **时间窗口规则**：销售窗口严格 90 天；客流使用严格 56 天；公司发货从 90 天销售起点前推 30 天起算，窗口长度同样为严格 90 天。
- **汇报主体范围**：组货可比店使用 `is_tg=1 and is_kbtb_ct=1` 且试点基线有销售；目录状态取 `is_content_vs_store=1`，流转类型取最新分区 `fl`。
- **安全与合规**：严禁明细数据落盘，所有明细在 ODPS 侧先聚合后下载；单次导出严格受限在 1,000,000 行内。

## 执行分支 (Branches)

先根据用户需求确定执行分支：

### Branch A: 仅核对/计算大盘基线指标
当用户需要核对全国加盟大盘（销售、毛利、客流、O2O、代用券等 21 项指标）时触发：
1. 运行 `scripts/verify_market_baseline.py --project-et <YYYYMMDD>`。
2. 核对 21 项输出指标是否完整且数值非空。
- **完成标准**：产出大盘 21 项标准指标对比摘要，与基准误差小于 $10^{-4}$。
- **深入参考**：[references/market-baseline-contract.md](references/market-baseline-contract.md)。

### Branch B: 完整组货汇报一键跑批与 Excel 导出 (默认)
当用户需要生成本期组货汇报（整体看板、大盘看板、省区看板、内嵌桑基图）时触发：
1. 阅读 `topics/franchise_store/00_context/franchise_sales_with_company_delivery_0908.md` 确认本次业务区间与上线版本。
2. 运行导出脚本：
   ```bash
   uv run python topics/franchise_store/03_analysis/scripts/export_franchise_store_yoy.py --project-et <YYYYMMDD>
   ```
   *说明：无需传递 `--market-previous` 或 `--market-current`，脚本已集成 ODPS 大盘直算。*
3. 自动生成：
   - 目标 Excel: `04_outputs/tables/franchise_store_sale_profit_yoy_<YYYYMMDD>.xlsx`
   - 流转图表: `04_outputs/graphs/franchise_store_sankey_graph_<YYYYMMDD>.svg`
4. 运行质量门禁：
   ```bash
   python scripts/inspect_workbook.py 04_outputs/tables/franchise_store_sale_profit_yoy_<YYYYMMDD>.xlsx
   ```
- **完成标准**：Excel 生成且包含完整的“整体汇总”、“省区明细”及“加盟店大盘”三张工作表，桑基图成功嵌入，数值无 `#VALUE!` 或空表头。
- **深入参考**：[references/parameter-contract.md](references/parameter-contract.md)、[references/adversarial-review.md](references/adversarial-review.md)。

### Branch C: 桑基流转图与卡片独立交付
当用户需要单独输出或复核目录流转双列桑基图、HTML 汇报卡片时触发：
1. 确认流转数据集包含 8 大标准流向：`稳定目录内`、`稳定目录外`、`目录外转目录内`、`目录内转目录外`、`新增目录内`、`新增目录外`、`目录内汰换`、`目录外汰换`。
2. 运行资金平衡断言：
   ```bash
   python scripts/validate_sankey_ledger.py 04_outputs/graphs/franchise_store_sankey_flow_<YYYYMMDD>.json
   ```
3. 检查生成的独立 HTML 汇报页 `04_outputs/graphs/franchise_store_sankey_flow_<YYYYMMDD>.html`。
- **完成标准**：Ledger 校验通过，源端流出与终端流入严格守恒，图表通过文字防碰撞检查，词表严格对齐批准规范。
- **深入参考**：[references/sankey-style-contract.md](references/sankey-style-contract.md)、[references/sankey-wording-templates.md](references/sankey-wording-templates.md)。

## 规范与质量门禁

- **用词规范**：严禁使用“损耗”，必须使用“汰换”；占比一律使用“%”。
- **静态参数审查**：在提交修改前运行 `python scripts/audit_dynamic_params.py`，杜绝硬编码个人路径或历史年份常量。
- **历史差异比对**：若需要复核与历史版本差异，运行 `python scripts/compare_workbooks.py --reference <旧版> --candidate <新版>`，汇报核心指标绝对差异与口径归因。

## 支持资产索引

- `references/market-baseline-contract.md`：大盘 21 项指标口径与 ODPS 表映射。
- `references/parameter-contract.md`：动态日期推导（销售90d、客流56d、发货120/90d）清单。
- `references/sankey-style-contract.md`：桑基图双列布局、图例、字号与防重叠合同。
- `references/sankey-wording-templates.md`：批准汇报文案结构与措辞节奏。
- `references/adversarial-review.md`：硬编码与破坏性审查清单。
- `scripts/verify_market_baseline.py`：大盘指标 ODPS 直算与比对器。
- `scripts/validate_sankey_ledger.py`：桑基图流量守恒验证器。
- `scripts/inspect_workbook.py`：导出的 Excel 工作簿图表与结构审查。
- `scripts/compare_workbooks.py`：工作簿数值单元格比对报告器。
- `examples/market_baseline_sql_template.sql`：ODPS 大盘标准计算 SQL 脚本模板。
