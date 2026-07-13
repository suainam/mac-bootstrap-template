# Join 模式和验证

常见 join 模式、陷阱和验证查询。

---

## Join 类型速查

| 类型 | 说明 | 何时使用 |
|------|------|----------|
| **INNER JOIN** | 两边都匹配的记录 | 必须有匹配才有意义 |
| **LEFT JOIN** | 保留左表所有记录 | 左表是主体，右表是补充属性 |
| **RIGHT JOIN** | 保留右表所有记录 | 少用，用 LEFT JOIN 代替 |
| **FULL OUTER JOIN** | 保留两边所有记录 | 查找两边差异 |
| **CROSS JOIN** | 笛卡尔积 | 生成组合（慎用） |

---

## Join 验证清单

在写 join 前：

```sql
-- ============================================================
-- Join 验证模板
-- ============================================================

-- 1. 左表键分布
SELECT 
  'Left table' AS side,
  COUNT(*) AS total_rows,
  COUNT(DISTINCT join_key) AS unique_keys,
  COUNT(*) - COUNT(DISTINCT join_key) AS duplicate_keys
FROM left_table;

-- 2. 右表键分布
SELECT 
  'Right table' AS side,
  COUNT(*) AS total_rows,
  COUNT(DISTINCT join_key) AS unique_keys,
  COUNT(*) - COUNT(DISTINCT join_key) AS duplicate_keys
FROM right_table;

-- 3. 键覆盖率（多少左表键能在右表找到）
SELECT 
  COUNT(DISTINCT l.join_key) AS left_unique_keys,
  COUNT(DISTINCT r.join_key) AS right_unique_keys,
  COUNT(DISTINCT CASE WHEN r.join_key IS NOT NULL THEN l.join_key END) AS matched_keys,
  COUNT(DISTINCT CASE WHEN r.join_key IS NULL THEN l.join_key END) AS unmatched_keys,
  ROUND(100.0 * COUNT(DISTINCT CASE WHEN r.join_key IS NOT NULL THEN l.join_key END) 
    / COUNT(DISTINCT l.join_key), 2) AS match_rate_pct
FROM left_table l
LEFT JOIN right_table r ON l.join_key = r.join_key;

-- 4. 预测 join 后行数
WITH left_counts AS (
  SELECT join_key, COUNT(*) AS left_n
  FROM left_table
  GROUP BY join_key
),
right_counts AS (
  SELECT join_key, COUNT(*) AS right_n
  FROM right_table
  GROUP BY join_key
)
SELECT 
  SUM(COALESCE(l.left_n, 0) * COALESCE(r.right_n, 0)) AS predicted_rows,
  (SELECT COUNT(*) FROM left_table) AS left_rows,
  (SELECT COUNT(*) FROM right_table) AS right_rows
FROM left_counts l
FULL OUTER JOIN right_counts r ON l.join_key = r.join_key;
```

---

## 常见 Join 模式

### 模式 1: 维度扩展（1:1）

**场景**: 给事实表添加维度属性

```sql
-- 验证右表键唯一
SELECT product_id, COUNT(*) 
FROM products 
GROUP BY product_id 
HAVING COUNT(*) > 1;
-- 预期: 0 行

-- 安全 join
SELECT 
  o.order_id,
  o.amount,
  p.product_name,
  p.category
FROM orders o
LEFT JOIN products p ON o.product_id = p.product_id;

-- 验证行数不变
-- join 前: COUNT(*) FROM orders
-- join 后: COUNT(*) FROM orders LEFT JOIN products
-- 应该相等
```

### 模式 2: 聚合后 Join（N:1）

**场景**: 将汇总指标关联到主表

```sql
-- 错误：直接 join 会导致行爆炸
-- SELECT u.*, o.amount FROM users u JOIN orders o ON u.user_id = o.user_id

-- 正确：先聚合再 join
WITH user_stats AS (
  SELECT 
    user_id,
    COUNT(*) AS order_count,
    SUM(amount) AS total_spent,
    MAX(order_date) AS last_order_date
  FROM orders
  GROUP BY user_id
)
SELECT 
  u.user_id,
  u.email,
  COALESCE(s.order_count, 0) AS order_count,
  COALESCE(s.total_spent, 0) AS total_spent
FROM users u
LEFT JOIN user_stats s ON u.user_id = s.user_id;

-- 验证
-- user 数应该 = users 表行数
```

### 模式 3: 多对多扩展（N:M）

**场景**: 两个有重复键的表 join

```sql
-- 场景：订单-产品（一个订单多个产品，一个产品多个订单）
SELECT 
  o.order_id,
  o.order_date,
  oi.product_id,
  oi.quantity,
  p.product_name
FROM orders o
JOIN order_items oi ON o.order_id = oi.order_id
JOIN products p ON oi.product_id = p.product_id;

-- 验证行数
-- 应该 = order_items 表行数（如果 products 键唯一）
```

**陷阱**: 意外的 N:M

```sql
-- 检查是否有意外的多对多
WITH left_dups AS (
  SELECT join_key FROM left_table GROUP BY join_key HAVING COUNT(*) > 1
),
right_dups AS (
  SELECT join_key FROM right_table GROUP BY join_key HAVING COUNT(*) > 1
)
SELECT 
  l.join_key,
  'Both sides have duplicates - N:M join!' AS warning
FROM left_dups l
JOIN right_dups r ON l.join_key = r.join_key;
-- 预期: 0 行（如果不想要 N:M）
```

### 模式 4: 时间范围 Join

**场景**: 根据时间窗口匹配记录

