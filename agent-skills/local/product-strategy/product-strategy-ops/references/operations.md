# 缩铺与自动陈列

路径相对 product_strategy 根目录。命令以专题 Makefile 为准，先读取 README 的业务口径与日期约束。

## non_catalogue_clear

- 查看进度：读 `topics/non_catalogue_clear/03_analysis/scripts/analyze_reduction_rlt.py` 参数，使用不带 `--append` 的调用；核对 stat-date 与 previous-date，不把“查看”转换为改报告。
- 追加进度：专题 Makefile 的 `progress STAT_DATE=<日期>`，会写跟踪 Markdown；执行前检查目标报告已有日期，重复调用先确认是否已写入。
- 门店 TOP10：读 `store_gz1_top10.py` 和专题 README；核对营运区、统计截止日、店品与批次粒度及排名方向。
- 配置调整：读 README 的业务配置表 SOP、`00_context/reduction_progress_tracking_sop.md` 与对应 SQL；配置写入另确认目标与范围，不通过改分析脚本伪造策略效果。
- 导出：沿用 `export-dry-run/export/export-parquet/export-excel/export-reuse`；检查日期参数、选定导出项、实际 runner 及输出路径。
- 回归：专题 Makefile 的 `test`、`test-scope`；README 中旧的 `scope-test` 名称不能直接调用，当前目标为 `test-scope`。

## auto_display

工作目录入口 `topics/auto_display/03_analysis/scripts/Makefile`。

| 需求 | 目标 | 实际作用与验收 |
|---|---|---|
| 昨日最新指标 | metrics-latest | 依赖 metrics-refresh，重建远端表、校验、导出；先授权写表并核对截止日 |
| 指定截止日全流程 | metrics-refresh | 重建后导出；读取 README 的日期变量及生命周期规则 |
| 只重建 | metrics-rebuild | 写 MaxCompute 并校验，不能当只读探查 |
| 校验已有表 | metrics-validate | 核对现有表与分析截止日是否一致 |
| 导出现有指标 | metrics-excel | 校验后生成 Excel，检查工作簿及实际输出文件 |
| 比较两版工作簿 | metrics-compare | 指定旧/新工作簿或日期，核对比较方向；不默认重建 |
| 生成工作流 SQL | metrics-sql | 生成 SQL 文件，不等于远端执行成功；交付文件并说明待执行 |
| 本地回归 | metrics-test | 静态测试结果与业务在线验收分开报告 |
| 在线回归 | metrics-test-live | 执行前读取 live 测试及环境约束，确认云端范围 |
| 通用导出 | export 系列 | 与试验指标工作簿是不同产物，使用场景索引的导出流程 |

这些目标的完整变量和默认值只在 Makefile/README 维护。帮助输出、SQL 生成、任务提交、Excel 文件存在分别只证明对应阶段，不能互相替代。
