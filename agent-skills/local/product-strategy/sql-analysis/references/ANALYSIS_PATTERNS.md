# 常见分析方法

SQL 数据分析的标准模式和可复用查询模板。

---

## 1. 对比分析（Comparison Analysis）

比较不同维度、时期或群组的指标差异。

### 同比分析（Year-over-Year）

```sql
WITH this_year AS (
  SELECT 
    DATE_TRUNC('month', order_date) AS month,
    SUM(amount) AS revenue
  FROM orders
  WHERE YEAR(order_date) = 2024
  GROUP BY 1
),
last_year AS (
  SELECT 
    DATE_TRUNC('month', order_date) AS month,
    SUM(amount) AS revenue
  FROM orders
  WHERE YEAR(order_date) = 2023
  GROUP BY 1
)
SELECT 
  ty.month,
  ty.revenue AS revenue_2024,
  ly.revenue AS revenue_2023,
  ty.revenue - ly.revenue AS abs_change,
  ROUND(100.0 * (ty.revenue - ly.revenue) / NULLIF(ly.revenue, 0), 2) AS pct_change
FROM this_year ty
LEFT JOIN last_year ly 
  ON DATE_PART('month', ty.month) = DATE_PART('month', ly.month)
ORDER BY ty.month;
```

### 环比分析（Period-over-Period）

```sql
WITH monthly_metrics AS (
  SELECT 
    DATE_TRUNC('month', order_date) AS month,
    SUM(amount) AS revenue,
    COUNT(DISTINCT user_id) AS active_users
  FROM orders
  GROUP BY 1
)
SELECT 
  month,
  revenue,
  active_users,
  LAG(revenue) OVER (ORDER BY month) AS prev_month_revenue,
  revenue - LAG(revenue) OVER (ORDER BY month) AS revenue_change,
  ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY month)) 
    / NULLIF(LAG(revenue) OVER (ORDER BY month), 0), 2) AS revenue_pct_change
FROM monthly_metrics
ORDER BY month DESC;
```

### 群组对比（Group Comparison）

```sql
-- 对比不同用户群体的行为
SELECT 
  user_segment,
  COUNT(DISTINCT user_id) AS users,
  AVG(order_count) AS avg_orders_per_user,
  AVG(total_spent) AS avg_spent_per_user,
  MEDIAN(total_spent) AS median_spent_per_user
FROM (
  SELECT 
    u.user_id,
    u.segment AS user_segment,
    COUNT(o.order_id) AS order_count,
    SUM(o.amount) AS total_spent
  FROM users u
  LEFT JOIN orders o ON u.user_id = o.user_id
  WHERE o.order_date >= '2024-01-01'
  GROUP BY 1, 2
)
GROUP BY user_segment
ORDER BY avg_spent_per_user DESC;
```

---

## 2. 拆分分析（Breakdown Analysis）

将总体指标拆分到不同维度，识别结构和贡献。

### 维度拆分（Dimensional Breakdown）

```sql
-- 按多维度拆分收入
SELECT 
  product_category,
  channel,
  region,
  SUM(amount) AS revenue,
  COUNT(DISTINCT order_id) AS orders,
  ROUND(100.0 * SUM(amount) / SUM(SUM(amount)) OVER (), 2) AS pct_of_total
FROM orders
WHERE order_date >= '2024-01-01'
GROUP BY 1, 2, 3
ORDER BY revenue DESC;
```

### 帕累托分析（80/20 分析）

```sql
-- 识别贡献 80% 收入的客户
WITH customer_revenue AS (
  SELECT 
    customer_id,
    SUM(amount) AS total_revenue
  FROM orders
  WHERE order_date >= '2024-01-01'
  GROUP BY 1
),
ranked AS (
  SELECT 
    customer_id,
    total_revenue,
    SUM(total_revenue) OVER (ORDER BY total_revenue DESC) AS running_total,
    SUM(total_revenue) OVER () AS grand_total
  FROM customer_revenue
)
SELECT 
  customer_id,
  total_revenue,
  running_total,
  ROUND(100.0 * running_total / grand_total, 2) AS cumulative_pct
FROM ranked
WHERE cumulative_pct <= 80
ORDER BY total_revenue DESC;
```

### 时间序列拆分（Temporal Breakdown）

```sql
-- 按小时拆分查看使用模式
SELECT 
  DATE_PART('hour', created_at) AS hour_of_day,
  DATE_PART('dow', created_at) AS day_of_week, -- 0=Sunday
  COUNT(*) AS event_count,
  COUNT(DISTINCT user_id) AS unique_users
FROM events
WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY 1, 2
ORDER BY 2, 1;
```

---

## 3. 下钻分析（Drill-Down Analysis）

从汇总层级逐步深入到细节层级。

### 层级下钻模板

