# 使用示例

常见场景的完整示例。

---

## 示例 1: Numbers 文件快速导出

### 场景
将 Apple Numbers 文件的所有工作表导出为 CSV。

### 执行

```bash
# 自动导出所有工作表到当前目录
python3 scripts/materialize.py ~/Downloads/Q2_Sales.numbers

# 指定输出目录
python3 scripts/materialize.py ~/Downloads/Q2_Sales.numbers --output-dir ~/staging/

# 指定日期标签
python3 scripts/materialize.py ~/Downloads/Q2_Sales.numbers \
  --output-dir ~/staging/ \
  --date-tag 20260713
```

### 输出

```
Q2_Sales.numbers 包含 3 个工作表：
- Summary → Q2_Sales_Summary_20260713.csv (10 行, 5 列)
- Details → Q2_Sales_Details_20260713.csv (100 行, 8 列)
- Chart Data → Q2_Sales_Chart_Data_20260713.csv (50 行, 3 列)
```

---

## 示例 2: Excel 文件全部导出

### 场景
导出 Excel 文件的所有工作表，保持原始工作表名称。

### 执行

```bash
python3 scripts/materialize.py ~/Downloads/销售报表.xlsx \
  --output-dir ~/staging/ \
  --date-tag 20260713
```

### 输出

```
销售报表.xlsx 包含 2 个工作表：
- 商品信息 → 销售报表_商品信息_20260713.csv
- 销售数据 → 销售报表_销售数据_20260713.csv
```

---

## 示例 3: Excel 文件选择性导出（带工作表映射）

### 场景
只导出指定的工作表，并使用英文名称。

### 执行

```bash
python3 scripts/materialize.py ~/Downloads/产品数据.xlsx \
  --output-dir ~/staging/ \
  --date-tag 20260713 \
  --sheet-map '{"商品信息":"product_info","销售数据":"sales_data"}'
```

### 输出

```
产品数据.xlsx 包含 4 个工作表，导出 2 个：
- 商品信息 → 产品数据_product_info_20260713.csv (500 行, 10 列)
- 销售数据 → 产品数据_sales_data_20260713.csv (1000 行, 6 列)

跳过工作表：配置表, 备注
```

---

## 示例 4: 检测加密的工作簿

### 场景
尝试打开可能加密的工作簿。

### 执行

```bash
python3 scripts/materialize.py ~/Downloads/confidential.xlsx
```

### 输出（加密）

```json
{
  "source": "~/Downloads/confidential.xlsx",
  "encrypted": true,
  "error": "Password-protected workbook",
  "resolution": "Provide password or decrypted copy"
}
```

### 输出（未加密）

```json
{
  "source": "~/Downloads/confidential.xlsx",
  "workbook_name": "confidential",
  "encrypted": false,
  "date_tag": "20260713",
  "sheets": [
    {
      "sheet": "Data",
      "file": "~/Downloads/confidential_Data_20260713.csv",
      "rows": 200,
      "cols": 15,
      "verified": true
    }
  ]
}
```

---

## 示例 5: 批量处理多个工作簿

### 场景
批量转换一个目录下的所有工作簿。

### 执行

```bash
#!/bin/bash
# batch_materialize.sh

INPUT_DIR=~/Downloads/workbooks
OUTPUT_DIR=~/staging/csv_output
DATE_TAG=$(date +%Y%m%d)

for file in "$INPUT_DIR"/*.{xlsx,numbers,xls}; do
  [ -f "$file" ] || continue
  echo "处理: $file"
  python3 scripts/materialize.py "$file" \
    --output-dir "$OUTPUT_DIR" \
    --date-tag "$DATE_TAG"
done

echo "批量处理完成"
```

---

## 示例 6: Smudged YAML 文件读取

### 场景
Read 工具显示乱码，需要读取实际内容。

### 问题

```python
# Read 工具返回乱码
content = read_tool("private/database.yaml")
print(content)
# 输出: ��Q��...乱码
```

### 解决

```bash
# 方法 1: Shell 直接读取
cat private/database.yaml

# 方法 2: Python 读取
python3 -c "
with open('private/database.yaml') as f:
    print(f.read())
"

# 方法 3: Python 解析
python3 -c "
import yaml
with open('private/database.yaml') as f:
    config = yaml.safe_load(f)
    print(config)
"
```

