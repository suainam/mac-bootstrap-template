# 表分析检查清单

在开始分析前，先理解数据的结构和质量。

---

## 快速分析模板

复制这个 SQL 块，替换 `your_table` 开始分析：

```sql
-- ============================================================
-- 表分析检查清单：your_table
-- ============================================================

-- 1. 基本统计
SELECT 
  COUNT(*) AS row_count,
  COUNT(DISTINCT primary_key) AS unique_keys,
  MIN(created_at) AS earliest_date,
  MAX(created_at) AS latest_date,
  DATEDIFF('day', MIN(created_at), MAX(created_at)) AS date_range_days
FROM your_table;

-- 2. 键唯一性检查
SELECT 
  primary_key,
  COUNT(*) AS occurrences
FROM your_table
GROUP BY primary_key
HAVING COUNT(*) > 1
ORDER BY occurrences DESC
LIMIT 10;

-- 3. 空值分析
SELECT 
  COUNT(*) AS total_rows,
  SUM(CASE WHEN col1 IS NULL THEN 1 ELSE 0 END) AS col1_nulls,
  SUM(CASE WHEN col2 IS NULL THEN 1 ELSE 0 END) AS col2_nulls,
  SUM(CASE WHEN col3 IS NULL THEN 1 ELSE 0 END) AS col3_nulls,
  -- 添加更多列
  ROUND(100.0 * SUM(CASE WHEN col1 IS NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS col1_null_pct
FROM your_table;

-- 4. 基数分析（离散值分布）
SELECT 
  'col1' AS column_name,
  COUNT(DISTINCT col1) AS distinct_values,
  COUNT(*) AS total_rows,
  ROUND(100.0 * COUNT(DISTINCT col1) / COUNT(*), 2) AS cardinality_pct
FROM your_table
UNION ALL
SELECT 
  'col2',
  COUNT(DISTINCT col2),
  COUNT(*),
  ROUND(100.0 * COUNT(DISTINCT col2) / COUNT(*), 2)
FROM your_table;

-- 5. 值分布（Top N）
SELECT 
  col1,
  COUNT(*) AS occurrences,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_total
FROM your_table
GROUP BY col1
ORDER BY occurrences DESC
LIMIT 10;

-- 6. 数值列统计
SELECT 
  COUNT(*) AS n,
  AVG(numeric_col) AS mean,
  MEDIAN(numeric_col) AS median,
  MIN(numeric_col) AS min,
  MAX(numeric_col) AS max,
  STDDEV(numeric_col) AS stddev,
  -- 四分位数（如果数据库支持）
  PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY numeric_col) AS q1,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY numeric_col) AS q3
FROM your_table;

-- 7. 时间分布
SELECT 
  DATE_TRUNC('month', date_col) AS month,
  COUNT(*) AS row_count
FROM your_table
GROUP BY 1
ORDER BY 1;

-- 8. 数据新鲜度
SELECT 
  MAX(updated_at) AS last_update,
  DATEDIFF('hour', MAX(updated_at), CURRENT_TIMESTAMP) AS hours_since_update
FROM your_table;
```

---

## 检查清单

在开始任何分析前，回答这些问题：

### 数据粒度（Grain）
- [ ] 每行代表什么？（一个订单？一个用户？一个事件？）
- [ ] 主键是什么？
- [ ] 主键是唯一的吗？

### 时间维度
- [ ] 数据覆盖什么时间范围？
- [ ] 最新数据是什么时候？
- [ ] 是否有时区问题？
- [ ] 是否有历史数据变更/重刷？

### 数据质量
- [ ] 哪些列有空值？空值比例多少？
- [ ] 是否有异常值/离群点？
- [ ] 是否有重复记录？
- [ ] 枚举列的值分布合理吗？

### 关系和依赖
- [ ] 这张表与哪些表关联？
- [ ] Join 键在两边都是唯一的吗？
- [ ] Join 会是 1:1, 1:N, 还是 N:M？

