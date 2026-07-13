# Python 数据分析模式

常见分析方法的 pandas/polars 实现。

---

## 1. 对比分析（Comparison Analysis）

### 同比分析（Year-over-Year）

```python
import pandas as pd

# 准备数据
df = pd.read_csv('orders.csv', parse_dates=['order_date'])

# 按年月聚合
monthly = df.groupby([
    df['order_date'].dt.year.rename('year'),
    df['order_date'].dt.month.rename('month')
]).agg({
    'amount': 'sum',
    'order_id': 'count'
}).rename(columns={'amount': 'revenue', 'order_id': 'orders'})

# 计算同比变化
yoy = monthly.reset_index()
yoy['prev_year_revenue'] = yoy.groupby('month')['revenue'].shift(12)
yoy['yoy_change'] = yoy['revenue'] - yoy['prev_year_revenue']
yoy['yoy_pct'] = 100 * yoy['yoy_change'] / yoy['prev_year_revenue']

print(yoy[yoy['year'] == 2024])
```

### 环比分析（Period-over-Period）

```python
# 月度环比
monthly = df.set_index('order_date').resample('ME').agg({
    'amount': 'sum',
    'user_id': 'nunique'
}).rename(columns={'amount': 'revenue', 'user_id': 'active_users'})

monthly['prev_month_revenue'] = monthly['revenue'].shift(1)
monthly['mom_change'] = monthly['revenue'] - monthly['prev_month_revenue']
monthly['mom_pct'] = 100 * monthly['mom_change'] / monthly['prev_month_revenue']

# 可视化
import plotly.express as px

fig = px.line(monthly.reset_index(), 
              x='order_date', 
              y=['revenue', 'prev_month_revenue'],
              title='Revenue MoM Comparison')
fig.show()
```

### 群组对比（Group Comparison）

```python
# 对比不同用户群体
segment_stats = df.groupby('user_segment').agg({
    'user_id': 'nunique',
    'order_id': 'count',
    'amount': ['sum', 'mean', 'median']
}).round(2)

segment_stats.columns = ['users', 'orders', 'total_revenue', 'avg_order', 'median_order']
segment_stats['orders_per_user'] = (segment_stats['orders'] / segment_stats['users']).round(2)

print(segment_stats.sort_values('avg_order', ascending=False))
```

---

## 2. 拆分分析（Breakdown Analysis）

### 多维度拆分

```python
# 按多维度拆分
breakdown = df.groupby(['category', 'channel', 'region'])['amount'].agg([
    ('revenue', 'sum'),
    ('orders', 'count')
]).reset_index()

# 计算占比
breakdown['pct_of_total'] = 100 * breakdown['revenue'] / breakdown['revenue'].sum()

# 显示 Top 10
print(breakdown.nlargest(10, 'revenue'))
```

### 帕累托分析（80/20）

```python
# 识别贡献 80% 收入的客户
customer_revenue = df.groupby('customer_id')['amount'].sum().sort_values(ascending=False)

cumsum = customer_revenue.cumsum()
cum_pct = 100 * cumsum / customer_revenue.sum()

# 找到 80% 阈值
top_80_customers = customer_revenue[cum_pct <= 80]

print(f"Top {len(top_80_customers)} customers ({100*len(top_80_customers)/len(customer_revenue):.1f}%) "
      f"contribute 80% of revenue")

# 可视化
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(10, 6))
ax.plot(range(len(cum_pct)), cum_pct.values)
ax.axhline(80, color='r', linestyle='--', label='80% threshold')
ax.axvline(len(top_80_customers), color='r', linestyle='--')
ax.set_xlabel('Number of Customers (sorted by revenue)')
ax.set_ylabel('Cumulative Revenue %')
ax.set_title('Pareto Analysis: Customer Revenue Distribution')
ax.legend()
plt.show()
```

### 时间序列拆分

