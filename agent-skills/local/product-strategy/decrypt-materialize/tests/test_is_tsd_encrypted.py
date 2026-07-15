#!/usr/bin/env python3
"""测试 is_tsd_encrypted 函数"""

import sys
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from decrypt_codex_crossplatform import is_tsd_encrypted


def test_detects_tsd_encrypted_file():
    """应该检测到 TSD 加密文件"""
    encrypted = Path.home() / ".codex/db-backups/sqlite-1783755712-0/state_5.sqlite"
    assert encrypted.exists(), f"Test file not found: {encrypted}"

    result = is_tsd_encrypted(encrypted)
    assert result is True, f"Expected True for TSD encrypted file, got {result}"


def test_detects_plaintext_file():
    """应该识别明文文件"""
    plaintext = Path.home() / ".codex/logs_2.sqlite"
    assert plaintext.exists(), f"Test file not found: {plaintext}"

    result = is_tsd_encrypted(plaintext)
    assert result is False, f"Expected False for plaintext file, got {result}"


if __name__ == "__main__":
    print("Running: test_detects_tsd_encrypted_file")
    try:
        test_detects_tsd_encrypted_file()
        print("✓ PASS")
    except AssertionError as e:
        print(f"✗ FAIL: {e}")
        sys.exit(1)

    print("\nRunning: test_detects_plaintext_file")
    try:
        test_detects_plaintext_file()
        print("✓ PASS")
    except AssertionError as e:
        print(f"✗ FAIL: {e}")
        sys.exit(1)

    print("\nAll tests passed!")