---

## 常见陷阱

### 陷阱 1: 假设键唯一性
**错误**:
```sql
SELECT 
  u.user_id,
  o.order_total
FROM users u
JOIN orders o ON u.user_id = o.user_id;
```

**问题**: 如果一个用户有多个订单，结果会爆炸

**正确**:
```sql
-- 先验证键
SELECT user_id, COUNT(*) 
FROM orders 
GROUP BY user_id 
HAVING COUNT(*) > 1;

-- 然后明确聚合
SELECT 
  u.user_id,
  SUM(o.order_total) AS total_spent
FROM users u
JOIN orders o ON u.user_id = o.user_id
GROUP BY u.user_id;
```

### 陷阱 2: 忽略空值

**错误**:
```sql
SELECT AVG(rating) FROM reviews;
-- 结果: 4.2
```

**问题**: 空值被排除，可能误导（大量空值 = 大量无评分）

**正确**:
```sql
SELECT 
  AVG(rating) AS avg_rating,
  COUNT(*) AS total_reviews,
  COUNT(rating) AS reviews_with_rating,
  COUNT(*) - COUNT(rating) AS missing_ratings,
  ROUND(100.0 * COUNT(rating) / COUNT(*), 2) AS rating_coverage_pct
FROM reviews;
```

### 陷阱 3: 未检查时间范围

**错误**:
```sql
SELECT DATE_TRUNC('month', order_date), COUNT(*)
FROM orders
GROUP BY 1;
```

**问题**: 当月数据可能不完整

**正确**:
```sql
SELECT 
  DATE_TRUNC('month', order_date) AS month,
  COUNT(*) AS orders,
  CASE 
    WHEN DATE_TRUNC('month', order_date) = DATE_TRUNC('month', CURRENT_DATE)
    THEN 'Incomplete'
    ELSE 'Complete'
  END AS month_status
FROM orders
GROUP BY 1
ORDER BY 1 DESC;
```

---

## DuckDB 本地分析

分析 CSV/Parquet 时保持 SQL 习惯：

```sql
-- 直接查询 CSV
SELECT * 
FROM 'data/orders.csv' 
LIMIT 10;

-- 多文件聚合
SELECT 
  DATE_TRUNC('month', order_date) AS month,
  COUNT(*) AS orders
FROM 'data/orders_*.csv'
GROUP BY 1;

-- CSV → Parquet 转换
COPY (
  SELECT * FROM 'data/orders.csv'
) TO 'data/orders.parquet' (FORMAT PARQUET);

-- 检查 Parquet schema
DESCRIBE SELECT * FROM 'data/orders.parquet';
```

---

## 自动化检查脚本

保存为 `scripts/profile_table.sql`：

```sql
-- 使用方法: duckdb -c ".read scripts/profile_table.sql" -var table=your_table

.mode markdown
.header on

.print ============================================================
.print Table Profile: ${table}
.print ============================================================
.print

.print --- Row Count ---
SELECT COUNT(*) AS row_count FROM ${table};

.print
.print --- Sample Rows ---
SELECT * FROM ${table} LIMIT 5;

.print
.print --- Column Types ---
DESCRIBE ${table};

.print
.print --- Null Counts ---
-- 动态生成所有列的空值统计
-- （需要根据实际列名调整）
```

---

## 输出模板

分析结果应包含：

```markdown
## 表：orders

**粒度**: 每行 = 一个订单

**时间范围**: 2023-01-01 至 2024-07-13（561 天）

**行数**: 1,245,678

**主键**: order_id（唯一性：✓）

**数据质量**:
- user_id: 0.2% 空值
- product_id: 0% 空值
- amount: 1.5% 空值（可能是取消订单）

**关联**:
- users: 1:N（一个用户多个订单）
- products: N:1（多个订单可以是同一产品）

**注意事项**:
- 2024-07 数据不完整（仅 13 天）
- amount 有 15 个异常值 > $10,000（已验证为真实大额订单）
```