```python
# 按小时和星期拆分
df['hour'] = df['created_at'].dt.hour
df['day_of_week'] = df['created_at'].dt.day_name()

heatmap_data = df.groupby(['day_of_week', 'hour']).size().unstack(fill_value=0)

# 按星期顺序排序
day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
heatmap_data = heatmap_data.reindex(day_order)

# 热力图
import seaborn as sns

plt.figure(figsize=(12, 6))
sns.heatmap(heatmap_data, cmap='YlOrRd', annot=True, fmt='g')
plt.title('Activity Heatmap by Hour and Day of Week')
plt.show()
```

---

## 3. 下钻分析（Drill-Down Analysis）

### 层级下钻

```python
# 总体 → 类别 → 子类别
def drill_down(df, levels=['category', 'subcategory']):
    results = []
    
    # Level 0: 总体
    total = pd.DataFrame([{
        'level': 'Total',
        'category': None,
        'subcategory': None,
        'revenue': df['amount'].sum(),
        'orders': len(df)
    }])
    results.append(total)
    
    # Level 1: 类别
    cat = df.groupby('category').agg({
        'amount': 'sum',
        'order_id': 'count'
    }).reset_index()
    cat['level'] = 'Category'
    cat['subcategory'] = None
    cat.columns = ['category', 'revenue', 'orders', 'level', 'subcategory']
    results.append(cat[['level', 'category', 'subcategory', 'revenue', 'orders']])
    
    # Level 2: 子类别
    subcat = df.groupby(['category', 'subcategory']).agg({
        'amount': 'sum',
        'order_id': 'count'
    }).reset_index()
    subcat['level'] = 'Subcategory'
    subcat.columns = ['category', 'subcategory', 'revenue', 'orders', 'level']
    results.append(subcat[['level', 'category', 'subcategory', 'revenue', 'orders']])
    
    return pd.concat(results, ignore_index=True)

hierarchy = drill_down(df)
print(hierarchy)
```

### 条件下钻（异常检测 → 根因）

```python
# 1. 识别异常日期
daily = df.groupby(df['order_date'].dt.date)['order_id'].count()
daily_mean = daily.rolling(7).mean().shift(1)

anomalies = daily[(daily - daily_mean).abs() > 100]

# 2. 下钻到异常日期的渠道
for date in anomalies.index:
    print(f"\n异常日期: {date} (订单: {anomalies[date]:.0f}, 预期: {daily_mean[date]:.0f})")
    
    day_data = df[df['order_date'].dt.date == date]
    by_channel = day_data.groupby('channel').size().sort_values(ascending=False)
    
    print("按渠道分布:")
    print(by_channel)
```

---

## 4. 趋势分析（Trend Analysis）

### 移动平均

```python
# 计算移动平均平滑趋势
daily = df.groupby(df['order_date'].dt.date)['amount'].sum()

daily_df = pd.DataFrame({
    'date': daily.index,
    'revenue': daily.values
})

daily_df['ma_7d'] = daily_df['revenue'].rolling(7, min_periods=1).mean()
daily_df['ma_30d'] = daily_df['revenue'].rolling(30, min_periods=1).mean()

# 可视化
fig = px.line(daily_df, x='date', y=['revenue', 'ma_7d', 'ma_30d'],
              title='Daily Revenue with Moving Averages')
fig.show()
```

### 增长率计算

```python
# 月度增长率
monthly = df.set_index('order_date').resample('ME')['amount'].sum()

growth = pd.DataFrame({
    'month': monthly.index,
    'revenue': monthly.values
})

# 环比增长
growth['mom_growth'] = growth['revenue'].pct_change() * 100

# 相对基准增长
growth['growth_from_baseline'] = (
    (growth['revenue'] - growth['revenue'].iloc[0]) / growth['revenue'].iloc[0] * 100
)

# CAGR (复合年增长率)
months = len(growth)
if months > 1:
    cagr = ((growth['revenue'].iloc[-1] / growth['revenue'].iloc[0]) ** (12 / months) - 1) * 100
    print(f"CAGR: {cagr:.2f}%")
```

---

## 5. 漏斗分析（Funnel Analysis）

### 标准漏斗

