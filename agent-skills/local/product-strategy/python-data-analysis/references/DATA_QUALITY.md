# 数据质量检查

数据分析前的质量验证清单和模板。

---

## 快速质量检查

```python
import pandas as pd
import numpy as np

def quick_profile(df, name='DataFrame'):
    """快速数据质量报告"""
    
    print(f"{'='*60}")
    print(f"数据质量报告: {name}")
    print(f"{'='*60}\n")
    
    # 1. 基本信息
    print("1. 基本信息")
    print(f"   行数: {len(df):,}")
    print(f"   列数: {len(df.columns)}")
    print(f"   内存: {df.memory_usage(deep=True).sum() / 1024**2:.2f} MB\n")
    
    # 2. 数据类型
    print("2. 数据类型分布")
    print(df.dtypes.value_counts())
    print()
    
    # 3. 缺失值
    print("3. 缺失值分析")
    missing = df.isnull().sum()
    missing_pct = 100 * missing / len(df)
    missing_df = pd.DataFrame({
        'column': missing.index,
        'missing': missing.values,
        'pct': missing_pct.values
    })
    missing_df = missing_df[missing_df['missing'] > 0].sort_values('missing', ascending=False)
    
    if len(missing_df) > 0:
        print(missing_df.to_string(index=False))
    else:
        print("   ✓ 无缺失值")
    print()
    
    # 4. 重复行
    print("4. 重复行检查")
    dup_count = df.duplicated().sum()
    if dup_count > 0:
        print(f"   ⚠ 发现 {dup_count} 行重复 ({100*dup_count/len(df):.2f}%)")
    else:
        print("   ✓ 无重复行")
    print()
    
    # 5. 数值列统计
    print("5. 数值列统计")
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    if len(numeric_cols) > 0:
        print(df[numeric_cols].describe().round(2))
    else:
        print("   无数值列")
    print()
    
    # 6. 类别列基数
    print("6. 类别列唯一值")
    cat_cols = df.select_dtypes(include=['object', 'category']).columns
    for col in cat_cols[:10]:  # 最多显示 10 个
        n_unique = df[col].nunique()
        pct = 100 * n_unique / len(df)
        print(f"   {col}: {n_unique:,} 个唯一值 ({pct:.1f}%)")
    print()
    
    # 7. 样本数据
    print("7. 样本数据（前 3 行）")
    print(df.head(3))
    
    return missing_df

# 使用
df = pd.read_csv('data.csv')
quick_profile(df, 'orders')
```

---

## 详细质量检查清单

### 结构完整性

```python
def check_schema(df, expected_columns):
    """检查列是否符合预期"""
    actual = set(df.columns)
    expected = set(expected_columns)
    
    missing = expected - actual
    extra = actual - expected
    
    if missing:
        print(f"⚠ 缺少列: {missing}")
    if extra:
        print(f"⚠ 额外列: {extra}")
    if not missing and not extra:
        print("✓ Schema 正确")
    
    return len(missing) == 0 and len(extra) == 0

# 使用
expected = ['user_id', 'order_date', 'amount', 'status']
check_schema(df, expected)
```

### 数据类型验证

```python
def check_types(df, type_map):
    """验证列类型"""
    issues = []
    
    for col, expected_type in type_map.items():
        if col not in df.columns:
            issues.append(f"列 {col} 不存在")
            continue
            
        actual_type = df[col].dtype
        
        # 简化类型比较
        if expected_type == 'int' and not pd.api.types.is_integer_dtype(actual_type):
            issues.append(f"{col}: 预期 int, 实际 {actual_type}")
        elif expected_type == 'float' and not pd.api.types.is_float_dtype(actual_type):
            issues.append(f"{col}: 预期 float, 实际 {actual_type}")
        elif expected_type == 'str' and actual_type != 'object':
            issues.append(f"{col}: 预期 str, 实际 {actual_type}")
        elif expected_type == 'datetime' and not pd.api.types.is_datetime64_any_dtype(actual_type):
            issues.append(f"{col}: 预期 datetime, 实际 {actual_type}")
    
    if issues:
        print("⚠ 类型问题:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("✓ 所有类型正确")
    
    return len(issues) == 0

# 使用
type_map = {
    'user_id': 'int',
    'amount': 'float',
    'order_date': 'datetime',
    'status': 'str'
}
check_types(df, type_map)
```

