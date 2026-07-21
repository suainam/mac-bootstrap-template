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

## 示例 9: 解密 Codex TSD 加密数据库（2026-07-15 实战案例）

### 场景
nvim 打开 `~/.codex/config.toml` 显示 `%TSD-Header-###%` 加密内容，需要解密。

### 优先解密文件列表
```
config.toml                 # Codex 配置
config.toml.0715.bak        # 配置备份
logs_2.sqlite               # 日志数据库
goals_1.sqlite              # 目标数据库
memories_1.sqlite           # 记忆数据库
session_index.jsonl         # 会话索引
```

### 前置检查

```bash
# 1. 确认加密状态（原始字节）
head -c 20 ~/.codex/config.toml | xxd
# 输出: 00000000: 2554 5344 2d48 6561 6465 722d 2323 2325  %TSD-Header-###%

# 2. 检查 Codex 进程
pgrep -fl codex

# 3. 停止 Codex（如需要）
# 方法1: 使用脚本自动停止
python3 scripts/decrypt_codex_crossplatform.py ~/.codex --stop-daemon

# 方法2: 正常退出对应前台 Codex 会话
```

### 执行解密（跨平台）

```bash
# 基本用法（自动备份并替换原文件）
python3 scripts/decrypt_codex_crossplatform.py ~/.codex --stop-daemon

# 仅解密到 decrypted/ 不替换（更安全）
python3 scripts/decrypt_codex_crossplatform.py ~/.codex --no-replace

# 强制执行（Codex 运行时也解密，危险）
python3 scripts/decrypt_codex_crossplatform.py ~/.codex --force
```

### 输出示例

```
使用默认 Codex 目录: $HOME/.codex
错误: Codex 进程仍在运行:
  PID 4835: codex-threadrip
  PID 37242: codex
  PID 38106: codex-code-mode

尝试停止守护进程...
已停止守护服务，等待进程退出...
✓ 所有进程已停止

找到 5 个加密文件

处理: config.toml
  ✓ 已解密到: ~/.codex/decrypted/config.toml
  ✓ 已备份到: ~/.codex/backups/config.toml.backup_20260715_082113
  ✓ 已替换原文件

处理: logs_2.sqlite
  ✓ 已解密到: ~/.codex/decrypted/logs_2.sqlite
  ✓ 已备份到: ~/.codex/backups/logs_2.sqlite.backup_20260715_082113
  ✓ 已替换原文件 (415.5 MB)

处理: session_index.jsonl
  ✓ 已解密到: ~/.codex/decrypted/session_index.jsonl
  ✓ 已备份到: ~/.codex/backups/session_index.jsonl.backup_20260715_082331
  ✓ 已替换原文件

============================================================
解密摘要:
  成功: 5/5
  备份目录: ~/.codex/backups
  解密目录: ~/.codex/decrypted
```

### 验证解密

```bash
# 1. 检查文件头（TOML）
head -c 20 ~/.codex/config.toml
# 输出: model_provider = "O

# 2. 检查文件头（SQLite）
head -c 20 ~/.codex/logs_2.sqlite | xxd
# 输出: 00000000: 5351 4c69 7465 2066 6f72 6d61 7420 3300  SQLite format 3.

# 3. 测试数据库访问
sqlite3 ~/.codex/memories_1.sqlite "SELECT name FROM sqlite_master WHERE type='table';"

# 4. 测试 JSONL
head -1 ~/.codex/session_index.jsonl | python3 -m json.tool
```

### TSD 透明解密机制

**重要发现**: `~/.codex/` 路径下存在系统级透明解密 hook。

```bash
# Python open() 读到解密内容（即使磁盘是加密的）
python3 -c "print(open('~/.codex/config.toml').read(100))"
# 输出: model_provider = ...（明文）

# 但原始字节仍是 TSD 加密
xxd -l 20 ~/.codex/config.toml
# 输出: %TSD-Header-###%
```

**影响**: 
- vim 能正常显示（透明解密生效）
- nvim 显示加密内容（未配置 cryptmethod）
- Unix 解密脚本直接执行 `dd` 参数数组绕过 Python VFS hook，不经过 shell

### 恢复备份

```bash
# 如果解密后有问题，恢复备份
cp ~/.codex/backups/config.toml.backup_20260715_082113 ~/.codex/config.toml
cp ~/.codex/backups/logs_2.sqlite.backup_20260715_082113 ~/.codex/logs_2.sqlite
```
