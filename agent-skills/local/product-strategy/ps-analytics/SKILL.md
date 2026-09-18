---
name: ps-analytics
description: "Product Strategy 统一数据分析全流程规范：涵盖 ODPS SQL 性能优化（MAX_PT/防笛卡尔积）、多模型优先级掩盖排查、环形跨年时间区间解析、PyODPS 高效抽取以及高质量报表交付。"
disable-model-invocation: true
---

# ODPS & Python 联合数据分析 (ODPS Python Analytics)

本技能定义了在长期数据分析环境（如 `product_strategy`）中，基于 **MaxCompute (ODPS) SQL** 与 **Python (PyODPS / Pandas / DuckDB)** 进行高质量、可复现数据分析与交付的工业级闭环流程。

---

## 核心分析闭环 (6-Step Analytics Loop)

```text
1. 探查画像 -> 2. 定位规则与优先级 -> 3. 原生性能SQL -> 4. 交叉验证与防误伤 -> 5. 本地轻量化呈现 -> 6. 资产沉淀
```

### 1. 探查画像与颗粒度锁定 (Profile & Grain)
- **锁定实体粒度**：明确主键键值组合（如 `store_code + item_code`、`city_name + upc_code`）。
- **核验真实分区**：禁止猜测试验或历史脏分区（如 `29090902`），必须先探查有效分区范围。
- **主键唯一性初检**：在进行任何 Join 或过滤前，必须先断言 `COUNT(1) - COUNT(DISTINCT keys) == 0`。

### 2. 定位规则与优先级反查 (Priority & Masking Audit)
- **追溯生成代码源头**：分析综合打标字段（如 `reason_zfl`、`reason_fl`）时，严禁望文生义；必须通过 DataWorks OpenAPI 或快照拉取真实生成节点（如 `10002161979`），审查 `CASE WHEN` 的短路顺序。
- **排查低优先级属性重叠**：当目标原因（如季节性）排在高顺位时，必须排查后续所有排在更低顺位的标志位（新品、自有品牌、预测、品牌品、O2O、必上品等），防止粗暴拦截误伤正当入选品。
- 详见 [多模型优先级掩盖排查规约](references/MULTI_MODEL_MASKING_AUDIT.md)。

### 3. 原生性能 SQL 与防笛卡尔积聚合 (ODPS Performance)
- **必须使用原生 `MAX_PT()`**：严禁书写 `WHERE stat_date = (SELECT MAX(stat_date) ...)` 嵌套子查询；所有表统一采用 `WHERE stat_date = MAX_PT('project.table_name')`。
- **多版本店品并发去重**：针对月度组货、季度组货、新老店多版本并发导致的底层店品重复，关联合并层必须前置 `GROUP BY store_code, item_code` 并配合 `MAX(CASE WHEN ...)` 聚合收敛。
- **计算加速选择**：批量与复杂关联优先切换至 `os.environ['ODPS_PROJECT'] = 'dsl_ads'`，避免常规队列资源饥饿。
- 详见 [ODPS 性能与防踩坑规约](references/ODPS_OPTIMIZATION_RULES.md)。

### 4. 交叉验证与抽样核查 (Adversarial Check)
- **多维断言**：每次过滤、Join 或聚合后，强制断言行数变化与关键指标守恒。
- **真实抽样反查**：从最终交付结果中按大区/品类随机抽取样本（如 10~20 条），返回 MaxCompute 底层明细表穿透复核，确保证据链 100% 闭环。

### 5. 本地轻量化呈现与保真导出 (Export & Delivery)
- **环形跨年时间区间智能合并**：对具有连续跨年特征的月份列表（如 `[1, 2, 10, 11, 12]`），必须格式化为业务友好的 **`10月-次年2月`**，杜绝生硬割裂输出。算法见 [环形跨年解析手册](references/CIRCULAR_SEASON_PARSER.md)。
- **安全行数红线**：禁止向 Git 仓库导出超过 1,000,000 行明细；明细超限必须在 ODPS 侧完成聚合汇总。
- **编码与格式**：CSV 统一采用 `utf-8-sig`（带 BOM，防 Excel 乱码）；Excel 统一采用 `openpyxl` 并保持样式与自动列宽。

### 6. 规范沉淀与索引闭环 (Topic Governance)
- 产出落地至专题标准的 `03_analysis/scripts/` 与 `04_outputs/tables/`；
- 更新专题 `manifest.jsonc` 的 `datasets` 与 `deliverables`；
- 运行 `python3 scripts/generate_topic_indexes.py` 刷新全局索引。

---

## 目录索引与关键资产

- **核心规约**:
  - `references/ODPS_OPTIMIZATION_RULES.md` — MaxCompute 性能与分区规约
  - `references/MULTI_MODEL_MASKING_AUDIT.md` — 业务模型优先级掩盖与防误伤 SOP
  - `references/DATA_QUALITY_CHECKLIST.md` — 深度数据质量校验清单
  - `references/CIRCULAR_SEASON_PARSER.md` — 跨年环形时间段解析与呈现
- **完整样例**:
  - `examples/01_pure_premature_seasonal_audit.sql` — 多表对齐、MAX_PT 优化与绝对纯季节性穿透 SQL
  - `examples/02_export_excel_with_dedup.py` — PyODPS 高效抽取并导出 15万+ 行格式化 Excel 模板
- **通用工具**:
  - `scripts/odps_quick_probe.py` — 表结构、主键唯一性与最新分区一键探查 CLI
  - `scripts/format_circular_months.py` — 跨年月份区间解析函数独立工具库
  - `scripts/test_analytics_skill.py` — 自动化单元与回归测试套件
