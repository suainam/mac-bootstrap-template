# DataWorks 生产工作流快照与表血缘提取规范

## 一、核心机制与规范

1. **增量比对 (Incremental)**：
   - 每次执行先通过 `GetNode` 读取云端最新 `ModifyTime`。
   - 若时间戳与本地 cache 一致，跳过耗时的 `GetNodeCode` 与上下游 IO 查询。
2. **断点续传 (Checkpoint)**：
   - 每拉取完一个节点立即原子写入磁盘缓存。即使网络中断，重跑时自动从断点继续。
3. **归属表判定 (Ownership)**：
   - 仅将含有 `INSERT OVERWRITE` / `INSERT INTO` 写入目标的表判定为“归属于工作流的产出表”。
   - 纯 `CREATE TABLE` 临时表（CTAS）不会作为最终表结构重复拉取。
4. **真实 DDL 拼装**：
   - 从 MaxCompute 表元数据中提取实际列名、列类型、列注释、分区键与表注释，标准化拼装为 `CREATE TABLE` DDL，消除云端 API 占位符。
5. **工作流拓扑图 (Topology)**：
   - 自动分析跨节点数据流向（节点 A INSERT 的表被节点 B 读取），生成紧凑直观的 Mermaid 架构图。

---

## 二、官方 OpenAPI 节点精准反查 SOP (避坑规范)

在 DataWorks OpenAPI 中，工作流子节点不能通过 `GetNodeChildren`（这是 DAG 依赖而非目录包含）查询，也不能使用宽泛关键词搜索。
**唯一精准链路为**：
$$\text{目标文件/根节点} \xrightarrow{\text{ListFiles}} \text{FileFolderId} \xrightarrow{\text{GetFolder}} \mathbf{FolderPath} \xrightarrow{\text{ListFiles(file\_folder\_path=...)}} \mathbf{全部子节点}$$

1. **步骤一**：调用 `ListFiles(project_id, keyword=exact_name, page_size=10)` 获取对应 `FileFolderId`。
2. **步骤二**：调用 `GetFolder(project_id, folder_id=FileFolderId)` 解析出真实物理路径（如：`个人/数据运营/<owner>/目录外/non_catalogue_store_item_info_df.目录外商品情况`）。
3. **步骤三**：调用 `ListFiles(project_id, file_folder_path=FolderPath, page_size=100)`：秒级返回当前工作流下的全部真实生产节点（不多不少，100% 精确，且自动覆盖新上线发版节点）。

---

## 三、版本归档与规范交付

1. **发版强刷**: 线上发版后必须带 `--force-refresh` 参数，强刷云端最新的 `ModifyTime` 与源码，避免本地 cache 命中旧逻辑。
2. **版本归档**: 新快照命名严格按 `workflow_<WORKFLOW_ID>_prod_YYYYMMDD.md`。将旧版本使用 `git mv` 移动到 `topics/<TOPIC_ID>/00_context/archive/`。
3. **报告五大标准章节**:
   - 节点概览（ID、名称、类型、产出表数、ModifyTime）
   - 归属表结构（完整 CREATE TABLE DDL 含字段注释、分区、表注释）
   - 工作流拓扑与表血缘（Mermaid 流程图）
   - 引用的外部数据源表（汇总所有外部输入表及对应引用节点）
   - 各节点完整 SQL 与元数据（生产 SQL、调度周期、Owner、参数配置）