```sql
-- 用户和他们活跃期间的促销
SELECT 
  u.user_id,
  u.signup_date,
  p.promo_code,
  p.start_date,
  p.end_date
FROM users u
JOIN promotions p 
  ON u.signup_date BETWEEN p.start_date AND p.end_date;

-- 警告: 可能产生多行（一个用户在多个促销期）
-- 验证
SELECT user_id, COUNT(*) 
FROM (上面的查询)
GROUP BY user_id
HAVING COUNT(*) > 1;
```

### 模式 5: Self Join（自连接）

**场景**: 在同一表内查找关系

```sql
-- 查找推荐链：用户 A 推荐了谁
SELECT 
  u1.user_id AS referrer_id,
  u1.email AS referrer_email,
  u2.user_id AS referred_id,
  u2.email AS referred_email,
  u2.signup_date
FROM users u1
JOIN users u2 ON u1.user_id = u2.referred_by
WHERE u1.user_id = 12345;
```

---

## Join 后验证查询

```sql
-- ============================================================
-- Join 后验证
-- ============================================================

-- 1. 行数变化
WITH before AS (
  SELECT COUNT(*) AS n FROM left_table
),
after AS (
  SELECT COUNT(*) AS n 
  FROM left_table l 
  JOIN right_table r ON l.join_key = r.join_key
)
SELECT 
  b.n AS before_rows,
  a.n AS after_rows,
  a.n - b.n AS row_change,
  ROUND(100.0 * (a.n - b.n) / b.n, 2) AS pct_change
FROM before b, after a;

-- 2. 丢失的记录（LEFT JOIN 中未匹配的）
SELECT 
  l.join_key,
  l.*
FROM left_table l
LEFT JOIN right_table r ON l.join_key = r.join_key
WHERE r.join_key IS NULL
LIMIT 10;

-- 3. 重复扩展检测
SELECT 
  l.primary_key,
  COUNT(*) AS occurrences
FROM left_table l
JOIN right_table r ON l.join_key = r.join_key
GROUP BY l.primary_key
HAVING COUNT(*) > 1
LIMIT 10;

-- 4. 空值注入检查
SELECT 
  COUNT(*) AS total_rows,
  COUNT(r.some_column) AS non_null_right_column,
  COUNT(*) - COUNT(r.some_column) AS nulls_from_join
FROM left_table l
LEFT JOIN right_table r ON l.join_key = r.join_key;
```

---

## 多表 Join 策略

### 链式 Join

```sql
-- 按依赖顺序 join
SELECT 
  o.order_id,
  u.email,
  p.product_name,
  s.status_name
FROM orders o
JOIN users u ON o.user_id = u.user_id          -- 1:1
JOIN products p ON o.product_id = p.product_id  -- 1:1
JOIN order_status s ON o.status_id = s.status_id; -- 1:1
```

### 先聚合再 Join（推荐）

```sql
-- 错误：巨大的中间结果
SELECT 
  u.user_id,
  COUNT(o.order_id) AS orders,
  COUNT(r.review_id) AS reviews
FROM users u
LEFT JOIN orders o ON u.user_id = o.user_id
LEFT JOIN reviews r ON u.user_id = r.user_id
GROUP BY u.user_id;
-- 问题: orders * reviews 笛卡尔积

-- 正确：分别聚合
WITH order_counts AS (
  SELECT user_id, COUNT(*) AS order_count
  FROM orders
  GROUP BY user_id
),
review_counts AS (
  SELECT user_id, COUNT(*) AS review_count
  FROM reviews
  GROUP BY user_id
)
SELECT 
  u.user_id,
  COALESCE(o.order_count, 0) AS orders,
  COALESCE(r.review_count, 0) AS reviews
FROM users u
LEFT JOIN order_counts o ON u.user_id = o.user_id
LEFT JOIN review_counts r ON u.user_id = r.user_id;
```

---

## 性能优化

### 索引建议

```sql
-- Join 键应该有索引
CREATE INDEX idx_orders_user_id ON orders(user_id);
CREATE INDEX idx_orders_product_id ON orders(product_id);
```

### 小表驱动大表

```sql
-- 好：小表在前
SELECT *
FROM small_table s
JOIN large_table l ON s.key = l.key;

-- 避免：大表在前（除非必要）
```

### 减少 Join 前的数据量

```sql
-- 好：先过滤再 join
SELECT 
  o.order_id,
  u.email
FROM (
  SELECT * FROM orders WHERE order_date >= '2024-01-01'
) o
JOIN users u ON o.user_id = u.user_id;

-- 差：join 后再过滤
SELECT 
  o.order_id,
  u.email
FROM orders o
JOIN users u ON o.user_id = u.user_id
WHERE o.order_date >= '2024-01-01';
-- 虽然结果相同，但第一种更高效
```

---

## Join 调试清单

Join 结果不符合预期时：

- [ ] 检查两边的键类型是否一致（INT vs STRING）
- [ ] 检查空格/大小写问题（'ABC' vs 'abc' vs ' ABC'）
- [ ] 检查空值（NULL 不匹配任何值，包括 NULL）
- [ ] 检查时区（timestamp with timezone）
- [ ] 打印样本键值对比
- [ ] 验证行数变化是否符合预期
- [ ] 检查是否有隐藏的笛卡尔积

---

## 快速诊断模板

```sql
-- 保存为 scripts/debug_join.sql

-- 左表样本键
SELECT DISTINCT join_key FROM left_table LIMIT 5;

-- 右表样本键
SELECT DISTINCT join_key FROM right_table LIMIT 5;

-- 键的数据类型
SELECT 
  typeof(join_key) AS left_type 
FROM left_table LIMIT 1;

SELECT 
  typeof(join_key) AS right_type 
FROM right_table LIMIT 1;

-- 找一个应该匹配但没匹配的键
SELECT l.join_key AS left_key
FROM left_table l
WHERE l.join_key NOT IN (SELECT join_key FROM right_table)
LIMIT 1;
```