---

## 示例 7: 编辑 Smudged TOML 配置

### 场景
更新被 git-smudge 加密的配置文件。

### 执行

```bash
# 1. 直接编辑（看到明文）
vim private/app.toml

# 修改某个配置项
# [server]
# port = 8080  →  port = 9000

# 2. 保存并提交
git add private/app.toml
git commit -m "更新服务器端口"

# 3. 验证加密状态
git show HEAD:private/app.toml | head -c 50
# 输出: 加密的二进制内容

# 4. 验证磁盘内容
head private/app.toml
# 输出: [server]\nport = 9000
```

---

## 示例 8: Python 脚本完整工作流

### 场景
从加密配置读取数据库连接，然后处理工作簿。

### 代码

```python
#!/usr/bin/env python3
"""完整工作流示例"""

import yaml
from pathlib import Path
import subprocess
import json

# 1. 读取加密的配置文件（绕过 Read 工具）
config_path = Path("private/database.yaml")
with config_path.open() as f:
    db_config = yaml.safe_load(f)

print(f"数据库: {db_config['host']}")

# 2. 物化工作簿
workbook = Path("~/Downloads/sales.xlsx").expanduser()
output_dir = Path("~/staging/").expanduser()
date_tag = "20260713"

result = subprocess.run([
    "python3", "scripts/materialize.py",
    str(workbook),
    "--output-dir", str(output_dir),
    "--date-tag", date_tag
], capture_output=True, text=True)

# 3. 解析结果
if result.returncode == 0:
    summary = json.loads(result.stdout)
    print(f"成功导出 {len(summary['sheets'])} 个工作表")
    for sheet in summary['sheets']:
        print(f"  - {sheet['file']} ({sheet['rows']} 行)")
else:
    print(f"错误: {result.stderr}")

# 4. 后续处理（例如导入数据库）
# import_to_database(summary['sheets'], db_config)
```

---

## 示例 9: 解密 Codex TSD 加密数据库

### 场景
Codex 无法启动，报告数据库文件被锁或无法访问。

### 前置检查

```bash
# 1. 确认加密状态
head -c 16 ~/.codex/memories_1.sqlite | od -c
# 输出: %   T   S   D   -   H   e   a   d   e   r   ...

# 2. 检查 Codex 是否在运行
ps aux | grep codex | grep -v grep

# 3. 如果在运行，完全退出 Codex
```

### 执行解密

```bash
# 基本用法（自动备份并替换）
python3 scripts/decrypt_codex.py ~/.codex

# 仅解密不替换（更安全）
python3 scripts/decrypt_codex.py ~/.codex --no-replace

# 指定备份目录
python3 scripts/decrypt_codex.py ~/.codex --backup-dir ~/codex_backups
```

### 输出示例

```
找到 5 个加密文件

处理: memories_1.sqlite
  ✓ 已解密到: ~/.codex/decrypted/memories_1.sqlite
  ✓ 已备份到: ~/.codex/backups/memories_1.sqlite.backup_20260713_220530
  ✓ 已替换原文件

处理: session_index.jsonl
  ✓ 已解密到: ~/.codex/decrypted/session_index.jsonl
  ✓ 已备份到: ~/.codex/backups/session_index.jsonl.backup_20260713_220530
  ✓ 已替换原文件

============================================================
解密摘要:
  成功: 5/5
  备份目录: ~/.codex/backups
  解密目录: ~/.codex/decrypted
```

### 验证解密

```bash
# 检查文件头已变为标准格式
head -c 16 ~/.codex/memories_1.sqlite | od -c
# 输出: S   Q   L   i   t   e       f   o   r   m   a   t       3

# 测试数据库访问
sqlite3 ~/.codex/memories_1.sqlite "SELECT COUNT(*) FROM sqlite_master;"

# 测试 JSONL
head -1 ~/.codex/session_index.jsonl | jq .
```

### 恢复备份（如需要）

```bash
# 如果解密后仍有问题，恢复备份
cp ~/.codex/backups/memories_1.sqlite.backup_20260713_220530 \
   ~/.codex/memories_1.sqlite
```
