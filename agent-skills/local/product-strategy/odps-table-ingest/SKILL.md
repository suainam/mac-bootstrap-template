---
name: odps-table-ingest
description: 将本地 Excel/CSV 上传至 MaxCompute/ODPS 分区表或全量表。执行线上元数据探查、字段模糊对齐方案确认、类型定型入库及聚合 SQL 双向核验举证。
---

# odps-table-ingest

将本地数据文件（Excel / CSV）安全、准确地导入 MaxCompute (ODPS) 表。以**线上探查 (Introspect)**、**对齐确认 (Reconcile & Gate)**、**类型定型 (Cast)** 与**事后举证 (Prove)** 为核心流程。

## 适用场景
- 用户需要将本地 `.xlsx` / `.xls` / `.csv` 上传至指定的 MaxCompute / ODPS 表（如分区表或明细表）。
- 源数据字段与线上表字段数量或名称不完全一致，需智能模糊对齐。
- 需要将数据写入指定日期分区（如今日 `stat_date=YYYYMMDD`）并做线上数据一致性核验。

## 工具体系与参考
### 核心确定性工具 (Core)
- `scripts/introspect_table.py` — 表结构、注释、分区定义与历史数据样本探查。
- `scripts/upload_and_verify.py` — 显式列序数据写入与事后聚合 SQL 双向举证。
- `references/CASE_STUDY.md` — 粤东退货剩余库存导入经典案例（含历史表名容错与指标举证）。

### 可选辅助工具 (Optional)
- `scripts/fuzzy_align.py` — （可选）字段模糊匹配与 Markdown 对齐草案生成器。
- `references/ALIGNMENT_RULES.md` — （可选）常见零售/供应链业务字段别名词典与类型定型规范。
---

## 执行步骤与完成标准 (Information Hierarchy)

### Step 1: 本地物化与数据画像 (Stage & Profile)
1. 检查源数据文件格式与加密状态（TSD 包装文件需保持原文件 Hash 不变，通过 Python/openpyxl 透明读取）。
2. 将数据暂存为可读 CSV（如 `02_working_data/<name>_<sheet>_<date>.csv`）。
3. 提取本地数据画像：总行数、字段列表、非空行数、主键唯一性、核心数值指标汇总（总数量、总金额、去重门店数、去重商品数等）。

**完成标准**：本地物化完成，产出明确的行数、字段清单及本地基准指标统计值。

---

### Step 2: 线上真实表元数据探查 (Introspect)
1. 使用 PyODPS 或 `scripts/introspect_table.py` 查询线上真实表元数据：
   ```bash
   python3 scripts/introspect_table.py <project>.<table_name> [--env-file <path>]
   ```
2. 验证表是否存在，**核验真实表名拼写**（容忍历史 typo，如 `anslysis_` 对比 `analysis_`，以线上真实存在的表为准）。
3. 获取目标表的字段名、数据类型、字段注释，以及**分区定义**（是否为分区表、分区键名称与类型）。
4. 读取线上最新分区列表及近期数据样本，确认历史数据的实际填充格式（如 `store_item_lot_merge` 是否拼接、`st_amt` 是否带小数等）。

**完成标准**：输出线上目标表的正式 Schema、注释、分区键与历史填充范式。

---
### Step 3: 字段对齐方案与人工确认门禁 (Reconcile & Gate)
1. 根据 Step 2 探查出的 Native 列名制定映射方案（列名歧义时可选用 `scripts/fuzzy_align.py` 辅助生成草案）。
   - 目标字段 (`Field`)、类型 (`Type`)、注释 (`Comment`)
   - 匹配的来源列 (`Source Column`) 与置信度
   - 类型定型与清洗规则（如 10 位文本补零、`BIGINT` 整型转换、`DOUBLE` 浮点转换）
   - 样例值 (`Sample Value`)
   - **丢弃列清单**（源文件中不入库的冗余列、辅助列或序号列）
   - **目标分区键**（如 `stat_date=YYYYMMDD`）
3. **硬性确认门禁**：将对齐表格呈现给用户，**必须等待用户显式确认（如“确认”）后方可执行后续写入步骤**。严禁未经确认直接写入线上表！

**完成标准**：向用户展示完整的对齐方案，并获得用户的显式确认答复。

---

### Step 4: 类型定型与分区写入 (Cast & Ingest)
1. 根据确认的映射规则，对每行数据执行严格的类型定型：
   - `STRING` 编码列：去除首尾空格，保留前导零（防止 `00123` 丢失）。
   - `BIGINT` 整数列：安全转换 `int(float(val))`，空值转为 `None`。
   - `DOUBLE` 浮点列：解析数值并保留精度，非法字符或空值转为 `None`。
2. 调用 PyODPS 写入指定分区（若分区不存在，自动创建）：
   ```python
   t = odps.get_table(table_name, project=project)
   if is_partitioned:
       t.create_partition(part_spec, if_not_exists=True)
       with t.open_writer(partition=part_spec, create_partition=True) as writer:
           writer.write(records_to_upload)
   else:
       with t.open_writer() as writer:
           writer.write(records_to_upload)
   ```

**完成标准**：PyODPS 写入成功，无异常抛出，返回 Logview 地址。

---

### Step 5: 线上聚合 SQL 举证闭环 (Prove)
1. 写入完成后，立即执行线上 MaxCompute 聚合查询 SQL：
   ```sql
   SELECT 
       COUNT(1) AS row_cnt,
       SUM(st_qty) AS sum_qty,
       ROUND(SUM(st_amt), 2) AS sum_amt,
       COUNT(DISTINCT store_code) AS store_cnt,
       COUNT(DISTINCT item_code) AS item_cnt,
       COUNT(DISTINCT store_item_lot_merge) AS merge_cnt
   FROM <project>.<table_name>
   WHERE <partition_condition>;
   ```
2. 将线上聚合查询结果与 Step 1 产出的本地数据画像进行双向核对：
   - `row_cnt` 必须 100% 等于本地物化行数。
   - `sum_qty` 与 `sum_amt` 必须与本地总和一致。
   - 去重键值（门店数、商品数、唯一主键数）必须完全一致。
3. 结构化输出最终举证报告。

**完成标准**：ODPS SQL 查验结果与本地指标完全吻合，形成闭环证据链。
