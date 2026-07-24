---
name: decrypt-materialize
description: 将加密或二进制包装的本地数据物化为可读文本或暂存 CSV。跨平台支持。仅用户调用。
disable-model-invocation: true
---

# decrypt-materialize

将不透明文件转为可读文件，不做业务规范化或下游质检。**支持 macOS、Linux、Windows**。

**四个分支**：
- **工作簿物化** — .numbers / .xlsx / .xls / .ods → 暂存 CSV（每个工作表一个文件）
- **Smudged 文本访问** — Read 工具显示乱码的文本文件 → 直接访问磁盘明文
- **Codex TSD 解密** — 解密 Codex 的 TSD 加密数据库文件（.sqlite / .jsonl）
- **加密文件扫描** — 全系统扫描识别加密文件（TSD / GPG / Age / OpenSSL 等）

**不在范围**：列重命名、类型强制转换、业务规则检查、关系验证、聚合质检。

**引用**：
- `references/CROSSPLATFORM.md` — 跨平台支持（Windows/Linux/macOS）
- `references/WORKBOOK_PROCESS.md` — 工作簿物化详细流程
- `references/SMUDGED_TEXT.md` — Smudged 文本处理
- `references/CODEX_TSD.md` — Codex TSD 解密流程
- `references/OUTPUT_CONTRACT.md` — 输出规范
- `references/EXAMPLES.md` — 使用示例
- `references/TESTING.md` — 测试和验证

---

## 分支 1: 工作簿物化

### 环境要求

脚本需要 `openpyxl` 依赖。**项目用 uv 时，在项目根目录运行**：

```bash
cd <project_root>
uv add openpyxl
<project_root>/.venv/bin/python ~/.claude/skills/decrypt-materialize/scripts/materialize.py <source> [options]
```

如果项目用其他包管理器：
- **poetry**: `poetry add openpyxl && poetry run python ...`
- **venv**: 激活虚拟环境后 `pip install openpyxl && python ...`
- **系统 Python（不推荐）**: `python3 -m pip install --user openpyxl`

### 统一入口

```bash
python3 scripts/materialize.py <source> [--output-dir DIR] [--date-tag YYYYMMDD]
```

脚本自动检测格式（.numbers / .xlsx / .xls / .ods）和加密状态。

### 输出目录规则

**不指定 `--output-dir` 时**，按优先级选择：
1. `../02_working_data/`（存在则用）
2. `./decrypted/`（存在则用）
3. `.`（当前目录）

**指定 `--output-dir` 时**，该目录必须已存在，否则报错。**脚本不会自动创建目录**。

### 执行流程

见 `references/WORKBOOK_PROCESS.md` 了解：
- 加密检测逻辑
- 结构检查步骤
- 命名规范
- 验证标准

**完成标准**：每个目标工作表导出为符合 `OUTPUT_CONTRACT.md` 的 CSV，或明确报告阻塞原因。

---

## 分支 2: Smudged 文本访问

**识别**：Read 工具返回乱码，但扩展名是 `.yaml` / `.yml` / `.toml` / `.json` / `.ini` / `.conf` / `.env` / `.properties`。

**处理**：
1. 绕过 Read 工具，用 shell 或 python 直接访问磁盘文件
2. 编辑时修改明文，git-clean 自动重新加密
3. 不发明解密路径 — smudge 过滤器已处理

见 `references/SMUDGED_TEXT.md` 了解详细操作。

**完成标准**：所需内容被访问/编辑，无需触碰加密字节。

---

## 分支 3: Codex TSD 解密

**识别**：文件头包含 `%TSD-Header-###%`，任意位置的文件都可能加密。

**TSD 透明层机制**：
- 按扩展名激活（`.sqlite` / `.sql` / `.xls` / `.jsonl` / `.toml` 等），不限路径
- 不透明扩展名（如 `.md`）需重命名为支持的扩展名后 Python 读取自动解密
- 批量脚本默认扫描 `~/.codex`（macOS/Linux）或 `%USERPROFILE%\.codex`（Windows），但单文件解密不受路径限制

**处理方式**：

**单文件快速解密**（任意路径）：
```python
# 不透明扩展名（如 .md）：重命名激活透明层
from pathlib import Path
src = Path('encrypted.md')
temp = src.with_suffix('.sql')  # 重命名为透明扩展名
temp.write_bytes(src.read_bytes())
content = temp.read_text()  # 自动解密
Path('decrypted.md').write_text(content)
temp.unlink()
```

**批量解密** `~/.codex` 目录：
1. 检查 Codex 进程：`pgrep -fl codex`（完整命令行，避免截断）
2. 自动备份原文件（带时间戳）
3. 用 Python sqlite3/文件 API 透明读取并写入未加密副本
4. 可选择仅解密到 `decrypted/` 或替换原文件

**跨平台批量脚本**：
```bash
# 自动检测平台并使用相应命令（默认扫描 ~/.codex）
python3 scripts/decrypt_codex_crossplatform.py ~/.codex --stop-daemon
```

见 `references/CODEX_TSD.md` 了解详细操作（含透明层机制说明），`references/CROSSPLATFORM.md` 了解平台差异。

**完成标准**：加密文件被解密为标准格式，批量操作时原文件已备份。

---

## 分支 4: 加密文件扫描

**目的**：快速发现系统中的加密文件，识别类型，提供解密建议。

**使用**（跨平台）：
```bash
# 扫描默认目录（自动适配 Windows/macOS/Linux）
python3 scripts/scan_encrypted.py

# 扫描特定目录
python3 scripts/scan_encrypted.py ~/work ~/Documents

# JSON 输出
python3 scripts/scan_encrypted.py --json
```

**识别类型**：TSD / GPG / Age / OpenSSL AES / Ansible Vault / LUKS

**平台适配**：
- macOS/Linux: 使用 `find` 命令
- Windows: 使用 Python `os.walk()`
- 自动检测默认扫描目录

见 `references/CROSSPLATFORM.md` 了解平台差异，`scripts/scan_encrypted.py` 查看实现。

**完成标准**：列出所有加密文件，按类型分组，提供对应解密方法。