### 业务规则验证

```python
def check_business_rules(df):
    """验证业务规则"""
    issues = []
    
    # 规则 1: amount 应该 > 0
    neg_amount = (df['amount'] <= 0).sum()
    if neg_amount > 0:
        issues.append(f"{neg_amount} 行 amount <= 0")
    
    # 规则 2: user_id 应该是正整数
    invalid_user = (df['user_id'] <= 0).sum()
    if invalid_user > 0:
        issues.append(f"{invalid_user} 行 user_id <= 0")
    
    # 规则 3: order_date 应该在合理范围
    if pd.api.types.is_datetime64_any_dtype(df['order_date']):
        too_old = (df['order_date'] < '2020-01-01').sum()
        future = (df['order_date'] > pd.Timestamp.now()).sum()
        if too_old > 0:
            issues.append(f"{too_old} 行日期早于 2020")
        if future > 0:
            issues.append(f"{future} 行日期在未来")
    
    # 规则 4: status 应该在枚举值中
    valid_statuses = {'pending', 'completed', 'cancelled'}
    invalid_status = ~df['status'].isin(valid_statuses)
    if invalid_status.sum() > 0:
        issues.append(f"{invalid_status.sum()} 行 status 无效")
    
    if issues:
        print("⚠ 业务规则违规:")
        for issue in issues:
            print(f"  - {issue}")
        return False
    else:
        print("✓ 所有业务规则通过")
        return True

check_business_rules(df)
```

### 异常值检测

```python
def detect_outliers(df, column, method='iqr', threshold=3):
    """检测数值列的异常值"""
    
    if method == 'iqr':
        Q1 = df[column].quantile(0.25)
        Q3 = df[column].quantile(0.75)
        IQR = Q3 - Q1
        lower = Q1 - 1.5 * IQR
        upper = Q3 + 1.5 * IQR
        outliers = df[(df[column] < lower) | (df[column] > upper)]
        
    elif method == 'zscore':
        z = np.abs((df[column] - df[column].mean()) / df[column].std())
        outliers = df[z > threshold]
    
    print(f"{column} 异常值检测 ({method}):")
    print(f"  范围: [{lower:.2f}, {upper:.2f}]" if method == 'iqr' else f"  阈值: {threshold} 个标准差")
    print(f"  异常值: {len(outliers)} 行 ({100*len(outliers)/len(df):.2f}%)")
    
    if len(outliers) > 0:
        print(f"  最小异常值: {outliers[column].min():.2f}")
        print(f"  最大异常值: {outliers[column].max():.2f}")
    
    return outliers

outliers = detect_outliers(df, 'amount', method='iqr')
```

---

## 常见数据质量问题

### 问题 1: 隐式缺失值

```python
# 检测伪装的缺失值
def check_implicit_nulls(df, column):
    """检查常见的隐式缺失值"""
    implicit_nulls = [
        '', ' ', 'null', 'NULL', 'None', 'NA', 'N/A', 
        '-', '--', '?', 'unknown', 'Unknown', 'UNKNOWN',
        '0', '0.0'  # 有时 0 也是缺失的标记
    ]
    
    if df[column].dtype == 'object':
        for null_value in implicit_nulls:
            count = (df[column] == null_value).sum()
            if count > 0:
                print(f"  '{null_value}': {count} 行")

print("隐式缺失值检测:")
for col in df.select_dtypes(include=['object']).columns:
    print(f"\n{col}:")
    check_implicit_nulls(df, col)
```

### 问题 2: 数据截断

```python
# 检测可能被截断的文本
def check_truncation(df, column, max_length=255):
    """检查文本是否可能被截断"""
    if df[column].dtype != 'object':
        return
    
    lengths = df[column].str.len()
    at_max = (lengths == max_length).sum()
    
    if at_max > 0:
        print(f"⚠ {column}: {at_max} 行长度恰好为 {max_length}（可能被截断）")
        print(f"  样本: {df[df[column].str.len() == max_length][column].iloc[0]}")

for col in df.select_dtypes(include=['object']).columns:
    check_truncation(df, col)
```

### 问题 3: 时区混乱

