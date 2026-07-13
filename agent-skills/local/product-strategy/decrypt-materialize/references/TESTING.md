# decrypt-materialize Skill 测试指南

本文档说明如何测试 decrypt-materialize skill。

## 前置依赖

```bash
# 安装 Python 依赖
pip3 install openpyxl           # Excel 支持
pip3 install numbers-parser==4.18.5  # Numbers 支持（可选）
```

## 运行测试

### 自动化测试

```bash
cd template/agent-skills/local/product-strategy/decrypt-materialize
python3 scripts/test_materialize.py
```

测试覆盖：
- ✅ 基本导出（全部工作表）
- ✅ 工作表映射（选择性导出 + 英文命名）
- ✅ 加密检测（错误处理）
- ✅ 命名规范验证（单下划线 `_`）
- ✅ CSV 验证（行数、列数、禁止值）

### 手动测试

#### 测试 1: Excel 文件导出

```bash
# 创建测试文件
python3 -c "
from openpyxl import Workbook
wb = Workbook()
ws = wb.active
ws.title = 'TestSheet'
ws.append(['Name', 'Value'])
ws.append(['Item1', 100])
ws.append(['Item2', 200])
wb.save('/tmp/test.xlsx')
"

# 导出
python3 scripts/materialize.py /tmp/test.xlsx --date-tag 20260713

# 验证输出
cat /tmp/test_TestSheet_20260713.csv
```

预期输出：
```csv
Name,Value
Item1,100
Item2,200
```

#### 测试 2: 工作表映射

```bash
# 使用中文工作表名
python3 -c "
from openpyxl import Workbook
wb = Workbook()
ws = wb.active
ws.title = '商品数据'
ws.append(['ID', '名称'])
ws.append([1, '苹果'])
wb.save('/tmp/产品.xlsx')
"

# 导出并映射为英文名
python3 scripts/materialize.py /tmp/产品.xlsx \
  --date-tag 20260713 \
  --sheet-map '{"商品数据":"product_data"}'

# 验证文件名（应该使用英文名）
ls -l /tmp/产品_product_data_20260713.csv
```

#### 测试 3: 命名规范验证

```bash
# 验证单下划线分隔
ls /tmp/*.csv | while read f; do
  if echo "$f" | grep -q '__'; then
    echo "❌ 发现双下划线: $f"
  else
    echo "✅ 命名正确: $(basename $f)"
  fi
done
```

#### 测试 4: 加密检测

```bash
# 创建密码保护的 Excel（需要 Excel 应用）
# 或者测试不存在的文件
python3 scripts/materialize.py /tmp/nonexistent.xlsx

# 预期输出: JSON 错误信息
# {
#   "error": "Cannot open: ...",
#   ...
# }
```

#### 测试 5: Numbers 文件（如果有 numbers-parser）

```bash
# 假设有 test.numbers 文件
python3 scripts/materialize.py ~/Downloads/test.numbers --date-tag 20260713

# 验证输出
ls -l ~/Downloads/test_*_20260713.csv
```

## 集成测试

### 测试完整工作流

```bash
#!/bin/bash
# integration_test.sh

set -e

echo "=== 集成测试开始 ==="

# 1. 创建测试数据
python3 -c "
from openpyxl import Workbook
wb = Workbook()

# 工作表 1
ws1 = wb.active
ws1.title = 'Products'
ws1.append(['ID', 'Name', 'Price'])
ws1.append([1, 'Apple', 5.5])
ws1.append([2, 'Banana', 3.2])

# 工作表 2
ws2 = wb.create_sheet('Sales')
ws2.append(['Date', 'Product', 'Quantity'])
ws2.append(['2026-07-01', 'Apple', 10])
ws2.append(['2026-07-02', 'Banana', 20])

wb.save('/tmp/integration_test.xlsx')
"

# 2. 导出
python3 scripts/materialize.py /tmp/integration_test.xlsx \
  --output-dir /tmp/csv_output \
  --date-tag 20260713

# 3. 验证
echo "=== 验证输出 ==="
for csv in /tmp/csv_output/*.csv; do
  echo "文件: $(basename $csv)"
  echo "行数: $(wc -l < $csv)"
  echo "内容预览:"
  head -n 3 "$csv"
  echo ""
done

echo "=== 集成测试完成 ==="
```

## 性能测试

```bash
# 测试大文件处理
python3 -c "
from openpyxl import Workbook
wb = Workbook()
ws = wb.active
ws.append(['ID', 'Value'])
for i in range(10000):
    ws.append([i, f'Value_{i}'])
wb.save('/tmp/large.xlsx')
"

# 计时导出
time python3 scripts/materialize.py /tmp/large.xlsx --date-tag 20260713
```

## 回归测试清单

每次修改脚本后，运行以下检查：

- [ ] 单工作表导出
- [ ] 多工作表导出
- [ ] 工作表映射
- [ ] 空工作表过滤
- [ ] 特殊字符处理（`/` `\` in sheet name）
- [ ] 中文文件名和工作表名
- [ ] 命名规范（单下划线）
- [ ] CSV 编码（UTF-8 with BOM）
- [ ] 禁止值规范化（NULL, NaN, #N/A）
- [ ] 加密文件错误处理
- [ ] JSON 输出格式

## 故障排除

### 问题：找不到 openpyxl

```bash
pip3 install openpyxl
```

### 问题：找不到 numbers-parser

```bash
pip3 install "numbers-parser==4.18.5"
```

### 问题：文件名包含双下划线

检查 `materialize.py` 中的命名逻辑：
```python
# 应该是单下划线
output_path = output_dir / f"{workbook_name}_{safe_name}_{date_tag}.csv"
```

### 问题：CSV 包含禁止值

检查 `normalize_cell()` 函数，确保正确过滤：
- NULL, null, None, none, NaN, nan
- #N/A, #REF!, #VALUE!, #DIV/0!, #NAME?, #NUM!, #NULL!
