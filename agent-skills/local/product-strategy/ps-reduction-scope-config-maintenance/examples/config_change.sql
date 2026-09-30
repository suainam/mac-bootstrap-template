-- Pattern only. Never execute this incomplete illustration as-is.
-- First load the complete current production snapshot; preserve every unchanged row.

CREATE TABLE IF NOT EXISTS dsl_analysis_dev.analysis_non_catalogue_reduction_scope_config_df (
  rule_id BIGINT,
  priority INT,
  version_dt STRING,
  prov_zone_man_cd BIGINT,
  prov_zone_man_nm STRING,
  region_man_code BIGINT,
  region_man_name STRING,
  match_type STRING,
  strategy_type STRING,
  start_date BIGINT,
  end_date BIGINT,
  is_active INT
);

-- Development target must contain ALL snapshot rows plus approved changes.
-- Generate the full VALUES list from the snapshot; do not use a delta-only list.
-- INSERT OVERWRITE TABLE dsl_analysis_dev.analysis_non_catalogue_reduction_scope_config_df
-- VALUES
--   (... every unchanged and changed rule ...),
--   (73, 2, '辽宁省区直营店缩铺', 1011003, '辽宁省区', -1, '全部', 'INCLUDE', 'ALL_PREFIX', 20260928, 20260930, 1);

-- Only after development validation and fresh production snapshot comparison:
-- INSERT OVERWRITE TABLE dsl_analysis.analysis_non_catalogue_reduction_scope_config_df
-- SELECT * FROM dsl_analysis_dev.analysis_non_catalogue_reduction_scope_config_df;
-- Safe only when dev table contains the complete validated snapshot.
