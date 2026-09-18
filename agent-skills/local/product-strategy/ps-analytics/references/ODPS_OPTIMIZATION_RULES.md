# ODPS 性能优化与防踩坑规约

在 MaxCompute (ODPS) 执行大规模数据分析时，必须遵守以下工程性能与防踩坑准则。

---

## 1. 分区定位：全面拥抱 `MAX_PT()` 原生语法

### 反模式 (Bad Pattern)
```sql
-- 严禁书写嵌套标量子查询求最新分区
WHERE stat_date = (SELECT MAX(stat_date) FROM dsl_ads.ads_item_3he1_db_1_6_store_item_xiafa_df)
```
- **问题**：MaxCompute 编译器无法在编译期静态剪枝（Partition Pruning），会导致 Map 阶段对底层元数据或全量历史进行无谓扫描，大幅增加排队延迟与开销。

### 正确模式 (Best Practice)
```sql
-- 统一使用 MaxCompute 原生 MAX_PT() 宏函数
WHERE stat_date = MAX_PT('dsl_ads.ads_item_3he1_db_1_6_store_item_xiafa_df')
```
- **优势**：执行计划在 Compile 阶段直接解析为常量（如 `stat_date = '20260915'`），实现物理分区的毫秒级准确定位与剪枝。
- **带前缀/限定表名**：`MAX_PT('project.table_name')` 必须传入包含项目名的全表名字符串。

---

## 2. 多版本并发防笛卡尔积聚合 (Deduplication Layer)

### 场景背景
在企业数仓中，中间层表（如 `ads_item_3he1_db_1_6_store_item_list_df`）常常同时存放：
1. 月度常规目录版本（如 `version_id = 100000000011`）；
2. 季度大促目录更新版本；
3. 新店/小店专项版本（如 `version_id = 2099330...`）。

### 规约要求
当需要将该表作为维表或属性表进行 `LEFT JOIN` / `INNER JOIN` 时，**绝对禁止直接在关联条件中仅用 `store_code + item_code` 关联**，否则会产生严重的笛卡尔积行数放大。

### 标准聚合收敛 CTE 模式
```sql
dedup_list AS (
    SELECT 
        store_code,
        item_code,
        MAX(CASE WHEN is_brand_item = 1 THEN 1 ELSE 0 END) as is_brand_item,
        MAX(CASE WHEN is_add_push_class_item = 1 THEN 1 ELSE 0 END) as is_add_push_class_item,
        MAX(CASE WHEN is_xsbd_item = 1 THEN 1 ELSE 0 END) as is_xsbd_item,
        MAX(CASE WHEN is_new_product_add_or_delete_code = 1 THEN 1 ELSE 0 END) as is_new_product,
        MAX(CASE WHEN is_zypp_item_action_code = 1 THEN 1 ELSE 0 END) as is_zypp,
        MAX(CASE WHEN is_o2o_store_item = 1 THEN 1 ELSE 0 END) as is_o2o_store
    FROM dsl_ads.ads_item_3he1_db_1_6_store_item_list_df
    WHERE stat_date = MAX_PT('dsl_ads.ads_item_3he1_db_1_6_store_item_list_df')
    GROUP BY store_code, item_code
)
```
- 通过 `GROUP BY store_code, item_code` 强制收敛粒度；
- 通过 `MAX(CASE WHEN ...)` 压平跨版本的多重打标，确保下游属性判定 100% 幂等。

---

## 3. 计算资源调度优化

1. **计算 Project 动态切换**：
   - 默认通过 `ODPSConfig` 读取时，可通过环境变量切至资源更充足或高优先级的业务队列：
     ```python
     os.environ["ODPS_PROJECT"] = "dsl_ads"
     ```
   - 实测在分析作业中，`dsl_ads` 的实例调度等待时间比通用分析项目降低 60% 以上。
2. **只读审计原则**：
   - 分析探索与数据拉取一律采用只读 SELECT，严禁使用 CTAS 或无谓创建临时表污染生产库。
3. **安全行数限制**：
   - 单次明细下载严禁突破 1,000,000 行限制；若数据量过大，必须先在 SQL 侧按维度 `GROUP BY` 聚合。
