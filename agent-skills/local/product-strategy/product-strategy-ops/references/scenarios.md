# 场景索引

路径相对仓库根目录。下表是已有入口盘点，不代表实际调用频率统计。执行前读取来源文件，确认当前参数和副作用。

请求涉及 non_catalogue_clear 或 auto_display 时，先读 [详细作业分支](operations.md)，覆盖查看、追加、配置、重建、校验、导出、比较和测试的不同副作用。

| 请求 | 读取来源 | 入口及验收 |
|---|---|---|
| 更新专题目录索引 | `scripts/generate_topic_indexes.py`、根 `README.md` | 根目录运行 `rtk uv run python scripts/generate_topic_indexes.py`，随后加 `--check` 验证；检查两个生成索引的 diff |
| DataWorks 工作流快照 | `shared/WORKFLOW_SNAPSHOT_GUIDE.md`、`shared/dataworks_snapshot.py` | 使用文档中的 `uv run --extra lineage python` 入口，补齐 project/env/workflow/node IDs；核对报告节点、SQL、DDL及缓存状态 |
| 单表上下游血缘 | `shared/dataworks_lineage.py` | 先读取参数解析及帮助；核对环境、表和递归范围，报告无法读取的节点 |
| 专题 ODPS 导出 | `shared/make/odps_export.mk`、目标专题 `03_analysis/scripts/Makefile` 与 `odps_export_config.py` | 对支持该规则的专题先 `rtk make -C <scripts目录> export-dry-run`；核对实际 runner、容器、凭证文件路径和导出项后再运行 export；按格式检查产物 |
| 自动陈列最新指标/对比 | `topics/auto_display/README.md`、`03_analysis/scripts/Makefile` | `rtk make -C topics/auto_display/03_analysis/scripts metrics-help`；metrics-latest、metrics-refresh、metrics-rebuild 都会重建远端表，执行前确认写入范围；metrics-compare 对比已有 Excel；核对业务截止日与工作簿 |
| 缩铺进度 | `topics/non_catalogue_clear/README.md`、`03_analysis/scripts/Makefile` | `rtk make -C topics/non_catalogue_clear/03_analysis/scripts progress STAT_DATE=<日期>` 会追加报告；仅查看时使用 README 中不带 append 的分析命令；核对本期/上期口径 |
| 门店 TOP10 缩铺统计 | `topics/non_catalogue_clear/README.md`、`03_analysis/scripts/store_gz1_top10.py` | 按 README 使用 end-date/format；核对营运区、排名及店品粒度 |
| O2O 货盘 | `topics/o2o_store/AGENTS.md`、`README.md`、`03_analysis/scripts/README_JDT_HIVE100.md` | 先区分城市 TOP2500 和 JDT 蜂窝100%两条链，再读取对应 run/export/audit 入口；核对月份、城市及门店展开口径 |
| 季节性商品池 | `topics/seasonal_item/README.md` | 读取池展开命令及输出契约；核对月份、商品池与产物路径 |
| 门店匹配分析 | `topics/store_selection/README.md` | 使用文档指定的 store-selection extra 与分析入口，核对匹配结果 |
| 智能组货工作流 | `topics/smart_assortment/README.md` | 快照沿用共享工具；补数先读取专题补数脚本与 `shared/dataworks_batch_backfill.py`，明确日期、节点和远端写入授权；核对所有实例终态 |
| 组货模型复盘、参数曲线、必要性诊断 | [组货复盘入口](assortment.md) | 进入 `topics/assortment/202608组货模型复盘/`，使用该目录的批次索引和报告指针；此场景独立于 smart_assortment |
| 网页/视频交付 | 专题 README、现有 web-video-presentation-delivery 等交付 skill | 使用已有交付 skill；本入口只定位素材与专题，完成标准由该交付流程负责 |

通用导出规则依赖仓库外 runner 和既有容器；预览前先检查其实际可用性。日常调度脚本位于 `scripts/daily_morning.sh`、`daily_evening.py`、`install_launchd.sh`，属于另一类系统集成；需要该场景时先读脚本并确定外部写入范围。

`shared/dataworks_batch_backfill.py` 的 CLI 仅演示参数解析；实际补数由专题提供 SQL builder 并调用共享函数。
