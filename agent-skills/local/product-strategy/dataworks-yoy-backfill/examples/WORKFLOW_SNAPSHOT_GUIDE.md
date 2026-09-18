# DataWorks 工作流与表血缘提取指引

本模块提供可跨专题复用的 DataWorks 生产/开发态工作流快照与表血缘提取能力。支持一键生成包含**节点 SQL、调度参数、真实表 DDL、工作流拓扑图、外部源表清单**的完整结构化快照报告。

---

## 1. 核心组件

| 文件 | 定位 | 职责 |
|---|---|---|
| `shared/dataworks_snapshot.py` | CLI 执行器 | 串联 DataWorks OpenAPI 与 MaxCompute SDK，支持**增量检查**与**断点续传** |
| `shared/workflow_snapshot_core.py` | 纯函数核心库 | SQL 正则解析、INSERT 归属表判定、MaxCompute DDL 拼装、Mermaid 拓扑渲染 |
| `shared/dataworks_lineage.py` | 单表血缘工具 | 基于 DataWorks 数据地图 API 进行任意单表的多级递归上下游血缘追踪 |

---

## 2. 快速开始

### 2.1 依赖环境
确保已安装 optional lineage 依赖：
```bash
uv sync --extra lineage
```

### 2.2 提取工作流快照

```bash
uv run --extra lineage python shared/dataworks_snapshot.py \
  --project-id <dataworks_project_id> \
  --env PROD \
  --workflow-id <workflow_id> \
  --node-ids <node_id_1>,<node_id_2>,... \
  --cache /tmp/wf_<workflow_id>_cache.json \
  --schemas-cache /tmp/wf_<workflow_id>_schemas.json \
  --out topics/<topic_id>/00_context/workflow_<workflow_id>_prod_YYYYMMDD.md
```

#### 参数说明
- `--project-id`: DataWorks 工作空间 ID（例如数智中台部 `175690`）。
- `--env`: 目标环境，`PROD`（生产态）或 `DEV`（开发态/未发版）。
- `--workflow-id`: 工作流根节点 ID。
- `--node-ids`: 工作流包含的子节点 ID 列表（逗号分隔，按执行顺序或逻辑顺序排列）。
- `--cache`: 节点元数据与 SQL 断点续传缓存文件路径。
- `--schemas-cache`: MaxCompute 表结构元数据缓存文件路径。
- `--out`: 最终生成的 Markdown 报告输出路径。
- `--force-refresh`: （可选）强制跳过本地时间戳对比，全量重新从云端拉取。

---

## 3. 核心机制说明

1. **增量比对 (Incremental)**：
   - 每次执行先通过 `GetNode` 读取云端最新 `ModifyTime`。
   - 若时间戳与本地 cache 一致，跳过耗时的 `GetNodeCode` 与上下游 IO 查询。
2. **断点续传 (Checkpoint)**：
   - 每拉取完一个节点立即原子写入磁盘缓存。即使网络抖动中断，重跑时自动从断点继续。
3. **归属表判定 (Ownership)**：
   - 仅将含有 `INSERT OVERWRITE` / `INSERT INTO` 写入目标的表判定为“归属于工作流的产出表”。
   - 纯 `CREATE TABLE` 临时表（CTAS）不会作为最终表结构重复拉取。
4. **真实 DDL 拼装**：
   - 从 MaxCompute 表元数据中提取实际列名、列类型、列注释、分区键与表注释，标准化拼装为 `CREATE TABLE` DDL，消除云端 API 占位符。
5. **工作流拓扑图 (Topology)**：
   - 自动分析跨节点数据流向（节点 A INSERT 的表被节点 B 读取），生成紧凑直观的 Mermaid 架构图。

---

## 4. 报告章节规范

生成的 Markdown 快照固定包含五大章节：
1. **一、节点概览**：表格汇总各节点 ID、名称、类型、INSERT 产出表数、ModifyTime。
2. **二、归属表结构**：按节点顺序展示归属表的完整 `CREATE TABLE` DDL（含字段注释、分区、表注释）。
3. **三、工作流拓扑与表血缘**：Mermaid 流程图，直观表达外部依赖表 → 节点 → 产出表 → 下游节点。
4. **四、引用的外部数据源表**：汇总所有外部输入表及对应的引用节点。
5. **五、各节点完整 SQL 与元数据**：记录每个节点完整的生产 SQL、调度周期、Owner 及参数配置。
