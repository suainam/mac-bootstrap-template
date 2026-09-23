# SQL 差异排查与 MaxCompute 避坑规约

本指南总结在 MaxCompute (ODPS) 上重构/排查复杂 SQL 工作流时，定位空值、类型隐式转换异常及环境切换的最佳实践。

---

## 1. SQL 差异排查心智模型 (Diff-First Bisection)

当重构后 SQL（或新版本工作流）跑出的结果为空或行数异常时，**严禁盲目重跑已被证明正确的旧版本全量任务**。

### 标准排查三部曲

1. **Git 文本级严格 Diff**：
   - 提取新旧两版 SQL 进行 `diff -u`，列出所有新增/修改的 CTE、`JOIN` 关联条件及 `WHERE` 谓词。
2. **逆向二分断点排查 (Bisection Probe)**：
   - 从下游向上游逆向探测 CTE 输出（如：最终写入 $\rightarrow$ 阶段 2 宽表 $\rightarrow$ 阶段 1 周期聚合 $\rightarrow$ 基础过滤范围）。
   - 精准定位**哪一个 CTE 是第一个产生 0 行的断点**。
3. **单键/单店切片微型作业 (Micro-Slice Isolation)**：
   - 严禁直接跑全量几千万行的大表 Join 来排查；
   - 绑定一个固定切片（例如 `store_code = 1009011769`），在 5~8 秒内端到端跑通该切片并打印字段中间值，快速锁定关联断裂点。

---

## 2. MaxCompute 类型转换隐式 NULL 陷阱

MaxCompute 2.0 在某些类型转换失败时**不抛出语法错误，而是静默返回 `NULL`**，极易导致全链路条件失效归零。

### 致命反模式 (Bad Pattern)
```sql
-- 反模式：TO_DATE 产生带时间精度的 DATETIME，外层 CAST 为 DATE 时静默返回 NULL
CAST(
    CASE
        WHEN effective_end_date IS NOT NULL THEN TO_DATE(effective_end_date, 'yyyy-mm-dd')
        ELSE TO_DATE('${bdp.system.bizdate}', 'yyyymmdd')
    END AS DATE
) AS c_e_date
```
- **问题**：`TO_DATE('20260921', 'yyyymmdd')` 产出 `DATETIME`（如 `'2026-09-21 00:00:00'`）；`CAST('2026-09-21 00:00:00' AS DATE)` **在 MaxCompute 中静默返回 `NULL`**！
- **后果**：`c_e_date` 为 `NULL`，导致后续 `d.day_date BETWEEN w.start_date AND w.end_date` 全为假，`valid_date` 0 行，全链路变空。

### 正确模式 (Best Practice)
```sql
-- 统一使用等长的标准格式字符串（'YYYY-MM-DD'）做区间过滤
date_input AS (
    SELECT
        batch_code,
        effective_start_date AS c_s_date,
        CASE
            WHEN effective_end_date IS NOT NULL AND TRIM(effective_end_date) <> ''
                THEN LEAST(
                    effective_end_date,
                    CONCAT(SUBSTR('${bdp.system.bizdate}', 1, 4), '-', SUBSTR('${bdp.system.bizdate}', 5, 2), '-', SUBSTR('${bdp.system.bizdate}', 7, 2))
                )
            ELSE CONCAT(SUBSTR('${bdp.system.bizdate}', 1, 4), '-', SUBSTR('${bdp.system.bizdate}', 5, 2), '-', SUBSTR('${bdp.system.bizdate}', 7, 2))
        END AS c_e_date
    FROM batch_contract
)
```
- 保证 `dim_day.day_date`（字符串）与窗口日期（字符串）类型一致，消除跨类型隐式转换风险。

---

## 3. 编译器拦截防护与执行计划门禁

在提交 DataWorks 生产节点前，必须在本地或预检执行 `EXPLAIN` 校验：

1. **CTAS 分区限制**：
   - MaxCompute **不支持** `CREATE TABLE ... PARTITIONED BY (pt STRING) AS SELECT ...`；
   - 正确写法：提前预建分区表（带完整字段与分区注释） $\rightarrow$ 运行 `INSERT OVERWRITE TABLE ... PARTITION (pt = ...)`。
2. **广播小表强制 MapJoin**：
   - 维表展开或笛卡尔积（如 `dim_store CROSS JOIN batch_contract`）必须显式标记 `/*+ MAPJOIN(b) */`，否则编译器直接抛出 `Cartesian product is not allowed without mapjoin`。
3. **大表静态分区剪裁**：
   - 扫描 POS 库存表等海量明细表（如 `dwd_pos_dsl_bms_st_qty_lst_rt`）必须包含编译期静态分区下限（如 `stat_date >= 20240101`），防止全表扫描被平台阻断。
4. **项目库解耦宏替换**：
   - 工作流中的业务表统一使用 `${dsl_analysis}.table_name` 宏定义，支持在 DataWorks 中通过单变量自由切换 `dsl_analysis_dev`（开发库）与 `dsl_analysis`（正式库）。
