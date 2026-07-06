import sys
from pathlib import Path


DATA_HUB_DIR = Path(__file__).parent.parent / "agent" / "data-hub"
SCRIPTS_DIR = DATA_HUB_DIR / "scripts"
sys.path.insert(0, str(DATA_HUB_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

from workflow_contracts import (
    RetryPolicy,
    StageSpec,
    SuccessCheck,
    evaluate_success_check,
    evaluate_success_checks,
    normalize_stage,
)


def test_stage_spec_defaults_are_serializable():
    stage = StageSpec(name="demo", command=["python", "demo.py"])

    assert stage.produces == []
    assert stage.success_checks == []
    assert stage.retry_policy == RetryPolicy()
    assert stage.degraded_ok is False
    assert stage["name"] == "demo"
    assert stage.to_dict()["retry_policy"]["max_attempts"] == 1


def test_stage_spec_converts_legacy_dict():
    stage = normalize_stage(
        {
            "name": "legacy",
            "command": ["python", "legacy.py"],
            "produces": ["artifact"],
            "success_checks": [{"kind": "stdout_exists", "target": "stdout"}],
            "retry_policy": {"max_attempts": 2, "retryable_exit_codes": [2], "backoff_seconds": 0.5},
            "degraded_ok": True,
        }
    )

    assert stage.name == "legacy"
    assert stage.success_checks == [SuccessCheck("stdout_exists", "stdout", True)]
    assert stage.retry_policy == RetryPolicy(max_attempts=2, retryable_exit_codes=(2,), backoff_seconds=0.5)
    assert stage.degraded_ok is True


def test_unknown_success_check_fails(tmp_path: Path):
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")

    passed, message = evaluate_success_check(SuccessCheck("unknown", "stdout"), stdout_path, stderr_path)

    assert passed is False
    assert "unknown success check kind" in message


def test_file_exists_check_resolves_relative_target_against_vault(tmp_path: Path, monkeypatch):
    vault_dir = tmp_path / "vault"
    note = vault_dir / "10_Periodic" / "Daily" / "2026-07-04.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("# daily\n", encoding="utf-8")
    monkeypatch.setenv("OBSIDIAN_VAULT_DIR", str(vault_dir))

    passed, message = evaluate_success_check(
        SuccessCheck("file_exists", "10_Periodic/Daily/2026-07-04.md"),
        tmp_path / "stdout.log",
        tmp_path / "stderr.log",
    )

    assert passed is True
    assert message is None


def test_stdout_and_output_marker_checks(tmp_path: Path):
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    stdout_path.write_text("pytest ok\n", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")

    assert evaluate_success_check(SuccessCheck("stdout_exists", "stdout"), stdout_path, stderr_path) == (True, None)
    assert evaluate_success_check(
        SuccessCheck("output_not_contains", "combined", ["LLM generation failed"]),
        stdout_path,
        stderr_path,
    ) == (True, None)

    stdout_path.write_text("LLM generation failed\n", encoding="utf-8")
    passed, message = evaluate_success_check(
        SuccessCheck("output_not_contains", "combined", ["LLM generation failed"]),
        stdout_path,
        stderr_path,
    )

    assert passed is False
    assert "LLM generation failed" in message


def test_multiple_success_checks_short_circuit_on_first_failure(tmp_path: Path, monkeypatch):
    vault_dir = tmp_path / "vault"
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    stdout_path.write_text("bad marker\n", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("OBSIDIAN_VAULT_DIR", str(vault_dir))
    stage = StageSpec(
        name="demo",
        command=["python", "demo.py"],
        success_checks=[
            SuccessCheck("file_exists", "missing.md"),
            SuccessCheck("output_not_contains", "stdout", ["bad marker"]),
        ],
    )

    passed, message = evaluate_success_checks(stage, stdout_path, stderr_path)

    assert passed is False
    assert "missing.md" in message