```sql
-- Level 1: 总体
SELECT 
  'Total' AS level,
  NULL AS category,
  NULL AS subcategory,
  SUM(amount) AS revenue,
  COUNT(DISTINCT order_id) AS orders
FROM orders
WHERE order_date >= '2024-01-01'

UNION ALL

-- Level 2: 按类别
SELECT 
  'Category' AS level,
  category,
  NULL AS subcategory,
  SUM(amount) AS revenue,
  COUNT(DISTINCT order_id) AS orders
FROM orders
WHERE order_date >= '2024-01-01'
GROUP BY 2

UNION ALL

-- Level 3: 按子类别
SELECT 
  'Subcategory' AS level,
  category,
  subcategory,
  SUM(amount) AS revenue,
  COUNT(DISTINCT order_id) AS orders
FROM orders
WHERE order_date >= '2024-01-01'
GROUP BY 2, 3

ORDER BY level, revenue DESC;
```

### 条件下钻（Conditional Drill-Down）

```sql
-- 从异常指标下钻到根因
WITH daily_orders AS (
  SELECT 
    DATE(order_date) AS date,
    COUNT(*) AS order_count
  FROM orders
  GROUP BY 1
),
anomalies AS (
  SELECT 
    date,
    order_count,
    AVG(order_count) OVER (ORDER BY date ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING) AS avg_prev_7d
  FROM daily_orders
)
SELECT 
  a.date,
  a.order_count,
  a.avg_prev_7d,
  a.order_count - a.avg_prev_7d AS deviation,
  -- 下钻到渠道
  o.channel,
  COUNT(*) AS orders_by_channel
FROM anomalies a
JOIN orders o ON DATE(o.order_date) = a.date
WHERE ABS(a.order_count - a.avg_prev_7d) > 100  -- 异常阈值
GROUP BY 1, 2, 3, 4, 5
ORDER BY 1 DESC, 6 DESC;
```

---

## 4. 趋势分析（Trend Analysis）

识别指标随时间的变化模式。

### 移动平均（Moving Average）

```sql
SELECT 
  DATE(order_date) AS date,
  COUNT(*) AS daily_orders,
  AVG(COUNT(*)) OVER (
    ORDER BY DATE(order_date)
    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
  ) AS ma_7d,
  AVG(COUNT(*)) OVER (
    ORDER BY DATE(order_date)
    ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
  ) AS ma_30d
FROM orders
WHERE order_date >= CURRENT_DATE - INTERVAL '90 days'
GROUP BY 1
ORDER BY 1;
```

### 增长率（Growth Rate）

```sql
WITH monthly_metrics AS (
  SELECT 
    DATE_TRUNC('month', order_date) AS month,
    SUM(amount) AS revenue
  FROM orders
  GROUP BY 1
)
SELECT 
  month,
  revenue,
  FIRST_VALUE(revenue) OVER (ORDER BY month) AS baseline_revenue,
  ROUND(100.0 * (revenue - FIRST_VALUE(revenue) OVER (ORDER BY month)) 
    / FIRST_VALUE(revenue) OVER (ORDER BY month), 2) AS growth_since_baseline_pct,
  -- 月度增长率
  ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY month)) 
    / NULLIF(LAG(revenue) OVER (ORDER BY month), 0), 2) AS mom_growth_pct
FROM monthly_metrics
ORDER BY month;
```

---

## 5. 漏斗分析（Funnel Analysis）

分析用户在多步骤流程中的转化。

### 标准漏斗

```sql
WITH funnel_steps AS (
  SELECT 
    user_id,
    MAX(CASE WHEN event_type = 'page_view' THEN 1 ELSE 0 END) AS step_1_view,
    MAX(CASE WHEN event_type = 'add_to_cart' THEN 1 ELSE 0 END) AS step_2_cart,
    MAX(CASE WHEN event_type = 'checkout' THEN 1 ELSE 0 END) AS step_3_checkout,
    MAX(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS step_4_purchase
  FROM events
  WHERE created_at >= '2024-01-01'
  GROUP BY 1
)
SELECT 
  SUM(step_1_view) AS users_viewed,
  SUM(step_2_cart) AS users_added_cart,
  SUM(step_3_checkout) AS users_checkout,
  SUM(step_4_purchase) AS users_purchased,
  -- 转化率
  ROUND(100.0 * SUM(step_2_cart) / NULLIF(SUM(step_1_view), 0), 2) AS cvr_view_to_cart,
  ROUND(100.0 * SUM(step_3_checkout) / NULLIF(SUM(step_2_cart), 0), 2) AS cvr_cart_to_checkout,
  ROUND(100.0 * SUM(step_4_purchase) / NULLIF(SUM(step_3_checkout), 0), 2) AS cvr_checkout_to_purchase,
  ROUND(100.0 * SUM(step_4_purchase) / NULLIF(SUM(step_1_view), 0), 2) AS overall_cvr
FROM funnel_steps;
```

### 时间窗口漏斗

