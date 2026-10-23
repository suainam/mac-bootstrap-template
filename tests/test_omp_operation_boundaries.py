"""Behavior checks for operation authorization boundaries."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_operation_boundaries():
    if shutil.which("bun") is None:
        pytest.skip("bun is required to execute OMP extensions")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["bun", "test", str(root / "tests/omp-operation-boundaries.test.ts")],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
