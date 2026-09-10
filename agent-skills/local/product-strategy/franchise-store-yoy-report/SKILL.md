---
name: franchise-store-yoy-report
description: 生成并复核加盟店组货同比动态汇报表，覆盖日期口径、桑基图、省区表和差异校验。
---

# 加盟店组货同比汇报

用于 `topics/franchise_store/` 的周期性加盟店组货同比汇报。优先复用专题已有的 ODPS SQL、Python 导出器和解密后的输入文件；不要复制一套新的业务计算逻辑。

## 固定业务契约

- `project_et` 默认昨天；年度由 `project_et` 推导为本年和去年，生产代码不得把 2025/2026 当作业务常量。
- `cata_version_dt` 是不晚于 `project_et` 的最大加盟组货上线日；灰度门店快照取 `cata_version_dt` 当天。
- 加盟销售窗口是截止 `project_et` 的严格 90 天；客流使用严格 56 天口径。
- 公司发货从严格 90 天销售窗口起点再前推 30 天开始，发货统计窗口长度仍为严格 90 天；去年窗口按去年同期平移。
- 汇报主体沿用组货可比同比门店；目录字段使用 `is_content_vs_store=1` 的语义，流转使用最新分区的 `fl`；大盘可比店使用 `is_tb_sj=1`，组货可比店使用 `is_tg=1 and is_kbtb_ct=1`。
- 报告页复制解密模板的版式和图表锚点，但数字、图表缓存、桑基图说明和省区表全部从本次结果生成。大盘输入必须校验结束日；历史对照快照只能作为明确匹配结束日的对照快照复用。
- 输出使用中文表头；报告页桑基图下方同时保留动态图例说明和以下口径：`口径：按照组货口径统计推广区域可比同比门店、大盘的销售、毛利、客流等情况；公司按仓库提前 1 个月备货进行统计`。
- 不导出明细数据；任何明细导出前都必须在 ODPS 侧聚合并执行百万行限制。

## 推荐流程

1. 阅读 `topics/franchise_store/00_context/franchise_sales_with_company_delivery_0908.md` 和专题 README，确认输入区间、表分区及输出模板。
2. 对加密输入先使用 `$decrypt-materialize` 生成可读副本；把副本作为本次命令的显式输入，不修改原始文件。
3. 运行 `topics/franchise_store/03_analysis/scripts/export_franchise_store_yoy.py`。生产运行显式传 `--project-et`、`--report-template`、`--market-previous`、`--market-current`；大盘区间不匹配时应停止或明确复用已核验的历史快照。
4. 在导出前后运行 `scripts/audit_dynamic_params.py` 和 `scripts/inspect_workbook.py`。
5. 需要复核历史结果时运行 `scripts/compare_workbooks.py --reference <旧版> --candidate <新版>`，只比较汇报页共同指标单元格，不把新增省区表或新增口径列误判为差异。
6. 汇报结论必须说明：共同指标的绝对差异、差异是否来自统计窗口/门店快照/字段语义变化，以及哪些新增内容无法与旧版一一比较。

## 失败处理

- 若 ODPS 连接失败，先记录是代理/依赖/认证/SQL 哪一层，不改口径、不用缓存冒充新结果。
- 若门店数异常，逐层检查 cata 版本、灰度快照、基线门店、`is_content_vs_store`、`is_tb_sj` 和 `is_tg/is_kbtb_ct`，并保留各层计数证据。
- 若公司发货毛利异常，先打印本年/去年起止日期和实际分区，再检查是否误用了加盟销售窗口或旧版发货区间。

## 支持文件

- `references/parameter-contract.md`：日期和字段口径的可执行审查清单。
- `references/adversarial-review.md`：硬编码、错连、模板覆盖和输出完整性检查。
- `scripts/audit_dynamic_params.py`：扫描生产 Python/SQL 中的日期、年度和个人绝对路径。
- `scripts/compare_workbooks.py`：汇报页共同单元格的数值差异报告。
- `scripts/inspect_workbook.py`：中文表头、桑基说明、口径、图表包和省区表检查。