```sql
-- 计算 7 天转化漏斗
WITH first_view AS (
  SELECT 
    user_id,
    MIN(created_at) AS first_view_at
  FROM events
  WHERE event_type = 'page_view'
  GROUP BY 1
),
subsequent_events AS (
  SELECT 
    fv.user_id,
    fv.first_view_at,
    MAX(CASE WHEN e.event_type = 'purchase' 
      AND e.created_at BETWEEN fv.first_view_at AND fv.first_view_at + INTERVAL '7 days'
      THEN 1 ELSE 0 END) AS purchased_within_7d
  FROM first_view fv
  LEFT JOIN events e ON fv.user_id = e.user_id
  GROUP BY 1, 2
)
SELECT 
  DATE_TRUNC('week', first_view_at) AS cohort_week,
  COUNT(*) AS users_viewed,
  SUM(purchased_within_7d) AS users_purchased,
  ROUND(100.0 * SUM(purchased_within_7d) / COUNT(*), 2) AS cvr_7d_pct
FROM subsequent_events
GROUP BY 1
ORDER BY 1 DESC;
```

---

## 6. 队列分析（Cohort Analysis）

按初始行为时间分组用户，追踪长期行为。

### 留存队列

```sql
WITH first_order AS (
  SELECT 
    user_id,
    DATE_TRUNC('month', MIN(order_date)) AS cohort_month
  FROM orders
  GROUP BY 1
),
orders_with_cohort AS (
  SELECT 
    fo.cohort_month,
    DATE_TRUNC('month', o.order_date) AS order_month,
    COUNT(DISTINCT o.user_id) AS active_users
  FROM first_order fo
  JOIN orders o ON fo.user_id = o.user_id
  GROUP BY 1, 2
),
cohort_size AS (
  SELECT 
    cohort_month,
    COUNT(*) AS cohort_size
  FROM first_order
  GROUP BY 1
)
SELECT 
  owc.cohort_month,
  owc.order_month,
  DATE_PART('month', AGE(owc.order_month, owc.cohort_month)) AS months_since_first,
  owc.active_users,
  cs.cohort_size,
  ROUND(100.0 * owc.active_users / cs.cohort_size, 2) AS retention_pct
FROM orders_with_cohort owc
JOIN cohort_size cs ON owc.cohort_month = cs.cohort_month
ORDER BY owc.cohort_month, owc.order_month;
```

---

## 7. 贡献分析（Attribution Analysis）

分解指标变化的驱动因素。

### 变化归因

```sql
-- 分解收入变化：数量效应 vs 价格效应
WITH this_period AS (
  SELECT 
    product_id,
    SUM(quantity) AS qty,
    AVG(unit_price) AS avg_price
  FROM orders
  WHERE order_date BETWEEN '2024-07-01' AND '2024-07-31'
  GROUP BY 1
),
last_period AS (
  SELECT 
    product_id,
    SUM(quantity) AS qty,
    AVG(unit_price) AS avg_price
  FROM orders
  WHERE order_date BETWEEN '2024-06-01' AND '2024-06-30'
  GROUP BY 1
)
SELECT 
  COALESCE(tp.product_id, lp.product_id) AS product_id,
  lp.qty * lp.avg_price AS revenue_last,
  tp.qty * tp.avg_price AS revenue_this,
  tp.qty * tp.avg_price - lp.qty * lp.avg_price AS revenue_change,
  -- 分解
  (tp.qty - lp.qty) * lp.avg_price AS quantity_effect,
  (tp.avg_price - lp.avg_price) * lp.qty AS price_effect,
  (tp.qty - lp.qty) * (tp.avg_price - lp.avg_price) AS mix_effect
FROM this_period tp
FULL OUTER JOIN last_period lp ON tp.product_id = lp.product_id
ORDER BY ABS(revenue_change) DESC;
```

---

## 8. 异常检测（Anomaly Detection）

识别偏离正常模式的数据点。

### Z-Score 方法

```sql
WITH daily_metrics AS (
  SELECT 
    DATE(order_date) AS date,
    COUNT(*) AS order_count
  FROM orders
  WHERE order_date >= CURRENT_DATE - INTERVAL '90 days'
  GROUP BY 1
),
stats AS (
  SELECT 
    AVG(order_count) AS mean,
    STDDEV(order_count) AS stddev
  FROM daily_metrics
)
SELECT 
  dm.date,
  dm.order_count,
  s.mean,
  s.stddev,
  (dm.order_count - s.mean) / NULLIF(s.stddev, 0) AS z_score,
  CASE 
    WHEN ABS((dm.order_count - s.mean) / NULLIF(s.stddev, 0)) > 3 THEN '异常'
    WHEN ABS((dm.order_count - s.mean) / NULLIF(s.stddev, 0)) > 2 THEN '可疑'
    ELSE '正常'
  END AS status
FROM daily_metrics dm
CROSS JOIN stats s
ORDER BY dm.date DESC;
```

---

## 使用建议

1. **选择合适方法**：根据分析目标选择模板
2. **验证假设**：检查时间范围、粒度、过滤条件
3. **测试小样本**：先用 LIMIT 验证查询逻辑
4. **记录业务逻辑**：在 CTE 中添加注释说明计算含义
5. **检查边界情况**：NULL 值、除零、日期范围等

## DuckDB 适配

以上查询在 DuckDB 中基本兼容，主要区别：
- `DATE_TRUNC` → DuckDB 支持
- `AGE()` → 使用 `INTERVAL` 运算
- `MEDIAN()` → DuckDB 内置支持
- CSV/Parquet 直接查询：`SELECT * FROM 'data.csv'`