```python
# 用户行为漏斗
events = pd.read_csv('events.csv', parse_dates=['timestamp'])

funnel = events.groupby('user_id')['event_type'].apply(
    lambda x: pd.Series({
        'viewed': ('page_view' in x.values),
        'added_to_cart': ('add_to_cart' in x.values),
        'checked_out': ('checkout' in x.values),
        'purchased': ('purchase' in x.values)
    })
).reset_index()

# 计算转化率
funnel_stats = pd.DataFrame({
    'step': ['Viewed', 'Added to Cart', 'Checked Out', 'Purchased'],
    'users': [
        funnel['viewed'].sum(),
        funnel['added_to_cart'].sum(),
        funnel['checked_out'].sum(),
        funnel['purchased'].sum()
    ]
})

funnel_stats['conversion_rate'] = (
    100 * funnel_stats['users'] / funnel_stats['users'].iloc[0]
)

funnel_stats['step_conversion'] = (
    100 * funnel_stats['users'] / funnel_stats['users'].shift(1)
)

print(funnel_stats)

# 漏斗可视化
fig = px.funnel(funnel_stats, x='users', y='step', title='Conversion Funnel')
fig.show()
```

### 时间窗口漏斗

```python
# 24小时内完成购买的用户
from datetime import timedelta

user_events = events.sort_values('timestamp').groupby('user_id')

def check_funnel(group):
    first_view = group[group['event_type'] == 'page_view']['timestamp'].min()
    purchase = group[group['event_type'] == 'purchase']['timestamp'].min()
    
    if pd.notna(first_view) and pd.notna(purchase):
        time_to_purchase = (purchase - first_view).total_seconds() / 3600  # hours
        return time_to_purchase <= 24
    return False

converted_24h = user_events.apply(check_funnel).sum()
total_viewers = events[events['event_type'] == 'page_view']['user_id'].nunique()

print(f"24-hour conversion rate: {100*converted_24h/total_viewers:.2f}%")
```

---

## 6. 同期群分析（Cohort Analysis）

### 留存分析

```python
# 按注册月份分组的留存
df['signup_month'] = df.groupby('user_id')['order_date'].transform('min').dt.to_period('M')
df['order_month'] = df['order_date'].dt.to_period('M')
df['months_since_signup'] = (df['order_month'] - df['signup_month']).apply(lambda x: x.n)

# 构建留存矩阵
cohort_data = df.groupby(['signup_month', 'months_since_signup'])['user_id'].nunique().reset_index()
cohort_pivot = cohort_data.pivot(index='signup_month', 
                                   columns='months_since_signup', 
                                   values='user_id')

# 计算留存率
cohort_size = cohort_pivot.iloc[:, 0]
retention = cohort_pivot.divide(cohort_size, axis=0) * 100

print(retention.round(1))

# 热力图
plt.figure(figsize=(12, 8))
sns.heatmap(retention, annot=True, fmt='.0f', cmap='RdYlGn', vmin=0, vmax=100)
plt.title('User Retention by Cohort (%)')
plt.xlabel('Months Since Signup')
plt.ylabel('Signup Month')
plt.show()
```

---

## 7. RFM 分析（Recency, Frequency, Monetary）

```python
from datetime import datetime

# 计算 RFM 指标
analysis_date = df['order_date'].max() + timedelta(days=1)

rfm = df.groupby('customer_id').agg({
    'order_date': lambda x: (analysis_date - x.max()).days,  # Recency
    'order_id': 'count',  # Frequency
    'amount': 'sum'  # Monetary
}).rename(columns={
    'order_date': 'recency',
    'order_id': 'frequency',
    'amount': 'monetary'
})

# RFM 分值（四分位数）
rfm['r_score'] = pd.qcut(rfm['recency'], 4, labels=[4, 3, 2, 1])  # 越近越好
rfm['f_score'] = pd.qcut(rfm['frequency'].rank(method='first'), 4, labels=[1, 2, 3, 4])
rfm['m_score'] = pd.qcut(rfm['monetary'], 4, labels=[1, 2, 3, 4])

# RFM 总分
rfm['rfm_score'] = rfm['r_score'].astype(int) + rfm['f_score'].astype(int) + rfm['m_score'].astype(int)

# 客户分类
def segment_customer(row):
    if row['rfm_score'] >= 10:
        return 'Champions'
    elif row['rfm_score'] >= 8:
        return 'Loyal'
    elif row['r_score'] >= 3 and row['f_score'] >= 3:
        return 'Potential Loyalist'
    elif row['r_score'] >= 3:
        return 'New Customers'
    elif row['f_score'] <= 2:
        return 'At Risk'
    else:
        return 'Need Attention'

rfm['segment'] = rfm.apply(segment_customer, axis=1)

print(rfm['segment'].value_counts())
print(rfm.groupby('segment')[['recency', 'frequency', 'monetary']].mean())
```

