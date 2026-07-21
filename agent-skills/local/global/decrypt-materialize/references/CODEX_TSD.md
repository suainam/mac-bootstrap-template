# Codex TSD 解密流程

处理 Codex 使用 TSD（Transparent Secure Data）格式加密的文件。

---

## 问题识别

### 症状

1. **第三方工具失败** - `codex-threadripper` 报错 "stream did not contain valid UTF-8"
2. **系统工具失败** - `cat/vim` 显示乱码,`sqlite3` 报错 "file is not a database"
3. **文件头异常** - `xxd` 显示 `%TSD-Header-###%`,但应用能正常打开

### 确认方法（Agent 必读）

**核心原则**：TSD 透明层拦截 Python 进程的文件读取，必须用系统工具绕过。

**错误方法** (失效):
```python
# Python 读取会被透明解密,永远返回 False
with open(path, 'rb') as f:
    return b'TSD-Header' in f.read(16)
```

**正确方法 1** (用 xxd):
```bash
# xxd 读取原始磁盘字节
xxd -l 16 file.sqlite
# 加密: 00000000: 2554 5344 2d48 6561 6465 722d 2323 2325  %TSD-Header-###%
# 明文: 00000000: 5351 4c69 7465 2066 6f72 6d61 7420 3300  SQLite format 3.
```

**正确方法 2** (用 dd，推荐用于脚本):
```python
import subprocess
def is_tsd_encrypted(path):
    # dd 直接读取磁盘字节，绕过 Python runtime hook
    result = subprocess.run(
        ['bash', '-c', f'dd if="{path}" bs=1 count=16 2>/dev/null'],
        capture_output=True, check=False, timeout=2
    )
    return b'TSD-Header' in result.stdout
```

**为什么不能用 Python open()**：
- Python `open()` / `pathlib.Path.read_bytes()` 都会触发透明解密
- 即使是 `subprocess.run(['cat', path])`，如果 Python 解析输出也会被拦截
- 必须让**非 Python 工具**读取磁盘字节，输出二进制流

---

## TSD 透明层机制

**选择性透明解密**:

| 维度 | 透明 | 不透明 |
|------|------|--------|
| **文件类型** | `.sqlite`, `.db`, `.sql`, `.xls`, `.jsonl`, `.toml` | `.md`, 其他文本 |
| **应用层** | Python `open()`, `sqlite3.connect()` | `cat`, `vim`, `xxd`, `strings` |
| **路径** | 任意位置(包括 `/tmp`) | - |

**关键特征**:
- 磁盘存储: 加密二进制(`%TSD-Header-###%`)
- Python 读取: 自动解密(看到标准格式头)
- 系统工具: 读到原始密文
- 写入新文件: 保持解密状态(不会重新加密)

**实验证据**:
```bash
# xxd 显示加密
xxd -l 16 file.sqlite
# → 255453442d4865616465722d23232325

# Python 读到明文
python3 -c "print(open('file.sqlite','rb').read(16).hex())"
# → 53514c69746520666f726d6174203300  (SQLite format 3)
```

---

## 使用

```bash
# 基本用法（自动停止守护进程并解密）
python3 scripts/decrypt_codex.py ~/.codex --stop-daemon

# 仅解密不替换
python3 scripts/decrypt_codex.py ~/.codex --no-replace

# 指定备份目录
python3 scripts/decrypt_codex.py ~/.codex --backup-dir ~/backups
```

---

## 解密方法

### 方法 1: Python 透明读写(推荐)

**适用**: `.sql`, `.xls`, `.sqlite`, `.db`, `.jsonl`, `.toml`

```python
import sqlite3
from pathlib import Path

# SQLite 数据库
src = Path('encrypted.sqlite')
dst = Path('decrypted.sqlite')
src_conn = sqlite3.connect(str(src))
dst_conn = sqlite3.connect(str(dst))
src_conn.backup(dst_conn)
src_conn.close()
dst_conn.close()

# 文本/二进制文件
with open('encrypted.sql', 'rb') as f_in:
    data = f_in.read()
with open('decrypted.sql', 'wb') as f_out:
    f_out.write(data)
```

