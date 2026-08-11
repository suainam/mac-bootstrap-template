"""Regression tests for single-file TSD binary materialization."""

import importlib.util
import struct
import sys
import zlib
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "decrypt_tsd_binary.py"
SPEC = importlib.util.spec_from_file_location("decrypt_tsd_binary", SCRIPT)
assert SPEC and SPEC.loader
binary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(binary)


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _png() -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    scanline = b"\x00\xff\x00\x00\xff"
    return (
        binary.PNG_SIGNATURE
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(scanline))
        + _chunk(b"IEND", b"")
    )


def test_default_output_preserves_all_suffixes(tmp_path: Path):
    source = tmp_path / "certificate.tar.gz"

    assert binary._default_output_path(source) == tmp_path / "certificate.decrypted.tar.gz"


def test_tsd_detection_does_not_execute_filename(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "payload$(touch${IFS}owned).png"
    source.write_bytes(b"%TSD-Header-###%ciphertext")

    assert binary.is_tsd_encrypted(source) is True
    assert not (tmp_path / "owned").exists()


def test_png_validator_checks_container_integrity(tmp_path: Path):
    path = tmp_path / "valid.png"
    path.write_bytes(_png())

    result = binary._validate_png(path)

    assert result["format"] == "png"
    assert result["width"] == 1
    assert result["height"] == 1
    assert result["chunks"] == 3


def test_png_validator_rejects_bad_crc(tmp_path: Path):
    broken = bytearray(_png())
    broken[41] ^= 1
    path = tmp_path / "broken.png"
    path.write_bytes(broken)

    with pytest.raises(binary.MaterializeError, match="CRC"):
        binary._validate_png(path)


def test_materialize_preserves_source_and_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "证书$(touch${IFS}owned).png"
    encrypted = b"%TSD-Header-###%ciphertext"
    plaintext = _png()
    source.write_bytes(encrypted)

    def fake_raw_copy(_source: Path, stage: Path) -> None:
        stage.write_bytes(plaintext)

    monkeypatch.setattr(binary, "_copy_raw", fake_raw_copy)
    monkeypatch.setattr(binary, "_validate_with_sips", lambda _path: {"preview_check": "test"})

    result = binary.materialize_tsd_file(source)
    output = tmp_path / "证书$(touch${IFS}owned).decrypted.png"

    assert result["status"] == "success"
    assert result["verified"] is True
    assert output.read_bytes() == plaintext
    assert source.read_bytes() == encrypted
    assert not (tmp_path / "owned").exists()
    assert not list(tmp_path.glob(".*.stage-*"))
    assert not list(tmp_path.glob(".*.tmp-*"))


def test_materialize_rejects_plaintext_source(tmp_path: Path):
    source = tmp_path / "plain.png"
    source.write_bytes(_png())

    with pytest.raises(binary.MaterializeError, match="不是 TSD"):
        binary.materialize_tsd_file(source)
