#!/usr/bin/env python3
"""解密 Codex TSD 加密的数据库文件 - 跨平台版本"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def get_platform() -> str:
    """获取平台类型"""
    system = platform.system().lower()
    if system == 'darwin':
        return 'macos'
    elif system == 'windows':
        return 'windows'
    elif system == 'linux':
        return 'linux'
    return 'unknown'


def get_codex_dir() -> Path:
    """获取 Codex 配置目录（跨平台）"""
    system = get_platform()

    if system == 'windows':
        # Windows: %APPDATA%\.codex
        appdata = Path(os.environ.get('APPDATA', ''))
        if appdata:
            return appdata / '.codex'
        return Path.home() / 'AppData/Roaming/.codex'
    else:
        # macOS/Linux: ~/.codex
        return Path.home() / '.codex'


def check_codex_running() -> tuple[list[int], list[str]]:
    """检查 Codex 进程是否在运行（跨平台）"""
    system = get_platform()

    try:
        if system == 'windows':
            # Windows: tasklist | findstr codex
            result = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq codex*'],
                capture_output=True,
                text=True,
                check=False
            )
            pids = []
            names = []
            for line in result.stdout.strip().split('\n'):
                if 'codex' in line.lower():
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            names.append(parts[0])
                            pids.append(int(parts[1]))
                        except ValueError:
                            pass
            return pids, names

        else:
            # macOS/Linux: pgrep
            result = subprocess.run(
                ["pgrep", "-il", "codex"],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0:
                pids = []
                names = []
                for line in result.stdout.strip().split('\n'):
                    if line:
                        parts = line.split(maxsplit=1)
                        if len(parts) == 2:
                            pids.append(int(parts[0]))
                            names.append(parts[1])
                return pids, names
            return [], []

    except Exception:
        return [], []


def stop_codex_daemon() -> bool:
    """停止 Codex 守护进程（跨平台）"""
    system = get_platform()

    try:
        if system == 'windows':
            # Windows: 没有守护进程机制，直接返回
            return True

        elif system == 'macos':
            # macOS: launchctl
            launch_agent = Path.home() / "Library/LaunchAgents/dev.wangnov.codex-threadripper.plist"
            if launch_agent.exists():
                subprocess.run(["launchctl", "unload", str(launch_agent)], check=True)
            return True

        else:
            # Linux: systemctl
            result = subprocess.run(
                ["systemctl", "--user", "is-active", "codex"],
                capture_output=True,
                check=False
            )
            if result.returncode == 0:
                subprocess.run(["systemctl", "--user", "stop", "codex"], check=True)
            return True

    except Exception:
        return False


def kill_process(pid: int) -> bool:
    """杀掉进程（跨平台）"""
    system = get_platform()

    try:
        if system == 'windows':
            subprocess.run(['taskkill', '/F', '/PID', str(pid)], check=True)
        else:
            subprocess.run(['kill', str(pid)], check=True)
        return True
    except:
        return False


def is_tsd_encrypted(path: Path) -> bool:
    """检查文件是否为 TSD 加密格式"""
    try:
        with path.open('rb') as f:
            header = f.read(16)
            return b'TSD-Header' in header
    except Exception:
        return False


def decrypt_sqlite(src: Path, dst: Path) -> dict:
    """解密 SQLite 数据库"""
    try:
        src_conn = sqlite3.connect(str(src))
        dst_conn = sqlite3.connect(str(dst))
        src_conn.backup(dst_conn)

        # 获取表信息
        cursor = dst_conn.cursor()
        cursor.execute("SELECT name, type FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()

        src_conn.close()
        dst_conn.close()

        # 验证文件头
        with dst.open('rb') as f:
            header = f.read(16)
            is_standard = header.startswith(b'SQLite format 3')

        return {
            "status": "success",
            "tables": len(tables),
            "table_names": [t[0] for t in tables],
            "verified_header": is_standard
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


def decrypt_jsonl(src: Path, dst: Path) -> dict:
    """解密 JSONL 文件"""
    try:
        with src.open('r', encoding='utf-8') as f:
            lines = f.readlines()

        with dst.open('w', encoding='utf-8') as f:
            f.writelines(lines)

        # 验证第一行是否为有效 JSON
        valid = False
        if lines:
            try:
                json.loads(lines[0])
                valid = True
            except:
                pass

        return {
            "status": "success",
            "lines": len(lines),
            "valid_json": valid
        }
    except UnicodeDecodeError:
        return {
            "status": "error",
            "error": "Binary encrypted, needs special decryption tool"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


def backup_file(src: Path, backup_dir: Path) -> Path:
    """备份文件，返回备份路径"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{src.name}.backup_{timestamp}"
    shutil.copy2(src, backup_path)
    return backup_path


