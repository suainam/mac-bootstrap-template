#!/usr/bin/env python3
"""全面扫描系统中的加密文件 - 跨平台版本"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


# 精确的加密特征
ENCRYPTION_SIGNATURES = {
    'TSD': b'%TSD-Header-###%',
    'GPG': b'\x85\x01\x0c',  # GPG packet header
    'GPG_ASCII': b'-----BEGIN PGP MESSAGE-----',
    'OpenSSL_AES': b'Salted__',
    'Age': b'age-encryption.org/',
    'Ansible_Vault': b'$ANSIBLE_VAULT;',
    'LUKS': b'LUKS\xba\xbe',  # LUKS header
    'BitLocker': b'-FVE-FS-',
}

# 跳过的扩展名（明显的二进制格式）
SKIP_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.icns',
    '.mp4', '.mov', '.avi', '.mkv', '.mp3', '.m4a', '.wav',
    '.pyc', '.pyo', '.so', '.dylib', '.dll', '.exe',
    '.woff', '.woff2', '.ttf', '.otf', '.eot',
    '.pdf', '.zip', '.tar', '.gz', '.bz2', '.xz', '.7z',
    '.dmg', '.pkg', '.deb', '.rpm',
}

# 默认扫描目录（跨平台）
def get_default_scan_dirs() -> list[str]:
    """获取默认扫描目录（根据平台）"""
    system = platform.system().lower()

    if system == 'windows':
        return [
            os.path.expandvars('%APPDATA%\\.codex'),
            os.path.expandvars('%USERPROFILE%\\Documents'),
            os.path.expandvars('%USERPROFILE%\\Desktop'),
            os.path.expandvars('%USERPROFILE%\\Downloads'),
            os.path.expandvars('%APPDATA%'),
        ]
    else:
        # macOS/Linux
        return [
            '~/.codex',
            '~/.config',
            '~/.ssh',
            '~/.gnupg',
            '~/Documents',
            '~/Desktop',
            '~/Downloads',
        ]


def check_encryption(path: Path) -> tuple[bool, str]:
    """检测文件是否加密"""
    # 跳过明显的二进制格式
    if path.suffix.lower() in SKIP_EXTENSIONS:
        return False, ''

    # 跳过过大的文件（> 100MB）
    try:
        if path.stat().st_size > 100 * 1024 * 1024:
            return False, ''
    except:
        return False, ''

    try:
        with path.open('rb') as f:
            header = f.read(256)

        for enc_type, sig in ENCRYPTION_SIGNATURES.items():
            if header.startswith(sig) or sig in header[:128]:
                return True, enc_type

        return False, ''
    except:
        return False, ''


def scan_directory(directory: Path, recursive: bool = True, max_depth: int = 5) -> dict:
    """扫描目录寻找加密文件（跨平台）"""
    results = defaultdict(list)
    scanned = 0
    system = platform.system().lower()

    try:
        if system == 'windows':
            # Windows: 使用 Python 递归遍历
            if recursive:
                for root, dirs, files in os.walk(directory):
                    depth = root[len(str(directory)):].count(os.sep)
                    if max_depth and depth >= max_depth:
                        dirs.clear()
                        continue

                    for filename in files:
                        fpath = Path(root) / filename
                        try:
                            size = fpath.stat().st_size
                            if size < 1024 or size > 100 * 1024 * 1024:
                                continue

                            scanned += 1
                            is_encrypted, enc_type = check_encryption(fpath)
                            if is_encrypted:
                                results[enc_type].append(fpath)
                        except:
                            pass
            else:
                for fpath in directory.iterdir():
                    if fpath.is_file():
                        try:
                            size = fpath.stat().st_size
                            if size < 1024 or size > 100 * 1024 * 1024:
                                continue

                            scanned += 1
                            is_encrypted, enc_type = check_encryption(fpath)
                            if is_encrypted:
                                results[enc_type].append(fpath)
                        except:
                            pass
        else:
            # macOS/Linux: 使用 find 命令
            if recursive:
                cmd = ['find', str(directory), '-type', 'f', '-size', '+1k', '-size', '-100M']
                if max_depth:
                    cmd.extend(['-maxdepth', str(max_depth)])
            else:
                cmd = ['find', str(directory), '-maxdepth', '1', '-type', 'f', '-size', '+1k']

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            files = [Path(f) for f in result.stdout.strip().split('\n') if f]

            for fpath in files:
                scanned += 1
                is_encrypted, enc_type = check_encryption(fpath)
                if is_encrypted:
                    results[enc_type].append(fpath)

    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass

    return {'results': dict(results), 'scanned': scanned}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="扫描系统中的加密文件"
    )
    parser.add_argument(
        'directories',
        nargs='*',
        type=Path,
        help='要扫描的目录（默认：常见目录）'
    )
    parser.add_argument(
        '--recursive',
        action='store_true',
        default=True,
        help='递归扫描子目录'
    )
    parser.add_argument(
        '--max-depth',
        type=int,
        default=5,
        help='最大递归深度（默认：5）'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='输出 JSON 格式'
    )

    args = parser.parse_args()

    # 确定扫描目录
    if args.directories:
        scan_dirs = [d.expanduser().resolve() for d in args.directories]
    else:
        scan_dirs = [Path(d).expanduser() for d in get_default_scan_dirs()]
        scan_dirs = [d for d in scan_dirs if d.exists()]

    if not args.json:
        print("扫描加密文件...")
        print("=" * 70)

    all_results = defaultdict(list)
    total_scanned = 0

    for directory in scan_dirs:
        if not args.json:
            print(f"\n扫描: {directory}")

        scan_result = scan_directory(directory, args.recursive, args.max_depth)
        total_scanned += scan_result['scanned']

        for enc_type, files in scan_result['results'].items():
            all_results[enc_type].extend(files)
            if not args.json:
                for f in files:
                    try:
                        rel = f.relative_to(Path.home())
                        print(f"  ✓ [{enc_type}] ~/{rel}")
                    except:
                        print(f"  ✓ [{enc_type}] {f}")

    # 输出结果
    if args.json:
        output = {
            'total_scanned': total_scanned,
            'total_encrypted': sum(len(v) for v in all_results.values()),
            'by_type': {}
        }

        for enc_type, files in all_results.items():
            output['by_type'][enc_type] = {
                'count': len(files),
                'files': [str(f) for f in files]
            }

        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print("\n" + "=" * 70)
        print(f"扫描完成: {total_scanned} 个文件")

        if all_results:
            total_encrypted = sum(len(v) for v in all_results.values())
            print(f"发现 {total_encrypted} 个加密文件\n")

            # 按类型统计
            for enc_type, files in sorted(all_results.items()):
                print(f"{enc_type} ({len(files)} 个):")

                # 按扩展名分组
                by_ext = defaultdict(int)
                for f in files:
                    by_ext[f.suffix or '(无扩展名)'] += 1

                for ext, count in sorted(by_ext.items(), key=lambda x: -x[1])[:5]:
                    print(f"  {ext}: {count} 个")
                print()

            # 解密建议
            print("解密方法:")
            if 'TSD' in all_results:
                print("  TSD: python3 scripts/decrypt_codex.py ~/.codex --stop-daemon")
            if 'GPG' in all_results or 'GPG_ASCII' in all_results:
                print("  GPG: gpg -d <file> -o <output>")
            if 'OpenSSL_AES' in all_results:
                print("  OpenSSL: openssl enc -d -aes-256-cbc -in <file> -out <output>")
            if 'Age' in all_results:
                print("  Age: age -d -i ~/.ssh/id_ed25519 <file> > <output>")
            if 'Ansible_Vault' in all_results:
                print("  Ansible: ansible-vault decrypt <file>")
        else:
            print("未发现加密文件")

    return 0


if __name__ == "__main__":
    sys.exit(main())
