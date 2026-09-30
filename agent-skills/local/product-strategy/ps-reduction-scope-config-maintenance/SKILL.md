---
name: ps-reduction-scope-config-maintenance
description: Use when adding, changing, disabling, or validating non-catalogue reduction scope rules in MaxCompute config tables; verifies province/region codes, stages changes in dsl_analysis_dev, then safely overwrites production.
---

# 缩铺范围配置表维护

## 流程

1. **核对范围与业务日期**：从用户请求确定省区/营运区、策略、版本名及生效区间。业务编码必须查 `dsl_dim.dim_store` 最新 `stat_date` 分区，不依据记忆或旧规则猜测。工作流按昨日业务日期 `${yyyyMMdd-1d}` 过滤；确保 `start_date <= target_business_date <= end_date`。
2. **读取正式全量配置**：从 `dsl_analysis.analysis_non_catalogue_reduction_scope_config_df` 读取全部行及 schema。确认拟用 `rule_id` 未占用。配置表是非事务表；对规则只生成全量覆写，不对生产直接 `UPDATE`/单行 `INSERT`。
3. **预览变更**：保留每一条现有规则原值；仅按明确要求修改停用规则的 `is_active`，新增规则分配新 `rule_id`。输出差异、目标计数与 SQL 预览；用户要求/授权前不写生产。
4. **开发验证**：项目为 `dsl_analysis_dev`。同名表不存在时按正式表 schema 创建；使用 `INSERT OVERWRITE` 写入正式现有全量规则加变更后的全量集合（不仅只写新增记录）。查询回读，验证 schema、行数、主键唯一性、所有保留行一致、新增/修改记录字段正确。
5. **生产落库**：开发验证全通过后，将同一份经验证的全量数据覆写到 `dsl_analysis.analysis_non_catalogue_reduction_scope_config_df`。写入前再核对生产行数/规则集合未发生竞态变化；变化则停止、重新合并与验证。覆写成功后重读整表，验证总行数、主键唯一、旧规则保留/修改、新规则字段正确。不要把只含变更记录的开发表直接覆写到生产。
6. **同步文档**：更新专题 README 与配置维护指南/SOP 的变更记录。清楚标注生产是否已写入、目标生效日期。只报告真实完成的阶段。

## 安全边界

- 凭据从 `~/.env` 读取；仅输出变量是否存在，不打印凭据值。
- 先执行只读探测与开发库验证；生产覆写是破坏性全表操作，必须先准备并验证完整行集。
- ODPS 网络瞬断（如 `SSLEOFError`）时，对同一明确 SQL 进行有限指数退避重试；写入超时后先查询目标状态，避免盲目重复追加。
- 项目/权限不明确时先确认；不要擅自把其他库名当作开发库。

## 参考资料

- [参考规则与列定义](references/config-contract.md)
- [SQL 模板](examples/config_change.sql)
- [操作脚本](scripts/README.md)
