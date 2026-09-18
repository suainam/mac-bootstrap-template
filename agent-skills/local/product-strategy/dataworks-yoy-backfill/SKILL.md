---
name: dataworks-yoy-backfill
description: DataWorks OpenAPI 工作流快照抽取（增量/断点续传）、表级血缘追踪，以及 MaxCompute 多分区并发批量回刷与 YoY 同店漂移修复。当用户需要拉取/更新工作流节点与表结构快照、分析表依赖、批量补历史分区、或修复同比可比口径时使用。
---

# DataWorks 工作流快照与批量分区回刷

跨专题通用的 DataWorks 生产工作流快照拉取、表级血缘追踪、MaxCompute SDK 多分区高效回刷与 YoY 可比店同店漂移修复。

---

## 核心流程与步骤

### 流程一：工作流快照拉取 (Snapshot)

当工作流发版、需要更新生产 SQL、或者梳理表结构与数据流图时执行：

1. **确定子节点列表 (官方 FolderPath 精准反查)**:
   - 若已知完整子节点列表，直接传入 `--node-ids`；
   - 若不确定发版后是否有新增节点，按 [快照契约](references/workflow-snapshot-contract.md) 中的两步反查法：
     通过任一已知节点名调用 `ListFiles` 获取 `FileFolderId` $\rightarrow$ 调用 `GetFolder` 解析出完整的 `FolderPath` $\rightarrow$ 调用 `ListFiles(file_folder_path=...)` 获取当前工作流下的全部真实生产节点（不多不少，100% 精确覆盖）。
2. **执行快照拉取**:
   ```bash
   uv run --extra lineage python scripts/dataworks_snapshot.py \
     --project-id 175690 \
     --env PROD \
     --workflow-id <WORKFLOW_ID> \
     --node-ids <NODE_ID_1>,<NODE_ID_2>,... \
     --cache /tmp/wf_<WORKFLOW_ID>_cache.json \
     --schemas-cache /tmp/wf_<WORKFLOW_ID>_schemas.json \
     --out topics/<TOPIC_ID>/00_context/workflow_<WORKFLOW_ID>_prod_YYYYMMDD.md \
     --force-refresh
   ```
3. **版本归档与契约闭环**:
   - 将该工作流的旧版快照通过 `git mv` 归档到对应专题的 `00_context/archive/` 目录；
   - 更新专题 `README.md` 中指向最新快照的路径；
   - 运行 `uv run python scripts/generate_topic_indexes.py --check` 校验全局索引一致性。

### 流程二：表级血缘追踪 (Lineage)

追踪任一 MaxCompute / DataWorks 表的上下游数据链路：

```bash
uv run --extra lineage python scripts/dataworks_lineage.py \
  --table dsl_ads.ads_item_content_store_all_stat \
  --direction up \
  --depth 3
```

### 流程三：批量历史分区并发回刷 (Batch Backfill)

当需要回刷数十至数百天历史分区数据时（替代低效的 DataWorks DAG 逐日补数）：

1. **构建单日 Multi-Table INSERT SQL**:
   采用纯 CTE 结构，单条 SQL 同时写入所有目标表，杜绝中间临时表。
2. **配置季度切片与并发**:
   参考 [并发回刷契约](references/yoy-drift-and-backfill-contract.md) 与 [模板配置](templates/backfill_config.yaml)：
   - 默认采用 16 线程池并发；
   - 开启 MaxCompute 分区存在性预检（已存在分区秒级跳过，支持断点续跑）；
   - 按自然季度倒序推进（新 $\rightarrow$ 旧）。
3. **验证回刷结果**:
   实查目标表分区连续性与行数；对 YoY 修复节点核对门店配对率 $\ge 99.96\%$。

---

## 凭据配置优先级

脚本自动按以下优先级加载阿里云凭据，无需硬编码：

1. 环境变量：`ODPS_ACCESS_ID` / `ODPS_SECRET_KEY` / `DATAWORKS_ENDPOINT` / `ODPS_ENDPOINT`
2. 本地 `.env` 文件（按顺序自动查找）：
   - `~/work/projects/www/marimo/merchandise/.env`
   - `~/work/config/shared/.env`
   - `topics/<TOPIC_ID>/.env`

---

## 规范引用文件

- [快照机制与文件夹精准反查契约](references/workflow-snapshot-contract.md)
- [YoY 漂移修复范式与并发回刷契约](references/yoy-drift-and-backfill-contract.md)
- [实战案例：智能组货 10002308897 工作流快照与 628 天回刷](examples/smart_assortment_case.md)
- [批量回刷配置模板](templates/backfill_config.yaml)
