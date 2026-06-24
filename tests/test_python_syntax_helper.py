"""Unit tests for check-python-syntax helper."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, rel_path: str):
    path = ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


check_python_syntax = load_module("check_python_syntax", "scripts/check-python-syntax.py")



def test_check_python_syntax_usage(capsys):
    rc = check_python_syntax.main(["check-python-syntax.py"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "Usage:" in err


def test_check_python_syntax_ok(tmp_path, capsys):
    target = tmp_path / "ok.py"
    target.write_text("x = 1\n")
    rc = check_python_syntax.main(["check-python-syntax.py", str(target)])
    out = capsys.readouterr().out
    assert rc == 0