```python
# 检查时区问题
def check_timezone(df, date_column):
    """检查日期列的时区"""
    if not pd.api.types.is_datetime64_any_dtype(df[date_column]):
        print(f"⚠ {date_column} 不是 datetime 类型")
        return
    
    if df[date_column].dt.tz is None:
        print(f"⚠ {date_column} 无时区信息（naive datetime）")
    else:
        print(f"✓ {date_column} 时区: {df[date_column].dt.tz}")
    
    # 检查是否有不合理的小时分布
    hours = df[date_column].dt.hour.value_counts().sort_index()
    if hours.min() == 0 and hours.max() == 0:
        print(f"⚠ 所有时间都在 00:00，可能丢失了时间部分")

check_timezone(df, 'order_date')
```

### 问题 4: 编码问题

```python
# 检测编码问题
def check_encoding(df, column):
    """检测可能的编码问题"""
    if df[column].dtype != 'object':
        return
    
    # 查找乱码特征
    issues = df[column].str.contains('�|\\\\x|\\\\u', na=False).sum()
    if issues > 0:
        print(f"⚠ {column}: {issues} 行可能有编码问题")
        print(f"  样本: {df[df[column].str.contains('�', na=False)][column].iloc[0]}")

for col in df.select_dtypes(include=['object']).columns:
    check_encoding(df, col)
```

---

## 数据清洗模板

### 处理缺失值

```python
def handle_missing(df, strategy='report'):
    """处理缺失值"""
    
    if strategy == 'report':
        # 仅报告
        missing = df.isnull().sum()
        return missing[missing > 0]
    
    elif strategy == 'drop':
        # 删除有缺失的行
        before = len(df)
        df = df.dropna()
        print(f"删除 {before - len(df)} 行（{100*(before-len(df))/before:.1f}%）")
        return df
    
    elif strategy == 'fill_zero':
        # 数值列填 0
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        df[numeric_cols] = df[numeric_cols].fillna(0)
        return df
    
    elif strategy == 'fill_median':
        # 数值列填中位数
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            df[col] = df[col].fillna(df[col].median())
        return df
    
    elif strategy == 'fill_mode':
        # 类别列填众数
        cat_cols = df.select_dtypes(include=['object']).columns
        for col in cat_cols:
            df[col] = df[col].fillna(df[col].mode()[0] if len(df[col].mode()) > 0 else 'Unknown')
        return df

# 使用
df_clean = handle_missing(df.copy(), strategy='fill_median')
```

### 标准化列名

```python
def standardize_columns(df):
    """标准化列名"""
    df.columns = (df.columns
                  .str.strip()                # 去除空格
                  .str.lower()                # 小写
                  .str.replace(' ', '_')      # 空格 → 下划线
                  .str.replace('[^a-z0-9_]', '', regex=True))  # 去除特殊字符
    return df

df = standardize_columns(df)
```

### 日期解析和验证

```python
def parse_dates(df, date_columns, format='%Y-%m-%d', errors='coerce'):
    """解析日期列"""
    for col in date_columns:
        original = df[col].copy()
        df[col] = pd.to_datetime(df[col], format=format, errors=errors)
        
        failed = df[col].isnull() & original.notnull()
        if failed.sum() > 0:
            print(f"⚠ {col}: {failed.sum()} 行解析失败")
            print(f"  样本失败值: {original[failed].iloc[0]}")
    
    return df

df = parse_dates(df, ['order_date', 'shipped_date'])
```

---

## 完整验证流程

```python
def full_validation(df, name='DataFrame'):
    """完整数据质量验证流程"""
    
    print(f"\n{'='*60}")
    print(f"完整数据质量验证: {name}")
    print(f"{'='*60}\n")
    
    # 1. 快速概览
    quick_profile(df, name)
    
    # 2. 验证业务规则
    print("\n业务规则验证:")
    check_business_rules(df)
    
    # 3. 异常值检测
    print("\n异常值检测:")
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    for col in numeric_cols:
        outliers = detect_outliers(df, col)
        if len(outliers) > 0:
            print(f"  {col}: {len(outliers)} 个异常值")
    
    # 4. 生成报告
    print("\n数据质量得分:")
    completeness = 100 * (1 - df.isnull().sum().sum() / (len(df) * len(df.columns)))
    uniqueness = 100 * (1 - df.duplicated().sum() / len(df))
    
    print(f"  完整性: {completeness:.1f}%")
    print(f"  唯一性: {uniqueness:.1f}%")
    print(f"  整体得分: {(completeness + uniqueness) / 2:.1f}%")

# 使用
full_validation(df, 'orders')
```
