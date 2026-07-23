# 工作簿物化流程

详细步骤：检测加密 → 检查结构 → 导出 CSV → 验证 → 报告。

---

## 步骤 1: 检测格式与加密状态

### 格式识别

根据扩展名选择解析器：
- `.numbers` → `numbers-parser`
- `.xlsx` / `.xls` → `openpyxl`
- `.ods` → `pandas` 或 `odfpy`

### 加密检测

**先尝试直接打开**。如果失败，判断失败原因：

```python
# Excel 加密检测
from openpyxl import load_workbook
try:
    wb = load_workbook(path)
    status = "可访问"
except Exception as e:
    if 'password' in str(e).lower() or 'encrypted' in str(e).lower():
        status = "密码保护"
    elif 'corrupt' in str(e).lower():
        status = "文件损坏"
    else:
        status = f"其他错误: {e}"
```

### 阻塞处理

- **密码保护**：报告无法访问，要求用户提供解密副本或密码
- **文件损坏**：报告文件损坏，要求用户修复或提供其他版本
- **其他错误**：报告完整错误信息

**完成标准**：工作簿无错误加载，或明确报告阻塞原因（加密/损坏）。

---

## 步骤 2: 检查结构

记录以下信息：

1. **工作簿元数据**
   - 文件名（去除扩展名）：`Q2_Sales.numbers` → `Q2_Sales`
   - 完整路径

2. **工作表清单**
   - 工作表名称列表
   - 每个工作表的行数、列数
   - 每个工作表的首行（header）

3. **日期标签**
   - 从用户输入提取：`--date-tag 20260713`
   - 从文件名推断：`data_20260713.xlsx` → `20260713`
   - 默认：当前日期 `YYYYMMDD`

4. **目标工作表**
   - 用户指定：通过 `--sheets` 或 `--sheet-map`
   - 默认：所有包含数据的工作表

**完成标准**：每个目标工作表都有确认的存在、行数、列数。

---

## 步骤 3: 导出暂存 CSV

### 命名规范

**模式**：`{工作簿名}_{工作表名}_{日期标签}.csv`

- `{工作簿名}`：原始文件名去除扩展名
- `{工作表名}`：清理后的工作表名
  - 替换 `/` `\` 为 `_`
  - 可选：转为 `snake_case` 小写（通过 `--sheet-map` 提供英文名）
- `{日期标签}`：`YYYYMMDD` 格式
- **单下划线 `_` 分隔**，不使用双下划线

### 示例

| 工作簿 | 工作表 | 日期标签 | 输出文件名 |
|--------|--------|----------|------------|
| `Q2_Sales.numbers` | `Summary` | `20260713` | `Q2_Sales_Summary_20260713.csv` |
| `产品数据.xlsx` | `商品信息` | `20260713` | `产品数据_商品信息_20260713.csv` |
| `产品数据.xlsx` | `商品信息` (映射为 `product_info`) | `20260713` | `产品数据_product_info_20260713.csv` |

### 规范化规则

应用 `OUTPUT_CONTRACT.md` 规则：
- 空单元格 → `""`
- Excel 错误值（`#N/A`, `#REF!`, `#VALUE!`, `#DIV/0!`, `#NAME?`, `#NUM!`, `#NULL!`）→ `""`
- 占位符字符串（`NULL`, `null`, `None`, `none`, `NaN`, `nan`，trim 后）→ `""`
- 保持：普通字符串、数值、原始行列顺序

### 空工作表不导出

工作表整体无数据（`rows == 0`，跳过空行后）时，**不写 CSV 文件**，只在报告里标记 `skipped: true` 并给出原因。避免为空表生成 0 字节垃圾文件、污染暂存目录、拖累下游合并/校验脚本。

`xlsx`（openpyxl）和 `xls`（xlrd）两条导出路径都已实现此跳过逻辑；`numbers` 路径在选表阶段已通过 `_has_data_numbers` 过滤空表，天然不受影响。

### 执行

```bash
# 统一入口（推荐）
python3 scripts/materialize.py source.xlsx --output-dir ./staging/ --date-tag 20260713

# 指定工作表映射
python3 scripts/materialize.py source.xlsx \
  --output-dir ./staging/ \
  --date-tag 20260713 \
  --sheet-map '{"中文名":"english_name"}'
```

**完成标准**：每个目标工作表有一个 CSV 文件在预期路径。

---

## 步骤 4: 验证暂存集

对每个生成的 CSV：

1. **存在性**：文件已写入
2. **可读性**：可以用 CSV reader 打开
3. **结构匹配**：
   - 行数 = 源工作表行数
   - 列数 = 源工作表列数
4. **值清洁**：无禁止的占位符值（`NULL`, `NaN` 等）

### 验证脚本示例

```python
import csv
from pathlib import Path

def verify_csv(path: Path, expected_rows: int, expected_cols: int):
    with path.open('r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        rows = list(reader)
    
    actual_rows = len(rows)
    actual_cols = max(len(row) for row in rows) if rows else 0
    
    assert actual_rows == expected_rows, f"行数不匹配: {actual_rows} != {expected_rows}"
    assert actual_cols == expected_cols, f"列数不匹配: {actual_cols} != {expected_cols}"
    
    # 检查禁止值
    forbidden = {'NULL', 'NaN', 'None'}
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            if cell.strip() in forbidden:
                raise ValueError(f"禁止值 '{cell}' 出现在 ({i}, {j})")
    
    return True
```

**完成标准**：每个 CSV 通过验证，或报告具体失败原因。

---

## 步骤 5: 紧凑报告

输出 JSON 格式的处理结果：

```json
{
  "source": "/path/to/workbook.xlsx",
  "workbook_name": "workbook",
  "encrypted": false,
  "date_tag": "20260713",
  "sheets": [
    {
      "sheet": "Sheet1",
      "file": "/path/to/output/workbook_Sheet1_20260713.csv",
      "rows": 100,
      "cols": 5,
      "verified": true
    }
  ]
}
```

如果加密阻塞：

```json
{
  "source": "/path/to/workbook.xlsx",
  "encrypted": true,
  "error": "Password-protected workbook",
  "resolution": "Provide password or decrypted copy"
}
```

**完成标准**：下游系统可以直接解析 JSON 并获取文件，无需重新阅读对话。
