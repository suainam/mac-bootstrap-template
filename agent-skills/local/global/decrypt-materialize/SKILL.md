---
name: decrypt-materialize
description: 将加密或二进制包装的本地数据物化为可读文本、暂存 CSV 或可验证的原始格式副本。跨平台支持。仅用户调用。
disable-model-invocation: true
---

# decrypt-materialize

将不透明文件转为可读文件，不做业务规范化或下游质检。**支持 macOS、Linux、Windows**。

**四个分支**：
- **工作簿物化** — .numbers / .xlsx / .xls / .ods → 暂存 CSV（每个工作表一个文件）
- **Smudged 文本访问** — Read 工具显示乱码的文本文件 → 直接访问磁盘明文
- **Codex TSD 解密** — 任意扩展名（含 `.zip` / `.png`）的 TSD 文件 → 保真原格式副本
- **加密文件扫描** — 全系统扫描识别加密文件（TSD / GPG / Age / OpenSSL 等）

**不在范围**：列重命名、类型强制转换、业务规则检查、关系验证、聚合质检。

**引用**：
- `references/CROSSPLATFORM.md` — 跨平台支持（Windows/Linux/macOS）
- `references/WORKBOOK_PROCESS.md` — 工作簿物化详细流程
- `references/SMUDGED_TEXT.md` — Smudged 文本处理
- `references/CODEX_TSD.md` — Codex TSD 解密流程
- `references/TSD_ATTRIBUTION.md` — TSD 加密来源归因（天锐 OCular DLP）与复发监控
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
- 不透明扩展名（如 `.md`、`.png`、`.zip` 等）需先复制为支持的 `.sql` 扩展名；Python 读取 staging 文件时自动解密
- Python / `pathlib` 读取可能已经看到明文；判断是否加密必须用 `dd` / `xxd` 读取原始磁盘字节
- 归因与行为模型（谁在加密、何时触发、为何时有时无）见 `references/TSD_ATTRIBUTION.md`
- 批量脚本默认扫描 `~/.codex`（macOS/Linux）或 `%USERPROFILE%\.codex`（Windows），但单文件解密不受路径限制

**先判定原始磁盘字节（必须）**：
- macOS/Linux 用 `dd` 或 `xxd` 读取前 16 字节；不要用 Python `open()` / `Path.read_bytes()` 判断是否加密。
- TSD 透明层可能让 Python 直接看到明文 PNG/SQLite，而原始磁盘仍以 `%TSD-Header-###%` 开头。

**二进制文件（PNG、ZIP 等）保真解密**：
1. 用非 Python 工具确认原始头；源文件保持不动。
2. 用 `cp` 将密文复制为支持透明层的扩展名（如 `.sql`）。
3. Python 读取 staging `.sql` 后，写入新的原始扩展名输出文件。
4. 不重编码、不删 PNG metadata/chunk、不生成替代 JSON；要求“保留原数据”时复制完整明文字节流。
5. 验证输出魔数/容器结构和格式专属工具（PNG 可用 `sips` / `qlmanage`），再删除 staging 文件。


**处理方式**：

**单文件快速解密**（任意路径）：
```bash
# 默认输出：<源文件名>.decrypted<原扩展名>
python3 scripts/decrypt_tsd_binary.py encrypted.png

# 指定输出路径；已有输出文件需显式 --force 才会覆盖
python3 scripts/decrypt_tsd_binary.py encrypted.png \
  --output decrypted.png

# 自动返回可供脚本消费的 JSON
python3 scripts/decrypt_tsd_binary.py encrypted.png --json
```

脚本会用系统工具读取原始 TSD 头、创建 `.sql` 暂存副本、流式写入原扩展名输出，并在发布前验证：
- 源文件仍保持 TSD 头且不被覆盖
- 输出不含 TSD 包装头
- PNG 的 chunk 边界、CRC、尺寸和 macOS `sips` 解析结果
- 暂存文件和失败时的临时输出自动清理

低层手工流程仅用于诊断脚本故障；不要把 PNG 重编码、去 metadata 或提取成 JSON/CSV。

保真要求：只改变 TSD 包装层；输出保持原始文件扩展名和完整明文字节，不要把 PNG 转成 JSON/CSV，也不要为了预览删除原文件中的 metadata。
**ZIP 等容器**：先用 `dd` / `xxd` 检查原始头；TSD 包装下 `file` 可能显示 `data`，`unzip` 可能报告缺少 central directory。使用上面的单文件脚本生成 `.decrypted.zip`，再做 ZIP 结构校验；“解密”默认只生成解密文件，不自动解压。完整步骤见 `references/CODEX_TSD.md` 的「ZIP 等容器」。


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
**保真完成标准**：输出文件头变为目标格式的标准魔数；格式结构校验通过；源文件仍保留加密头且未被修改；原始数据块/metadata 全部保留。


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
