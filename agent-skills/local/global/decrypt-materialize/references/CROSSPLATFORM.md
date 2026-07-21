# 跨平台支持指南

decrypt-materialize 技能已支持跨平台：macOS、Linux、Windows。

---

## 平台差异

### Codex 配置目录

| 平台 | 默认路径 |
|------|----------|
| macOS | `~/.codex` |
| Linux | `~/.codex` |
| Windows | `%USERPROFILE%\.codex` |

### 进程管理

| 平台 | 检查进程 | 杀进程 | 守护进程 |
|------|----------|--------|----------|
| macOS | `pgrep -ifl codex` | 用户手动退出 | `launchctl unload` |
| Linux | `pgrep -ifl codex` | 用户手动退出 | `systemctl --user stop codex` |
| Windows | `tasklist /FI "IMAGENAME eq codex*"` | 用户手动退出 | 无守护机制 |

### 文件扫描

| 平台 | 方法 |
|------|------|
| macOS/Linux | `find` 命令 |
| Windows | Python `os.walk()` |

---

## 使用方法

### 跨平台解密脚本

```bash
# macOS/Linux
python3 scripts/decrypt_codex_crossplatform.py

# Windows
python scripts/decrypt_codex_crossplatform.py
```

**自动检测**：
- 自动识别操作系统
- 自动找到 Codex 配置目录
- 使用平台相应的进程管理命令

### 跨平台扫描

```bash
# 使用默认目录（自动适配平台）
python3 scripts/scan_encrypted.py

# Windows 特定目录
python scripts/scan_encrypted.py "%USERPROFILE%\Documents"

# macOS/Linux
python3 scripts/scan_encrypted.py ~/Documents
```

---

## 平台特定注意事项

### Windows

**路径分隔符**：
- 使用 `Path()` 对象自动处理
- 或使用 `os.path.join()` 而非手动拼接

**权限**：
- 可能需要管理员权限运行
- UAC 可能会弹窗确认

**进程管理**：
- 没有 systemd/launchd 守护进程
- 进程退出后不会自动重启
- `--stop-daemon` 选项在 Windows 上无操作；仍有前台进程时安全退出

**编码**：
- 默认使用 UTF-8
- 如遇编码问题，设置 `PYTHONIOENCODING=utf-8`

### macOS

**守护进程**：
- 使用 launchd 管理
- 位置：`~/Library/LaunchAgents/dev.wangnov.codex-threadripper.plist`
- 需要 `--stop-daemon` 选项停止自动重启

**权限**：
- 可能需要"完全磁盘访问"权限
- 系统偏好设置 → 安全性与隐私 → 完全磁盘访问

**命令行工具**：
- 需要安装 Xcode Command Line Tools
- `xcode-select --install`

### Linux

**守护进程**：
- 使用 systemd（用户服务）
- 检查：`systemctl --user status codex`
- 停止：`systemctl --user stop codex`

**权限**：
- 通常不需要 root
- 扫描系统目录可能需要 sudo

**依赖**：
- 需要 `pgrep` 命令（procps 包）
- 需要 `find` 命令（findutils 包）

---

## 兼容性测试

### 已测试平台

| 平台 | 版本 | 状态 |
|------|------|------|
| macOS | 14.x (Sonoma) | ✓ 完全支持 |
| Linux | Ubuntu 22.04+ | ✓ 理论支持 |
| Windows | 10/11 | ✓ 理论支持 |

### 功能支持矩阵

| 功能 | macOS | Linux | Windows |
|------|-------|-------|---------|
| TSD 解密 | ✓ | ✓ | ✓ |
| 进程检测 | ✓ | ✓ | ✓ |
| 守护进程停止 | ✓ | ✓ | N/A |
| 加密扫描 | ✓ | ✓ | ✓ |
| 工作簿物化 | ✓ | ✓ | ✓ |

---

## 故障排查

### Windows 特定问题

**问题**：`tasklist` 命令不存在
**解决**：确保在 CMD 或 PowerShell 中运行，不是 Git Bash

**问题**：路径中的反斜杠报错
**解决**：使用原始字符串 `r"C:\path"` 或正斜杠 `"C:/path"`

**问题**：权限拒绝
**解决**：以管理员身份运行命令提示符

### Linux 特定问题

**问题**：`pgrep` 命令不存在
**解决**：安装 procps `sudo apt install procps`

**问题**：systemd 服务不存在
**解决**：Codex 可能未配置为 systemd 服务，跳过 `--stop-daemon`

### 通用问题

**问题**：Python 版本太旧
**解决**：需要 Python 3.9+（类型提示语法）

**问题**：`uv` 命令不存在（macOS）
**解决**：直接用 `python3` 替代 `uv run python`

---

## 代码示例

### 检测平台并设置路径

```python
import platform
from pathlib import Path

system = platform.system().lower()

if system == 'windows':
    codex_dir = Path.home() / 'AppData/Roaming/.codex'
else:
    codex_dir = Path.home() / '.codex'

print(f"Platform: {system}")
print(f"Codex dir: {codex_dir}")
```

### 跨平台进程检测

```python
import subprocess
import platform

def check_process(name: str) -> bool:
    system = platform.system().lower()

    if system == 'windows':
        result = subprocess.run(
            ['tasklist', '/FI', f'IMAGENAME eq {name}*'],
            capture_output=True
        )
        return name in result.stdout.decode().lower()
    else:
        result = subprocess.run(
            ['pgrep', '-i', name],
            capture_output=True
        )
        return result.returncode == 0

if check_process('codex'):
    print("Codex is running")
```

---

## 部署建议

### Python 环境

**推荐**：使用虚拟环境
```bash
# macOS/Linux
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

### 依赖安装

```bash
pip install openpyxl xlrd numbers-parser
```

### 配置文件

创建 `config.json` 支持自定义路径：
```json
{
  "codex_dir": "~/.codex",
  "backup_dir": "~/backups",
  "max_depth": 5
}
```

---

## 已知限制

1. **Windows 守护进程**：无法自动停止（Windows 无 launchd/systemd）
2. **路径长度**：Windows 旧版本有 260 字符限制
3. **符号链接**：Windows 需要管理员权限创建
4. **文件权限**：Unix 权限模型不适用于 Windows

---

## 贡献平台支持

如需添加其他平台支持（如 FreeBSD、WSL）：

1. 在 `get_platform()` 中添加平台检测
2. 在 `check_codex_running()` 中添加进程检测逻辑
3. 在 `stop_codex_daemon()` 中添加守护进程管理
4. 更新测试矩阵
5. 提交 PR 并注明测试环境

---

## 快速开始

```bash
# 1. 克隆仓库（或复制脚本）
git clone <repo>

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行扫描
python scripts/scan_encrypted.py

# 4. 如发现 TSD 加密，运行解密
python scripts/decrypt_codex_crossplatform.py [codex_dir]
```

全平台通用，自动适配！
