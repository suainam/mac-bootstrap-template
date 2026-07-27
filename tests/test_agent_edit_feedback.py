from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "agent_runtime.py"


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def init_repo(repo: Path) -> None:
    repo.mkdir()
    run_git(repo, "init", "-q")
    run_git(repo, "config", "user.email", "feedback@example.com")
    run_git(repo, "config", "user.name", "Feedback Test")


def opt_in(repo: Path, profile: str = "test") -> None:
    run_git(repo, "config", "--local", "agent.runtime.enabled", "true")
    run_git(repo, "config", "--local", "agent.runtime.profile", profile)


def write_registry(
    path: Path,
    gates: dict[str, object],
    *,
    log_dir: Path | None = None,
) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runtime": {
                    "diagnostic_limit": 5,
                    "diagnostic_bytes": 4096,
                    "log_dir": str(log_dir or path.parent / "state"),
                },
                "profiles": {"test": {"gates": list(gates)}},
                "gates": gates,
            }
        ),
        encoding="utf-8",
    )
    return path


def event(
    repo: Path,
    *,
    event_type: str = "after.edit",
    event_id: str = "evt-001",
    target_paths: list[str] | None = None,
    session_id: str = "session-001",
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "event_id": event_id,
        "source_adapter": "test",
        "timestamp": "2026-07-27T00:00:00Z",
        "cwd": str(repo),
        "target_paths": ["sample.py"] if target_paths is None else target_paths,
        "session_id": session_id,
        "metadata": metadata or {},
    }


def clean_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHON", None)
    env.pop("PYTHON_BIN", None)
    return env


def run_runtime(
    repo: Path,
    registry: Path,
    payload: dict[str, object],
    command: str = "dispatch",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME), "--registry", str(registry), command],
        cwd=repo,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env=clean_env(),
    )


