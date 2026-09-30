# 配置表契约

正式表：`dsl_analysis.analysis_non_catalogue_reduction_scope_config_df`。开发表：`dsl_analysis_dev.analysis_non_catalogue_reduction_scope_config_df`。

字段顺序：

`rule_id BIGINT, priority INT, version_dt STRING, prov_zone_man_cd BIGINT, prov_zone_man_nm STRING, region_man_code BIGINT, region_man_name STRING, match_type STRING, strategy_type STRING, start_date BIGINT, end_date BIGINT, is_active INT`

规则：

- 表为非事务表；规则变更以全量 `INSERT OVERWRITE` 落库。
- `priority`: 营运区精确 1、省区 2、全通配 3。
- `prov_zone_man_cd=-1` 表示全省区通配；`region_man_code=-1` 表示省区下全部营运区。
- `match_type`: `INCLUDE` / `EXCLUDE`。
- `strategy_type`: `ALL_PREFIX`, `NORMAL`, `NONO2O_DS`, `O2O_CENTER`。
- 规则有效日包含起止日，且必须覆盖工作流业务日期（通常为昨日）。
- 编码查询示例：

```sql
SELECT DISTINCT prov_zone_man_cd, prov_zone_man_nm, region_man_code, region_man_name
FROM dsl_dim.dim_store
WHERE stat_date = (SELECT MAX(stat_date) FROM dsl_dim.dim_store)
  AND prov_zone_man_nm RLIKE '目标省区';
```

- 仲裁顺序：`priority ASC, start_date DESC, end_date ASC, rule_id DESC`。
- 唯一性门禁：`rule_id` 必须唯一；目标表行数必须等于保留行与新增行的预期总和。
