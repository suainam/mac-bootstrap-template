#!/usr/bin/env python3
"""Materialize one TSD-wrapped binary file without changing its payload.

The source is inspected with a system reader, copied to a ``.sql`` staging
path so the TSD transparent layer can decrypt it, then streamed to an atomic
output.  The encrypted source is never replaced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path
from typing import BinaryIO

TSD_MARKER = b"TSD-Header"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
COPY_CHUNK_SIZE = 1024 * 1024
DEFAULT_STAGE_SUFFIX = ".sql"


class MaterializeError(RuntimeError):
    """Raised when a file cannot be safely materialized."""


def _raw_prefix(path: Path, size: int = 64) -> bytes:
    """Read raw on-disk bytes, bypassing the transparent Python layer."""
    if os.name != "nt":
        dd = shutil.which("dd")
        if dd:
            result = subprocess.run(
                [dd, f"if={path}", f"bs={size}", "count=1", "status=none"],
                capture_output=True,
                check=False,
            )
            if result.returncode != 0:
                detail = result.stderr.decode(errors="replace").strip()
                raise MaterializeError(f"无法读取源文件原始字节: {detail}")
            return result.stdout

    try:
        with path.open("rb") as handle:
            return handle.read(size)
    except OSError as exc:
        raise MaterializeError(f"无法读取文件头: {path}: {exc}") from exc


def is_tsd_encrypted(path: Path) -> bool:
    """Return whether raw file bytes contain the TSD header marker."""
    return TSD_MARKER in _raw_prefix(path)


def _copy_raw(source: Path, stage: Path) -> None:
    """Copy ciphertext without routing the source through Python I/O."""
    if os.name != "nt":
        cp = shutil.which("cp")
        if cp:
            result = subprocess.run(
                [cp, str(source), str(stage)],
                capture_output=True,
                check=False,
            )
            if result.returncode != 0:
                detail = result.stderr.decode(errors="replace").strip()
                raise MaterializeError(f"暂存密文失败: {detail}")
            return

    try:
        shutil.copyfile(source, stage)
    except OSError as exc:
        raise MaterializeError(f"暂存密文失败: {exc}") from exc


def _default_output_path(source: Path) -> Path:
    """Return ``name.decrypted`` before all original suffixes."""
    suffix = "".join(source.suffixes)
    stem = source.name[:-len(suffix)] if suffix else source.name
    return source.with_name(f"{stem}.decrypted{suffix}")


def _normalize_output(source: Path, output: Path | None, force: bool) -> Path:
    source = source.expanduser()
    if not source.is_file():
        raise MaterializeError(f"源文件不存在或不是普通文件: {source}")
    source = source.resolve()

    target = _default_output_path(source) if output is None else output.expanduser()
    target = target.resolve()
    if target == source:
        raise MaterializeError("输出路径不能覆盖加密源文件")
    if not target.parent.is_dir():
        raise MaterializeError(f"输出目录不存在: {target.parent}")
    if target.exists() and not force:
        raise MaterializeError(f"输出文件已存在；如需覆盖请指定 --force: {target}")
    return target


def _new_temp_path(directory: Path, prefix: str, suffix: str) -> Path:
    fd, name = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=directory)
    os.close(fd)
    return Path(name)


def _stream_decrypted(stage: Path, temporary_output: Path) -> tuple[int, str, bytes]:
    """Read the transparent stage and stream it to a temporary output."""
    digest = hashlib.sha256()
    total = 0
    first_bytes = bytearray()

    try:
        with stage.open("rb") as source, temporary_output.open("wb") as target:
            while chunk := source.read(COPY_CHUNK_SIZE):
                if len(first_bytes) < 64:
                    first_bytes.extend(chunk[: 64 - len(first_bytes)])
                target.write(chunk)
                digest.update(chunk)
                total += len(chunk)
    except OSError as exc:
        raise MaterializeError(f"读取透明暂存文件失败: {stage}: {exc}") from exc

    if total == 0:
        raise MaterializeError("透明读取得到空文件，拒绝生成输出")
    if TSD_MARKER in first_bytes:
        raise MaterializeError(
            "暂存文件仍返回 TSD 包装头；透明层未生效，未生成输出"
        )
    return total, digest.hexdigest(), bytes(first_bytes)


def _read_exact(handle: BinaryIO, size: int, context: str) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise MaterializeError(f"PNG {context} 截断")
    return data


def _validate_png(path: Path) -> dict[str, object]:
    """Validate PNG chunk boundaries, CRCs, dimensions, and IEND placement."""
    with path.open("rb") as handle:
        if _read_exact(handle, 8, "签名") != PNG_SIGNATURE:
            raise MaterializeError("输出不是标准 PNG")

        chunk_count = 0
        idat_count = 0
        ihdr: tuple[int, int, int, int, int, int, int] | None = None
        saw_iend = False

        while True:
            header = handle.read(8)
            if not header:
                break
            if len(header) != 8:
                raise MaterializeError("PNG chunk 头部截断")
            length = struct.unpack(">I", header[:4])[0]
            chunk_type = header[4:]
            if chunk_count == 0 and chunk_type != b"IHDR":
                raise MaterializeError("PNG 第一个 chunk 不是 IHDR")
            if chunk_type == b"IHDR" and ihdr is not None:
                raise MaterializeError("PNG 包含多个 IHDR")

            crc = zlib.crc32(chunk_type)
            if chunk_type == b"IHDR":
                if length != 13:
                    raise MaterializeError(f"PNG IHDR 长度错误: {length}")
                payload = _read_exact(handle, length, "IHDR")
                crc = zlib.crc32(payload, crc)
                ihdr = struct.unpack(">IIBBBBB", payload)
                if ihdr[0] == 0 or ihdr[1] == 0:
                    raise MaterializeError("PNG 尺寸不能为 0")
            else:
                remaining = length
                while remaining:
                    block = _read_exact(
                        handle, min(remaining, COPY_CHUNK_SIZE), chunk_type.decode("latin1")
                    )
                    crc = zlib.crc32(block, crc)
                    remaining -= len(block)

            stored_crc = struct.unpack(">I", _read_exact(handle, 4, "CRC"))[0]
            if stored_crc != (crc & 0xFFFFFFFF):
                name = chunk_type.decode("latin1", errors="replace")
                raise MaterializeError(f"PNG {name} CRC 校验失败")

            chunk_count += 1
            if chunk_type == b"IDAT":
                idat_count += 1
            if chunk_type == b"IEND":
                if length != 0:
                    raise MaterializeError("PNG IEND 长度错误")
                saw_iend = True
                if handle.read(1):
                    raise MaterializeError("PNG IEND 后存在额外数据")
                break

        if ihdr is None or not saw_iend:
            raise MaterializeError("PNG 缺少 IHDR 或 IEND")
        if idat_count == 0:
            raise MaterializeError("PNG 缺少 IDAT")

    return {
        "format": "png",
        "width": ihdr[0],
        "height": ihdr[1],
        "bit_depth": ihdr[2],
        "color_type": ihdr[3],
        "chunks": chunk_count,
        "idat_chunks": idat_count,
    }


def _validate_with_sips(path: Path) -> dict[str, str]:
    """Ask macOS ImageIO to parse the materialized PNG."""
    if platform.system().lower() != "darwin":
        return {"preview_check": "skipped_non_macos"}
    sips = shutil.which("sips")
    if not sips:
        raise MaterializeError("macOS 未找到 sips，无法完成 PNG 预览校验")

    result = subprocess.run(
        [sips, "-g", "format", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise MaterializeError(f"sips PNG 校验失败: {detail}")

    fields: dict[str, str] = {"preview_check": "sips"}
    for line in result.stdout.splitlines():
        key, separator, value = line.strip().partition(":")
        if separator:
            fields[key] = value.strip()
    return fields


def _validate_output(path: Path) -> dict[str, object]:
    first_bytes = _raw_prefix(path, 16)
    if TSD_MARKER in first_bytes:
        raise MaterializeError("输出仍包含 TSD 包装头")

    details: dict[str, object] = {"header": first_bytes[:16].hex()}
    if path.suffix.lower() == ".png":
        details.update(_validate_png(path))
        details.update(_validate_with_sips(path))
    else:
        details["format_check"] = "header_not_tsd"
    return details


def materialize_tsd_file(
    source: Path,
    output: Path | None = None,
    *,
    force: bool = False,
    stage_suffix: str = DEFAULT_STAGE_SUFFIX,
) -> dict[str, object]:
    source = source.expanduser().resolve()
    target = _normalize_output(source, output, force)
    source_size = source.stat().st_size
    if not is_tsd_encrypted(source):
        raise MaterializeError(f"源文件不是 TSD 包装文件: {source}")

    stage = _new_temp_path(
        source.parent,
        prefix=f".{source.name}.stage-",
        suffix=stage_suffix if stage_suffix.startswith(".") else f".{stage_suffix}",
    )
    temporary_output = _new_temp_path(
        target.parent,
        prefix=f".{target.name}.tmp-",
        suffix=target.suffix or ".tmp",
    )

    try:
        _copy_raw(source, stage)
        byte_count, digest, first_bytes = _stream_decrypted(stage, temporary_output)
        verification = _validate_output(temporary_output)

        if source.stat().st_size != source_size or not is_tsd_encrypted(source):
            raise MaterializeError("解密期间源文件发生变化，已拒绝发布输出")

        os.replace(temporary_output, target)
        temporary_output = None  # type: ignore[assignment]
        return {
            "status": "success",
            "source": str(source),
            "output": str(target),
            "bytes": byte_count,
            "sha256": digest,
            "output_header": first_bytes[:16].hex(),
            "verified": True,
            **verification,
        }
    finally:
        stage.unlink(missing_ok=True)
        if temporary_output is not None:
            temporary_output.unlink(missing_ok=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="解密单个 TSD 包装文件，保留原始二进制格式和全部数据"
    )
    parser.add_argument("source", type=Path, help="TSD 加密源文件")
    parser.add_argument(
        "-o", "--output", type=Path, help="输出路径（默认：<源文件名>.decrypted<原扩展名>）"
    )
    parser.add_argument(
        "--force", action="store_true", help="允许覆盖已存在的输出文件；不会覆盖源文件"
    )
    parser.add_argument(
        "--stage-suffix",
        default=DEFAULT_STAGE_SUFFIX,
        help="透明层暂存扩展名（默认：.sql）",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        result = materialize_tsd_file(
            args.source,
            args.output,
            force=args.force,
            stage_suffix=args.stage_suffix,
        )
    except (MaterializeError, OSError) as exc:
        if args.json:
            print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"错误: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"已解密: {result['output']}")
        print(f"大小: {result['bytes']} bytes")
        print(f"SHA-256: {result['sha256']}")
        print("校验: 通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