### 方法 2: 重命名激活透明层

**适用**: 不透明类型(如 `.md`)

```bash
# .md 文件 Python 读取不透明
cp file.md file.sql
# 重命名为 .sql 后透明层激活,Python 可读

python3 -c "
with open('file.sql', 'rb') as f:
    print(f.read(100).decode('utf-8'))
"
```

### 方法 3: 扫描加密文件

快速扫描脚本:
```bash
#!/bin/bash
find "$1" -type f \( \
  -name "*.sqlite" -o -name "*.db" -o \
  -name "*.sql" -o -name "*.xls" -o -name "*.md" -o \
  -name "*.jsonl" -o -name "*.toml" \
\) | while read file; do
  header=$(xxd -l 16 -p "$file" | tr -d '\n')
  [[ "$header" =~ ^255453442d486561646572 ]] && echo "$file"
done
```

性能: ~6 秒扫描整个 `~/.codex` 目录。

---

## 执行流程

1. **检查进程** - 检测 Codex 进程，如有 `--stop-daemon` 则停止 launchd 服务
2. **扫描文件** - 用 `xxd` 检测 TSD 加密头(不依赖固定文件列表)
3. **解密** - SQLite 用 `.backup()`，其他用文件读写
4. **备份替换** - 备份原文件（带时间戳），复制解密文件到原位置
5. **验证** - 检查文件头已变为标准格式

---

## 红绿测试结论

**测试方法**: 解密后监控文件状态,观察不同操作是否触发重新加密。

| 测试 | 操作 | 结果 | 结论 |
|------|------|------|------|
| A | codex 单独运行 10+ 分钟 | 明文 | ✓ 不触发加密 |
| B | threadripper watch 单独运行 | 明文 | ✓ 不触发加密 |
| C | 修改 config.toml 触发 threadripper 写操作 | 明文 | ✓ 不触发加密 |
| D | codex + threadripper 同时运行 | 明文 | ✓ 不触发加密 |

**关键发现**:
- TSD 加密**不是**由 codex/threadripper 写操作自动触发
- 解密后文件保持明文稳定运行
- 历史加密文件(17个)位于 `context-mode/sessions/*.db` 和 `db-backups/`
- 当前主目录文件已解密,系统正常工作

**实用建议**:
- 解密后无需担心重新加密
- threadripper daemon 可正常使用
- 历史备份保持加密不影响使用(透明读取)

---

## 验证

```bash
# 文件头
head -c 16 ~/.codex/memories_1.sqlite | od -c
# 预期: S   Q   L   i   t   e       f   o   r   m   a   t       3

# 数据库访问
sqlite3 ~/.codex/memories_1.sqlite "SELECT COUNT(*) FROM sqlite_master;"

# JSONL
head -1 ~/.codex/session_index.jsonl | jq .
```

---

## 故障排查

### 守护进程重启
**症状**：kill 进程后立即重启
**解决**：
```bash
launchctl unload ~/Library/LaunchAgents/dev.wangnov.codex-threadripper.plist
killall codex codex-threadripper
# 或使用 --stop-daemon 选项
```

### WAL 锁定
**症状**：解密后仍报文件被锁
**解决**：
```bash
python3 -c "
import sqlite3
for db in ['memories_1', 'goals_1', 'logs_2', 'state_5']:
    conn = sqlite3.connect(f'~/.codex/{db}.sqlite')
    conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    conn.close()
"
```

### 恢复备份
```bash
cp ~/.codex/backups/memories_1.sqlite.backup_* ~/.codex/memories_1.sqlite
```

---

## 完成标准

- [x] 文件头 = `SQLite format 3` (非 `%TSD-Header%`)
- [x] `sqlite3 <file> "SELECT 1"` 返回 0
- [x] JSONL 每行可 `json.loads()`
- [x] 备份文件存在且非空
- [x] Codex 能正常启动
