# Codex TSD 解密流程

处理 Codex 应用使用 TSD（Transparent Secure Data）格式加密的数据库文件。

---

## 问题识别

### 症状

1. **Codex 无法启动** - 报告数据库文件被锁定或无法访问
2. **命令行工具失败** - `sqlite3` 报错 "file is not a database (26)"
3. **文件头异常** - 文件开头是 `%TSD-Header-###%` 而非标准格式

### 确认

```bash
head -c 16 ~/.codex/memories_1.sqlite | od -c
# 加密: %   T   S   D   -   H   e   a   d   e   r   -   #   #   #   %
# 标准: S   Q   L   i   t   e       f   o   r   m   a   t       3
```

---

## 解密原理

**TSD = 透明应用层加密**：
- 磁盘：加密二进制（TSD 头）
- Python API：透明读取加密文件
- 写入新文件：自动变为标准格式
- **无需密钥** - sqlite3/文件 API 自动处理

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

## 执行流程

1. **检查进程** - 检测 Codex 进程，如有 `--stop-daemon` 则停止 launchd 服务
2. **扫描文件** - 检查已知文件列表中的 TSD 加密文件
3. **解密** - SQLite 用 `.backup()`，JSONL 用文件读写
4. **备份替换** - 备份原文件（带时间戳），复制解密文件到原位置
5. **验证** - 检查文件头已变为标准格式

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