def explain_context(
    repo: Path,
    registry: Path,
    session_id: str,
) -> dict[str, object]:
    result = subprocess.run(
        [
            sys.executable,
            str(RUNTIME),
            "--registry",
            str(registry),
            "--cwd",
            str(repo),
            "--session-id",
            session_id,
            "explain-context",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env=clean_env(),
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def check_gate(
    script: Path,
    *args: Path,
    stage: str = "edit",
    event_type: str = "after.edit",
    failure_policy: str = "diagnose",
) -> dict[str, object]:
    return {
        "stage": stage,
        "action": "check",
        "events": [event_type],
        "path_globs": ["*.py"],
        "command": [sys.executable, str(script), *(str(arg) for arg in args)],
        "cwd": "repo",
        "mode": "sync",
        "timeout_seconds": 5,
        "failure_policy": failure_policy,
        "output_policy": "diagnostic",
        "severity": "error",
        "rule_revision": "fixture-v1",
        "capabilities": [],
    }


def safe_fix_gate(
    script: Path,
    *args: Path,
    operation_id: str = "format-python",
    max_rounds: int = 2,
) -> dict[str, object]:
    return {
        "stage": "edit",
        "action": "safe-fix",
        "events": ["after.edit"],
        "path_globs": ["*.py"],
        "command": [sys.executable, str(script), *(str(arg) for arg in args)],
        "cwd": "repo",
        "mode": "sync",
        "timeout_seconds": 5,
        "failure_policy": "diagnose",
        "output_policy": "diagnostic",
        "severity": "error",
        "rule_revision": "formatter-v1",
        "capabilities": ["safe-fix"],
        "safe_fix": {
            "operation_id": operation_id,
            "max_rounds": max_rounds,
        },
    }


def test_after_edit_rejects_multiple_target_files(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    (repo / "sample.py").write_text("value = 1\n", encoding="utf-8")
    (repo / "other.py").write_text("value = 2\n", encoding="utf-8")
    noop = tmp_path / "noop.py"
    noop.write_text("raise SystemExit(0)\n", encoding="utf-8")
    registry = write_registry(
        tmp_path / "registry.json",
        {"edit-check": check_gate(noop)},
    )

    result = run_runtime(
        repo,
        registry,
        event(repo, target_paths=["sample.py", "other.py"]),
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "after.edit requires exactly one target path" in result.stderr


def test_after_edit_accumulates_and_after_batch_consumes_changed_files(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    (repo / "sample.py").write_text("value = 1\n", encoding="utf-8")
    edit_marker = tmp_path / "edit.json"
    batch_marker = tmp_path / "batch.json"
    capture = tmp_path / "capture.py"
    capture.write_text(
        "import json, os, pathlib, sys\n"
        "pathlib.Path(sys.argv[1]).write_text(os.environ['AGENT_RUNTIME_EVENT_JSON'])\n",
        encoding="utf-8",
    )
    registry = write_registry(
        tmp_path / "registry.json",
        {
            "edit-check": check_gate(capture, edit_marker),
            "batch-check": check_gate(
                capture,
                batch_marker,
                stage="batch",
                event_type="after.batch",
            ),
        },
    )

    edit_result = run_runtime(repo, registry, event(repo))

    assert edit_result.returncode == 0
    assert edit_result.stdout == ""
    assert edit_result.stderr == ""
    assert edit_marker.exists()
    assert batch_marker.exists() is False
    context = explain_context(repo, registry, "session-001")
    accumulator_path = Path(context["runtime_state"]["accumulator_path"])
    accumulated = json.loads(accumulator_path.read_text(encoding="utf-8"))
    assert accumulated["changed_files"] == {"sample.py": accumulated["changed_files"]["sample.py"]}

    batch_result = run_runtime(
        repo,
        registry,
        event(
            repo,
            event_type="after.batch",
            event_id="batch-001",
            target_paths=[],
        ),
    )

    assert batch_result.returncode == 0
    assert batch_result.stdout == ""
    assert batch_result.stderr == ""
    captured = json.loads(batch_marker.read_text(encoding="utf-8"))
    assert captured["target_paths"] == ["sample.py"]
    assert accumulator_path.exists() is False


def test_edit_stage_notice_must_be_deferred_to_batch(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    (repo / "sample.py").write_text("value = 1\n", encoding="utf-8")
    noop = tmp_path / "noop.py"
    noop.write_text("raise SystemExit(0)\n", encoding="utf-8")
    gate = check_gate(noop)
    gate["severity"] = "notice"
    registry = write_registry(
        tmp_path / "registry.json",
        {"notice": gate},
    )

    result = run_runtime(repo, registry, event(repo))

    assert result.returncode == 1
    assert result.stdout == ""
    assert "notices must be deferred to after.batch" in result.stderr


def test_duplicate_safe_fix_operation_ids_are_rejected(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    (repo / "sample.py").write_text("value = 1   \n", encoding="utf-8")
    formatter = tmp_path / "formatter.py"
    formatter.write_text("raise SystemExit(0)\n", encoding="utf-8")
    registry = write_registry(
        tmp_path / "registry.json",
        {
            "format-a": safe_fix_gate(formatter, operation_id="shared-format"),
            "format-b": safe_fix_gate(formatter, operation_id="shared-format"),
        },
    )

    result = run_runtime(repo, registry, event(repo))

    assert result.returncode == 1
    assert result.stdout == ""
    assert "operation_id 'shared-format' is shared" in result.stderr


def test_safe_fix_requires_explicit_trusted_capability(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    target = repo / "sample.py"
    target.write_text("value = 1   \n", encoding="utf-8")
    formatter = tmp_path / "formatter.py"
    formatter.write_text("raise SystemExit(0)\n", encoding="utf-8")
    gate = safe_fix_gate(formatter)
    gate["capabilities"] = []
    registry = write_registry(
        tmp_path / "registry.json",
        {"format-python": gate},
    )

    result = run_runtime(repo, registry, event(repo))

    assert result.returncode == 1
    assert result.stdout == ""
    assert "requires the safe-fix capability" in result.stderr
    assert target.read_text(encoding="utf-8") == "value = 1   \n"


def test_safe_fix_is_idempotent_writes_receipt_and_repeated_event_is_noop(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    target = repo / "sample.py"
    target.write_text("value = 1   \n", encoding="utf-8")
    counter = tmp_path / "counter.txt"
    formatter = tmp_path / "formatter.py"
    formatter.write_text(
        "import json, os, pathlib, sys\n"
        "counter = pathlib.Path(sys.argv[1])\n"
        "counter.write_text(str(int(counter.read_text() or '0') + 1) if counter.exists() else '1')\n"
        "event = json.loads(os.environ['AGENT_RUNTIME_EVENT_JSON'])\n"
        "target = pathlib.Path(os.environ['AGENT_RUNTIME_REPO_ROOT']) / event['target_paths'][0]\n"
        "target.write_text(target.read_text().rstrip() + '\\n')\n",
        encoding="utf-8",
    )
    registry = write_registry(
        tmp_path / "registry.json",
        {"format-python": safe_fix_gate(formatter, counter)},
    )

    first = run_runtime(repo, registry, event(repo))

    assert first.returncode == 0
    assert first.stdout == ""
    assert first.stderr == ""
    assert target.read_text(encoding="utf-8") == "value = 1\n"
    assert counter.read_text(encoding="utf-8") == "2"
    context = explain_context(repo, registry, "session-001")
    receipts = list(Path(context["runtime_state"]["receipts_dir"]).glob("*.json"))
    assert len(receipts) == 1
    assert list(Path(context["runtime_state"]["diagnostics_dir"]).glob("*.log")) == []
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["operation_id"] == "format-python"
    assert receipt["input_content_hash"] != receipt["output_content_hash"]
    assert receipt["rounds"] == 2

    second = run_runtime(repo, registry, event(repo, event_id="evt-002"))

    assert second.returncode == 0
    assert second.stdout == ""
    assert second.stderr == ""
    assert counter.read_text(encoding="utf-8") == "2"


def test_concurrent_safe_fix_uses_per_file_lock(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    target = repo / "sample.py"
    target.write_text("value = 1   \n", encoding="utf-8")
    counter = tmp_path / "counter.txt"
    formatter = tmp_path / "slow_formatter.py"
    formatter.write_text(
        "import json, os, pathlib, sys, time\n"
        "counter = pathlib.Path(sys.argv[1])\n"
        "value = int(counter.read_text() or '0') + 1 if counter.exists() else 1\n"
        "counter.write_text(str(value))\n"
        "time.sleep(0.15)\n"
        "event = json.loads(os.environ['AGENT_RUNTIME_EVENT_JSON'])\n"
        "target = pathlib.Path(os.environ['AGENT_RUNTIME_REPO_ROOT']) / event['target_paths'][0]\n"
        "target.write_text(target.read_text().rstrip() + '\\n')\n",
        encoding="utf-8",
    )
    registry = write_registry(
        tmp_path / "registry.json",
        {"format-python": safe_fix_gate(formatter, counter)},
    )
    command = [sys.executable, str(RUNTIME), "--registry", str(registry), "dispatch"]
    first = subprocess.Popen(
        command,
        cwd=repo,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=clean_env(),
    )
    second = subprocess.Popen(
        command,
        cwd=repo,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=clean_env(),
    )

    first_out, first_err = first.communicate(json.dumps(event(repo, event_id="evt-a")), timeout=10)
    second_out, second_err = second.communicate(json.dumps(event(repo, event_id="evt-b")), timeout=10)

    assert first.returncode == 0
    assert second.returncode == 0
    assert first_out == second_out == ""
    assert first_err == second_err == ""
    assert target.read_text(encoding="utf-8") == "value = 1\n"
    assert counter.read_text(encoding="utf-8") == "2"


def test_non_idempotent_safe_fix_restores_original_and_diagnoses(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    target = repo / "sample.py"
    target.write_text("A", encoding="utf-8")
    toggler = tmp_path / "toggle.py"
    toggler.write_text(
        "import json, os, pathlib\n"
        "event = json.loads(os.environ['AGENT_RUNTIME_EVENT_JSON'])\n"
        "target = pathlib.Path(os.environ['AGENT_RUNTIME_REPO_ROOT']) / event['target_paths'][0]\n"
        "target.write_text('B' if target.read_text() == 'A' else 'A')\n",
        encoding="utf-8",
    )
    registry = write_registry(
        tmp_path / "registry.json",
        {"toggle": safe_fix_gate(toggler, max_rounds=2)},
    )

    result = run_runtime(repo, registry, event(repo))

    assert result.returncode == 0
    assert result.stdout == ""
    payload = json.loads(result.stderr)
    assert payload["status"] == "diagnosed"
    diagnostic = payload["diagnostics"][0]
    assert diagnostic["action"] == "stop-safe-fix"
    assert diagnostic["fingerprint"].startswith("diag-")
    assert diagnostic["log_ref"]
    assert target.read_text(encoding="utf-8") == "A"


def test_recursion_metadata_skips_same_safe_fix_operation(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    (repo / "sample.py").write_text("value = 1   \n", encoding="utf-8")
    marker = tmp_path / "marker.txt"
    formatter = tmp_path / "formatter.py"
    formatter.write_text("import pathlib, sys\npathlib.Path(sys.argv[1]).touch()\n", encoding="utf-8")
    registry = write_registry(
        tmp_path / "registry.json",
        {"format-python": safe_fix_gate(formatter, marker)},
    )

    result = run_runtime(
        repo,
        registry,
        event(
            repo,
            metadata={
                "safe_fix": {
                    "operation_id": "format-python",
                    "depth": 1,
                }
            },
        ),
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert marker.exists() is False


def test_same_diagnostic_is_deduplicated_until_content_changes(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    target = repo / "sample.py"
    target.write_text("bad\n", encoding="utf-8")
    failing = tmp_path / "failing.py"
    failing.write_text("import sys\nprint('lint failed', file=sys.stderr)\nraise SystemExit(1)\n", encoding="utf-8")
    gate = check_gate(failing)
    registry = write_registry(
        tmp_path / "registry.json",
        {"lint": gate},
    )

    first = run_runtime(repo, registry, event(repo, event_id="evt-1"))
    second = run_runtime(repo, registry, event(repo, event_id="evt-2"))
    gate["rule_revision"] = "fixture-v2"
    write_registry(registry, {"lint": gate})
    third = run_runtime(repo, registry, event(repo, event_id="evt-3"))
    target.write_text("still bad\n", encoding="utf-8")
    fourth = run_runtime(repo, registry, event(repo, event_id="evt-4"))

    assert first.returncode == second.returncode == third.returncode == fourth.returncode == 0
    first_payload = json.loads(first.stderr)
    third_payload = json.loads(third.stderr)
    fourth_payload = json.loads(fourth.stderr)
    assert first_payload["diagnostics"][0]["message"].endswith("lint failed")
    assert second.stderr == ""
    fingerprints = {
        first_payload["diagnostics"][0]["fingerprint"],
        third_payload["diagnostics"][0]["fingerprint"],
        fourth_payload["diagnostics"][0]["fingerprint"],
    }
    assert len(fingerprints) == 3


def test_unapproved_check_mutation_is_restored_and_reported(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    target = repo / "sample.py"
    target.write_text("original\n", encoding="utf-8")
    mutator = tmp_path / "mutator.py"
    mutator.write_text(
        "import json, os, pathlib\n"
        "event = json.loads(os.environ['AGENT_RUNTIME_EVENT_JSON'])\n"
        "target = pathlib.Path(os.environ['AGENT_RUNTIME_REPO_ROOT']) / event['target_paths'][0]\n"
        "target.write_text('mutated\\n')\n",
        encoding="utf-8",
    )
    registry = write_registry(
        tmp_path / "registry.json",
        {"unsafe": check_gate(mutator)},
    )

    result = run_runtime(repo, registry, event(repo))

    assert result.returncode == 0
    assert target.read_text(encoding="utf-8") == "original\n"
    diagnostic = json.loads(result.stderr)["diagnostics"][0]
    assert diagnostic["action"] == "restore-unapproved-mutation"


def test_safe_fix_refuses_to_modify_when_state_is_not_writable(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    target = repo / "sample.py"
    target.write_text("value = 1   \n", encoding="utf-8")
    formatter = tmp_path / "formatter.py"
    formatter.write_text(
        "import json, os, pathlib\n"
        "event = json.loads(os.environ['AGENT_RUNTIME_EVENT_JSON'])\n"
        "target = pathlib.Path(os.environ['AGENT_RUNTIME_REPO_ROOT']) / event['target_paths'][0]\n"
        "target.write_text(target.read_text().rstrip() + '\\n')\n",
        encoding="utf-8",
    )
    state_root = tmp_path / "unwritable"
    state_root.mkdir()
    state_root.chmod(0o500)
    registry = write_registry(
        tmp_path / "registry.json",
        {"format-python": safe_fix_gate(formatter)},
        log_dir=state_root,
    )

    try:
        result = run_runtime(repo, registry, event(repo))
    finally:
        state_root.chmod(0o700)

    assert result.returncode == 0
    assert target.read_text(encoding="utf-8") == "value = 1   \n"
    diagnostic = json.loads(result.stderr)["diagnostics"][0]
    assert diagnostic["action"] == "stop-safe-fix"
    assert "state" in diagnostic["message"].lower()


def test_accumulator_is_isolated_between_linked_worktrees(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    (repo / "sample.py").write_text("main\n", encoding="utf-8")
    run_git(repo, "add", "sample.py")
    run_git(repo, "commit", "-qm", "initial")
    opt_in(repo)
    linked = tmp_path / "linked"
    run_git(repo, "worktree", "add", "-q", str(linked), "-b", "linked-test")
    (linked / "sample.py").write_text("linked\n", encoding="utf-8")
    noop = tmp_path / "noop.py"
    noop.write_text("raise SystemExit(0)\n", encoding="utf-8")
    registry = write_registry(
        tmp_path / "registry.json",
        {"edit-check": check_gate(noop)},
    )

    main_result = run_runtime(repo, registry, event(repo, session_id="shared"))
    linked_result = run_runtime(linked, registry, event(linked, session_id="shared"))

    assert main_result.returncode == linked_result.returncode == 0
    main_context = explain_context(repo, registry, "shared")
    linked_context = explain_context(linked, registry, "shared")
    main_accumulator = Path(main_context["runtime_state"]["accumulator_path"])
    linked_accumulator = Path(linked_context["runtime_state"]["accumulator_path"])
    assert main_context["repository_id"] == linked_context["repository_id"]
    assert main_context["worktree_id"] != linked_context["worktree_id"]
    assert main_accumulator != linked_accumulator
    assert main_accumulator.exists()
    assert linked_accumulator.exists()


def test_diagnostic_output_is_limited_to_five_entries_and_four_kib(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    (repo / "sample.py").write_text("bad\n", encoding="utf-8")
    failing = tmp_path / "failing.py"
    failing.write_text(
        "import sys\nprint('x' * 2000, file=sys.stderr)\nraise SystemExit(1)\n",
        encoding="utf-8",
    )
    gates = {
        f"lint-{index}": check_gate(failing)
        for index in range(6)
    }
    registry = write_registry(tmp_path / "registry.json", gates)

    result = run_runtime(repo, registry, event(repo))

    assert result.returncode == 0
    assert result.stdout == ""
    assert len(result.stderr.encode("utf-8")) <= 4096
    payload = json.loads(result.stderr)
    assert len(payload["diagnostics"]) <= 5


def test_batch_failure_uses_structured_diagnostic_and_clears_batch(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    (repo / "sample.py").write_text("value = 1\n", encoding="utf-8")
    failing = tmp_path / "batch_fail.py"
    failing.write_text("import sys\nprint('typecheck failed', file=sys.stderr)\nraise SystemExit(1)\n", encoding="utf-8")
    noop = tmp_path / "noop.py"
    noop.write_text("raise SystemExit(0)\n", encoding="utf-8")
    registry = write_registry(
        tmp_path / "registry.json",
        {
            "edit-check": check_gate(noop),
            "batch-check": check_gate(
                failing,
                stage="batch",
                event_type="after.batch",
                failure_policy="block",
            ),
        },
    )
    run_runtime(repo, registry, event(repo))
    context = explain_context(repo, registry, "session-001")
    accumulator = Path(context["runtime_state"]["accumulator_path"])

    result = run_runtime(
        repo,
        registry,
        event(repo, event_type="after.batch", event_id="batch", target_paths=[]),
    )

    assert result.returncode == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "blocked"
    diagnostic = payload["diagnostics"][0]
    assert diagnostic["severity"] == "error"
    assert diagnostic["action"] == "fix"
    assert diagnostic["log_ref"]
    assert accumulator.exists() is False
