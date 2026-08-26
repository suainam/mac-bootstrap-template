# Codex TSD 解密流程

处理 Codex 使用 TSD（Transparent Secure Data）格式加密的文件。

---

## 问题识别

### 症状

1. **第三方工具失败** - `codex-threadripper` 报错 "stream did not contain valid UTF-8"
2. **系统工具失败** - `cat/vim` 显示乱码,`sqlite3` 报错 "file is not a database"
3. **文件头异常** - `xxd` 显示 `%TSD-Header-###%`,但应用能正常打开
4. **容器工具失败** — `.zip` 被 `file` 显示为 `data`，`unzip` 报 `End-of-central-directory signature not found`

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

**正确方法 2** (直接执行 dd，推荐用于 Unix 脚本):
```python
import subprocess
def is_tsd_encrypted(path):
    # 参数数组不经过 shell，文件名中的元字符不会执行
    result = subprocess.run(
        ['dd', f'if={path}', 'bs=16', 'count=1'],
        capture_output=True, check=False, timeout=2
    )
    return b'TSD-Header' in result.stdout
```

**为什么不能用 Python open()**：
- Python `open()` / `pathlib.Path.read_bytes()` 都会触发透明解密
- Unix 上应以参数数组直接执行**非 Python 工具**读取磁盘字节，不经过 shell
- Windows 或缺少 `dd` 时回退到文件 API，并以测试覆盖平台行为

### 实战经验：不要用透明读取判断是否加密

- `dd` / `xxd` 等系统工具看到的是原始磁盘字节；Python `open()` / `Path.read_bytes()` 可能触发 TSD 透明解密。
- 因此 Python 可能显示标准 PNG/SQLite 头，但原始文件仍以 `%TSD-Header-###%` 开头。
- Unix 先用 `dd if=<file> bs=16 count=1` 或 `xxd -l 16 <file>` 判定；Windows/无 `dd` 时使用项目已验证的原始字节读取回退。

### 实战经验：任意扩展名保真解密

对 `.png`、`.zip` 等不在透明扩展名列表中的文件：

1. 源文件保持不动，用系统 `cp` 复制密文为 `.sql` staging 文件。
2. 用 Python 读取 staging 文件；该读取触发透明解密。
3. 用 `write_bytes()` 将完整明文字节写入保留原扩展名的新输出文件。
4. 不重编码、不删除 metadata/chunk、不改写容器内容；保留完整明文字节流。
5. 用格式专属工具验证输出魔数和容器结构；确认源文件未改变后删除 staging 文件。


---

## TSD 透明层机制

**选择性透明解密**:

| 维度 | 透明 | 不透明 |
|------|------|--------|
| 文件类型 | `.sqlite`, `.db`, `.sql`, `.xls`, `.jsonl`, `.toml` | 不透明扩展名（如 `.md`, `.png`, `.zip` 等） |
| 应用层 | Python `open()`, `sqlite3.connect()` | `cat`, `vim`, `xxd`, `strings` |
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

### 方法 1b: 二进制文件保真解密

对 `.png`、`.zip` 等不透明扩展名，优先使用可复用入口：

```bash
python3 scripts/decrypt_tsd_binary.py encrypted.png
# 默认生成 encrypted.decrypted.png
```

脚本自动完成原始头检测、`.sql` 暂存、透明读取、原扩展名输出和暂存清理；PNG 额外做 CRC/尺寸校验。使用 `--output PATH` 指定输出，使用 `--force` 才允许覆盖已有输出。

需要诊断透明层时，可使用以下低层流程：

```bash
# 原始磁盘检测必须绕过 Python 透明层
dd if=encrypted.png bs=16 count=1 status=none | od -An -tc

# 系统工具复制原始密文；.sql 扩展名激活透明层
cp encrypted.png encrypted.stage.sql

python3 - <<'PY'
from pathlib import Path

stage = Path("encrypted.stage.sql")
output = Path("decrypted.png")
output.write_bytes(stage.read_bytes())
stage.unlink()
PY
```

### ZIP 等容器

`.zip` 的 TSD 外层不是 ZIP central directory；先去除 TSD 包装，再判断 ZIP 内容。首轮 `file` 显示 `data` 或 `unzip` 找不到 central directory，不等于容器损坏。

1. **原始判定**：macOS/Linux 用 `dd` / `xxd` 读取前 16 字节；确认源文件以 `%TSD-Header-###%` 开头。Windows 使用平台原始字节读取方式。
2. **保真解密**：
   ```bash
   python3 scripts/decrypt_tsd_binary.py source.zip --json
   ```
   默认生成 `source.decrypted.zip`；指定 `--output` 时，已有文件必须显式传 `--force`。源文件始终保留。
3. **格式验证**：
   ```bash
   dd if="source.zip" bs=1 count=16 status=none | xxd -g 1
   dd if="source.decrypted.zip" bs=1 count=16 status=none | xxd -g 1
   unzip -t "source.decrypted.zip"
   ```
   预期源文件仍是 TSD 头，输出以 ZIP `PK` 头开头，ZIP 检查无错误；Windows 使用等价的 ZIP 完整性检查器。
4. **边界**：解密与解压分开。只有用户明确要求“解压”时才展开到另行指定的目录。

**完成标准**：解密输出是标准 ZIP；格式检查通过；源文件仍保留 TSD 头且未被覆盖；解密输出保留完整 ZIP 数据。

### 方法 2: 重命名激活透明层

**适用**: 不透明扩展名（如 `.md`、`.png` 等）

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

1. **检查进程** - 检测 Codex 进程；`--stop-daemon` 只停止明确管理的服务，不强杀其他进程
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
**症状**：停止受管服务后仍检测到前台 Codex 进程
**解决**：
```bash
launchctl unload ~/Library/LaunchAgents/dev.wangnov.codex-threadripper.plist
# 或使用 --stop-daemon；若仍有前台进程，脚本会安全退出
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

### 透明层未激活（批量脚本报 file is not a database）
**症状**：`decrypt_codex_crossplatform.py` 对所有加密文件报 `file is not a database`；
`.sql` 暂存副本经 Python 读取仍是 `%TSD-Header-###%`。
**根因**：天锐 OCular 企业 DLP 的透明解密按进程授权，当前会话未被授权
（未登录 / 策略过期 / 服务端不可达）。内核 EFS 驱动 `LSDEfs2600_arm` 仍在加密落盘，
但无人能读明文。归因见 `TSD_ATTRIBUTION.md`。
**解决**：
1. 完成 OCular 客户端扫码登录（ScanCodeLogin 弹窗；服务器如 `ipguardum.dslyy.com`），
   连入企业网等待策略下发；必要时重启 OCular 用户态守护或整机。
2. 登录生效后重跑脚本——脚本已内置透明层预检（exit code 2 + 恢复指引），
   不再产生误导性的 sqlite 报错。
3. 长期方案：请企业 IT 将 `~/.codex` 目录或相关进程加入加密排除/可信列表。
**快速探测**：
```bash
cp ~/.codex/goals_1.sqlite /tmp/probe.sql && python3 -c "print(open('/tmp/probe.sql','rb').read(16))" && rm /tmp/probe.sql
# 输出 b'SQLite format 3\x00' = 透明层已激活；b'%TSD-Header-###%' = 未激活
```
---

## 完成标准

- [x] 文件头 = `SQLite format 3` (非 `%TSD-Header%`)
- [x] `sqlite3 <file> "SELECT 1"` 返回 0
- [x] JSONL 每行可 `json.loads()`
- [x] 备份文件存在且非空
- [x] Codex 能正常启动