def main() -> int:
    import os  # 移到这里避免全局导入

    parser = argparse.ArgumentParser(
        description="解密 Codex TSD 加密的数据库文件（跨平台）"
    )
    parser.add_argument(
        "codex_dir",
        nargs='?',
        type=Path,
        help="Codex 配置目录路径（默认：自动检测）"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="即使 Codex 在运行也强制解密（危险）"
    )
    parser.add_argument(
        "--no-replace",
        action="store_true",
        help="只解密到 decrypted/ 子目录，不替换原文件"
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        help="备份目录（默认：codex_dir/backups）"
    )
    parser.add_argument(
        "--stop-daemon",
        action="store_true",
        help="自动停止 Codex 守护进程"
    )

    args = parser.parse_args()

    # 确定 Codex 目录
    if args.codex_dir:
        codex_dir = args.codex_dir.expanduser().resolve()
    else:
        codex_dir = get_codex_dir()
        print(f"使用默认 Codex 目录: {codex_dir}")

    # 验证目录
    if not codex_dir.exists():
        print(f"错误: 目录不存在: {codex_dir}", file=sys.stderr)
        return 1

    # 检查 Codex 是否在运行
    pids, names = check_codex_running()
    if pids and not args.force:
        print(f"错误: Codex 进程仍在运行:", file=sys.stderr)
        for pid, name in zip(pids, names):
            print(f"  PID {pid}: {name}", file=sys.stderr)

        if args.stop_daemon:
            print("\n尝试停止守护进程...", file=sys.stderr)
            if stop_codex_daemon():
                print("已停止守护服务，等待进程退出...", file=sys.stderr)
                time.sleep(2)

                # 强制杀掉残留进程
                for pid in pids:
                    kill_process(pid)

                time.sleep(1)

                # 再次检查
                pids, names = check_codex_running()
                if pids:
                    print(f"警告: 仍有进程运行 {pids}", file=sys.stderr)
                    print("请手动退出 Codex 或使用 --force", file=sys.stderr)
                    return 1
                print("✓ 所有进程已停止\n")
            else:
                print("无法停止守护进程", file=sys.stderr)
                return 1
        else:
            print("提示: 使用 --stop-daemon 自动停止，或使用 --force 强制执行", file=sys.stderr)
            return 1

    if pids and args.force:
        print(f"警告: Codex 进程仍在运行 (PIDs: {pids})，强制执行中...")

    # 设置目录
    decrypted_dir = codex_dir / "decrypted"
    decrypted_dir.mkdir(exist_ok=True)

    backup_dir = args.backup_dir or (codex_dir / "backups")
    backup_dir.mkdir(parents=True, exist_ok=True)

    # 已知的可能被加密的文件
    known_files = [
        "goals_1.sqlite",
        "logs_2.sqlite",
        "memories_1.sqlite",
        "state_5.sqlite",
        "session_index.jsonl",
        "history.jsonl",
        "transcription-history.jsonl",
    ]

    # 查找加密文件
    encrypted_files = []
    for filename in known_files:
        path = codex_dir / filename
        if path.is_file() and is_tsd_encrypted(path):
            encrypted_files.append(path)

    if not encrypted_files:
        print("未找到 TSD 加密文件")
        return 0

    print(f"找到 {len(encrypted_files)} 个加密文件")

    # 解密文件
    results = []
    for src in encrypted_files:
        print(f"\n处理: {src.name}")

        dst = decrypted_dir / src.name

        # 解密
        if src.suffix == '.sqlite':
            result = decrypt_sqlite(src, dst)
        elif src.suffix == '.jsonl':
            result = decrypt_jsonl(src, dst)
        else:
            result = {"status": "error", "error": "Unsupported file type"}

        result["file"] = src.name
        result["decrypted_path"] = str(dst)

        if result["status"] == "success":
            print(f"  ✓ 已解密到: {dst}")

            # 替换原文件
            if not args.no_replace:
                backup_path = backup_file(src, backup_dir)
                print(f"  ✓ 已备份到: {backup_path}")

                shutil.copy2(dst, src)
                print(f"  ✓ 已替换原文件")
                result["replaced"] = True
                result["backup_path"] = str(backup_path)
        else:
            print(f"  ✗ 失败: {result['error']}")

        results.append(result)

    # 输出摘要
    print("\n" + "="*60)
    print("解密摘要:")
    success_count = sum(1 for r in results if r["status"] == "success")
    print(f"  成功: {success_count}/{len(results)}")
    print(f"  平台: {get_platform()}")

    if not args.no_replace:
        print(f"  备份目录: {backup_dir}")
    print(f"  解密目录: {decrypted_dir}")

    # 输出 JSON 结果
    print("\n详细结果:")
    print(json.dumps(results, ensure_ascii=False, indent=2))

    return 0 if success_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
