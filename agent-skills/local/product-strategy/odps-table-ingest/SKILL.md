---
name: odps-table-ingest
description: Ingest local Excel/CSV files into MaxCompute (ODPS) partitioned tables with strict 5-phase verification: profile, introspect (with typo/rename handling), reconcile & gate, cast & write, and prove via aggregate SQL.
---

# odps-table-ingest

将本地数据文件（Excel / CSV）安全、定型、准确地导入 MaxCompute (ODPS) 表。以**数据画像 (Profile)**、**线上探查与重命名决策 (Introspect)**、**对齐确认门禁 (Reconcile & Gate)**、**类型定型写入 (Cast & Write)** 与**双向聚合 SQL 举证 (Prove)** 为核心闭环。

---

## 执行步骤与完成标准 (Information Hierarchy)

### Step 1: 本地物化与数据画像 (Stage & Profile)

1. **源文件读取**：
   - 检查加密与包装状态（TSD 包装文件需保持原文件 Hash 不变，通过 Python/openpyxl 透明读取明文）。
2. **物化落盘**：
   - 导出为标准 CSV 暂存于 `02_working_data/<topic_or_wh>_<batch>_<date>.csv`。
3. **数据画像基准提取**：
   - 必须提取 6 大本地基准指标：总行数 (`row_cnt`)、去重门店数 (`store_cnt`)、去重商品数 (`item_cnt`)、去重主键数 (`merge_cnt`，如 `store_code + item_code + lot`)、库存数量总和 (`sum_qty`)、库存金额总和 (`sum_amt`，元/万元)。
   - 核验主键唯一性，确认重复行为 0（若有重复需在对齐方案中单独披露处理规则）。

**完成标准**：本地数据完成物化落盘，产出明确的 6 项本地基准指标与零空值/唯一性检查结论。

---

### Step 2: 线上真实表元数据探查与重命名决策 (Introspect)

1. **元数据探查**：
   - 通过 PyODPS 查询线上目标表的字段名、数据类型、注释、分区定义（如 `stat_date BIGINT (yyyyMMdd)`）及已有分区列表。
2. **历史表名 Typo 与 RENAME 继承决策树**：
   - 当遇到历史表名拼写错误（如 `anslysis_...` 对比 `analysis_...`）时：
     - 若旧表已承载历史生产分区，**严禁直接新建空表**（会造成历史分区丢失或资产孤立）；
     - **必须执行 `ALTER TABLE <old_typo_table> RENAME TO <correct_table>;`**，确保历史分区 100% 完整继承至正名表名下；
     - 重命名后立即运行 `SHOW PARTITIONS` 验证历史分区数与名称全部在册。
3. **下游 Join 语义识别**：
   - 明确待导入数据在下游工作流中的角色：是全量数据直传，还是作为下游主流程按店品批 `INNER JOIN` 过滤特定批次的清单表。

**完成标准**：目标物理表名确立（含重命名继承证明）、字段类型与分区 Schema 锁定、已有分区列表清晰。

---

### Step 3: 字段对齐方案与人工确认门禁 (Reconcile & Gate)

1. **结构化对齐表格展示**：
   向用户清晰呈现包含以下列的 Markdown 对齐表：
   - `ODPS 目标字段` (`Field`)
   - `目标类型` (`Type`)
   - `字段注释` (`Comment`)
   - `Excel 来源列` (`Source Column`)
   - `处理与定型规则` (`Rule`，如 10位文本补零、BIGINT整型转换、DOUBLE浮点转换、Key拼接)
   - `样例值` (`Sample Value`)
   - `目标分区键`（如 `stat_date=YYYYMMDD`）
2. **明确披露信息**：
   - 本地 6 项指标基准汇总；
   - 丢弃列清单（若有冗余列、辅助列或行序号）；
   - 下游使用建议（如 INNER JOIN 关联字段与分区条件）。
3. **⛔ 硬性确认门禁 (Hard Gate)**：
   - **必须等待用户显式确认（如“确认”）后，方可执行后续写入步骤**；
   - 严禁在未经用户确认前调用写入方法或修改线上生产数据。

**完成标准**：对齐方案结构化呈现给用户，并收到用户的显式确认答复。

---

### Step 4: 类型定型与分区写入 (Cast & Write)

1. **严格类型定型**：
   - `STRING` 编码列：去除首尾空格，保留/补齐前导零（防止 `00123` 丢失）。
   - `BIGINT` 整数列：安全转换 `int(float(val))`，空值置为 `None`。
   - `DOUBLE` 浮点列：解析数值保留完整精度，非法值置为 `None`。
   - `store_item_lot_merge` 拼接列：按目标规范合成 `f"{store_code}{item_code}{lot}"`。
2. **分区安全写入**：
   - 声明 `create_partition=True` 或 `t.create_partition(part_spec, if_not_exists=True)`；
   - 使用 `t.open_writer(partition=part_spec, create_partition=True)` 写入记录列表。

**完成标准**：PyODPS 写入成功返回 Logview，无类型溢出或格式异常。

---

### Step 5: 线上聚合 SQL 举证闭环 (Prove)

1. **执行 MaxCompute 验证查询**：
   ```sql
   SELECT 
       COUNT(1)                             AS row_cnt,
       SUM(st_qty)                          AS sum_qty,
       ROUND(SUM(st_amt), 2)                AS sum_amt,
       COUNT(DISTINCT store_code)           AS store_cnt,
       COUNT(DISTINCT item_code)            AS item_cnt,
       COUNT(DISTINCT store_item_lot_merge) AS merge_cnt
   FROM <project>.<table_name>
   WHERE <partition_condition>;
   ```
2. **双向核对对比表输出**：
   输出包含 `指标项`、`本地物化源数据`、`MaxCompute 线上实际查询结果`、`核验结论` 的对比表：
   - `row_cnt` 必须 **100% 等于** 本地行数；
   - `sum_qty` 与 `sum_amt` 必须与本地总和一致；
   - 去重键值（门店数、商品数、店品批唯一键）必须完全吻合。

**完成标准**：MaxCompute 线上聚合查询输出 Logview，6 大指标与本地画像完全吻合，形成闭环证据链。

---

## 辅助参考与工具目录 (Progressive Disclosure)

- [`references/CASE_STUDY.md`](references/CASE_STUDY.md) — 典型实战案例：
  - **案例 1**：粤东退货剩余库存全量导入（39,289 行直接导入举证）；
  - **案例 2**：粤西茂名仓缩铺第一批清单导入与历史 Typo 表 `RENAME` 分区无损继承（25,700 行、表名重命名、下游 INNER JOIN 语义与逐日退仓走势印证）。
- [`references/ALIGNMENT_RULES.md`](references/ALIGNMENT_RULES.md) — 常见零售/供应链业务字段别名词典、边界类型转换规则与质量门禁。
- `scripts/introspect_table.py` — 表结构、注释、分区定义与历史样本探查脚本。
- `scripts/upload_and_verify.py` — 显式列序写入与事后聚合 SQL 双向举证脚本。
