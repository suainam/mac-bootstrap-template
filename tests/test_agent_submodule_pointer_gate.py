from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "agent_submodule_pointer_gate.py"
SPEC = importlib.util.spec_from_file_location("agent_submodule_pointer_gate", MODULE_PATH)
pointer_gate = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules["agent_submodule_pointer_gate"] = pointer_gate
SPEC.loader.exec_module(pointer_gate)


def test_fetchable_accepts_oid_advertised_by_remote(monkeypatch, tmp_path: Path):
    oid = "a" * 40
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"{oid}\trefs/heads/main\n",
            stderr="",
        )

    monkeypatch.setattr(pointer_gate, "_run", fake_run)

    pointer_gate._fetchable(
        tmp_path,
        "template",
        "git@github.com:example/template.git",
        oid,
    )

    assert len(calls) == 1
    assert "ls-remote" in calls[0]
    assert "fetch" not in calls[0]