---

## 8. 异常检测（Anomaly Detection）

### 基于统计的异常检测

```python
# Z-score 方法
from scipy import stats

daily = df.groupby(df['order_date'].dt.date)['amount'].sum()

daily_df = pd.DataFrame({
    'date': daily.index,
    'revenue': daily.values
})

# 计算 Z-score
daily_df['z_score'] = stats.zscore(daily_df['revenue'])
daily_df['is_anomaly'] = daily_df['z_score'].abs() > 3

anomalies = daily_df[daily_df['is_anomaly']]
print(f"发现 {len(anomalies)} 个异常日期:")
print(anomalies)

# 可视化
fig = px.scatter(daily_df, x='date', y='revenue', 
                 color='is_anomaly',
                 title='Revenue Anomaly Detection')
fig.show()
```

### 基于移动平均的异常检测

```python
daily_df['ma_7d'] = daily_df['revenue'].rolling(7, min_periods=1).mean()
daily_df['std_7d'] = daily_df['revenue'].rolling(7, min_periods=1).std()

# 超出 2 个标准差视为异常
daily_df['upper_bound'] = daily_df['ma_7d'] + 2 * daily_df['std_7d']
daily_df['lower_bound'] = daily_df['ma_7d'] - 2 * daily_df['std_7d']

daily_df['is_anomaly'] = (
    (daily_df['revenue'] > daily_df['upper_bound']) |
    (daily_df['revenue'] < daily_df['lower_bound'])
)

print(daily_df[daily_df['is_anomaly']])
```

---

## 使用 Polars（高性能替代）

```python
import polars as pl

# 读取数据
df = pl.read_csv('orders.csv').with_columns(
    pl.col('order_date').str.strptime(pl.Date, '%Y-%m-%d')
)

# 同比分析（Polars 语法）
monthly = df.group_by([
    pl.col('order_date').dt.year().alias('year'),
    pl.col('order_date').dt.month().alias('month')
]).agg([
    pl.col('amount').sum().alias('revenue'),
    pl.col('order_id').count().alias('orders')
])

# 窗口函数计算同比
yoy = monthly.with_columns([
    pl.col('revenue').shift(12).over('month').alias('prev_year_revenue')
]).with_columns([
    (pl.col('revenue') - pl.col('prev_year_revenue')).alias('yoy_change'),
    (100 * (pl.col('revenue') - pl.col('prev_year_revenue')) / pl.col('prev_year_revenue')).alias('yoy_pct')
])

print(yoy.filter(pl.col('year') == 2024))
```

---

## 完成标准模板

分析结果应包含：

```python
# 在 notebook 末尾
print("=" * 60)
print("分析摘要")
print("=" * 60)
print(f"数据源: orders.csv")
print(f"时间范围: {df['order_date'].min()} 至 {df['order_date'].max()}")
print(f"总行数: {len(df):,}")
print(f"分析方法: 同期群留存分析")
print(f"\n关键发现:")
print("- 2024-01 群组 6个月留存率: 45%")
print("- 高于平均留存率 12 个百分点")
print(f"\n数据质量:")
print(f"- 空值: user_id {df['user_id'].isna().sum()} 个")
print(f"- 重复: {df.duplicated().sum()} 行")
print(f"\n假设:")
print("- 用户首次订单日期 = 注册日期")
print("- 仅统计完成订单（status='completed'）")
```
