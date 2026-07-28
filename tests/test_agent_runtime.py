from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "agent_runtime.py"
WRAPPER = ROOT / "scripts" / "agent-runtime.sh"


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
    run_git(repo, "config", "user.email", "runtime@example.com")
    run_git(repo, "config", "user.name", "Runtime Test")


def opt_in(repo: Path, profile: str = "test") -> None:
    run_git(repo, "config", "--local", "agent.runtime.enabled", "true")
    run_git(repo, "config", "--local", "agent.runtime.profile", profile)


def write_registry(
    path: Path,
    *,
    gates: dict[str, object] | None = None,
    profiles: dict[str, object] | None = None,
) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runtime": {
                    "diagnostic_limit": 5,
                    "diagnostic_bytes": 4096,
                    "log_dir": str(path.parent / "logs"),
                },
                "profiles": profiles or {"test": {"gates": list((gates or {}).keys())}},
                "gates": gates or {},
            }
        ),
        encoding="utf-8",
    )
    return path


def event(repo: Path, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "event_type": "after.edit",
        "event_id": "evt-001",
        "source_adapter": "test",
        "timestamp": "2026-07-27T00:00:00Z",
        "cwd": str(repo),
        "target_paths": ["sample.py"],
        "session_id": "session-001",
        "metadata": {},
    }
    payload.update(overrides)
    return payload


def run_runtime(
    repo: Path,
    registry: Path,
    command: str,
    payload: dict[str, object],
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("PYTHON", None)
    env.pop("PYTHON_BIN", None)
    return subprocess.run(
        [sys.executable, str(RUNTIME), "--registry", str(registry), command],
        cwd=repo,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def gate_command(script: Path, marker: Path, *, mode: str = "sync", timeout: float = 5) -> dict[str, object]:
    return {
        "events": ["after.edit"],
        "path_globs": ["*.py"],
        "command": [sys.executable, str(script), str(marker)],
        "cwd": "repo",
        "mode": mode,
        "timeout_seconds": timeout,
        "failure_policy": "diagnose" if mode == "async" else "block",
        "output_policy": "silent",
        "capabilities": [],
    }


def test_unopted_repository_dispatch_is_silent_noop(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    registry = write_registry(tmp_path / "registry.json")

    result = run_runtime(repo, registry, "dispatch", event(repo))

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_opted_repository_executes_trusted_gate_and_stays_silent(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    marker = tmp_path / "marker.txt"
    script = tmp_path / "gate.py"
    script.write_text(
        "import os, pathlib, sys\n"
        "pathlib.Path(sys.argv[1]).write_text(os.environ['AGENT_RUNTIME_EVENT_TYPE'])\n",
        encoding="utf-8",
    )
    registry = write_registry(
        tmp_path / "registry.json",
        gates={"write-marker": gate_command(script, marker)},
    )

    result = run_runtime(repo, registry, "dispatch", event(repo))

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert marker.read_text(encoding="utf-8") == "after.edit"


def test_explain_is_deterministic_and_does_not_execute_gate(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    marker = tmp_path / "marker.txt"
    script = tmp_path / "gate.py"
    script.write_text("import pathlib, sys\npathlib.Path(sys.argv[1]).touch()\n", encoding="utf-8")
    registry = write_registry(
        tmp_path / "registry.json",
        gates={"write-marker": gate_command(script, marker)},
    )
    payload = event(repo)

    first = run_runtime(repo, registry, "explain", payload)
    second = run_runtime(repo, registry, "explain", payload)

    assert first.returncode == 0
    assert first.stderr == ""
    assert first.stdout == second.stdout
    explained = json.loads(first.stdout)
    assert explained["enabled"] is True
    assert explained["profile"] == "test"
    assert explained["matched_gates"] == ["write-marker"]
    assert explained["matched_gate_details"] == [
        {
            "action": "check",
            "capabilities": [],
            "failure_policy": "block",
            "gate_id": "write-marker",
            "mode": "sync",
            "output_policy": "silent",
            "rule_revision": "1",
            "safe_fix_max_rounds": 0,
            "safe_fix_operation_id": None,
            "severity": "error",
            "stage": "edit",
            "timeout_seconds": 5.0,
        }
    ]
    assert marker.exists() is False


def test_unknown_profile_fails_closed_with_bounded_diagnostic(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo, "missing")
    registry = write_registry(tmp_path / "registry.json")

    result = run_runtime(repo, registry, "dispatch", event(repo))

    assert result.returncode == 1
    assert result.stdout == ""
    assert "unknown profile" in result.stderr
    assert len(result.stderr.encode()) <= 4096


def test_registry_rejects_shell_string_command(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    registry = write_registry(
        tmp_path / "registry.json",
        gates={
            "unsafe": {
                "events": ["after.edit"],
                "command": "touch /tmp/unsafe",
                "cwd": "repo",
                "mode": "sync",
                "timeout_seconds": 5,
                "failure_policy": "block",
                "output_policy": "silent",
                "capabilities": [],
            }
        },
    )

    result = run_runtime(repo, registry, "dispatch", event(repo))

    assert result.returncode == 1
    assert "command must be a non-empty argv list" in result.stderr


def test_event_schema_error_wins_over_repository_configuration_error(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    run_git(repo, "config", "--local", "agent.runtime.enabled", "true")
    registry = write_registry(tmp_path / "registry.json")

    result = run_runtime(
        repo,
        registry,
        "dispatch",
        event(repo, schema_version=2),
    )

    assert result.returncode == 2
    assert "unsupported event schema_version" in result.stderr
    assert "agent.runtime.profile" not in result.stderr


def test_profile_rejects_duplicate_gate_execution(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    marker = tmp_path / "marker.txt"
    script = tmp_path / "gate.py"
    script.write_text("import pathlib, sys\npathlib.Path(sys.argv[1]).touch()\n", encoding="utf-8")
    gate = gate_command(script, marker)
    registry = write_registry(
        tmp_path / "registry.json",
        gates={"duplicate": gate},
        profiles={"test": {"gates": ["duplicate", "duplicate"]}},
    )

    result = run_runtime(repo, registry, "dispatch", event(repo))

    assert result.returncode == 1
    assert "contains duplicate gates" in result.stderr
    assert marker.exists() is False


def test_event_rejects_target_path_outside_repository(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    registry = write_registry(tmp_path / "registry.json")

    result = run_runtime(
        repo,
        registry,
        "dispatch",
        event(repo, target_paths=[str(tmp_path / "outside.py")]),
    )

    assert result.returncode == 2
    assert "outside repository" in result.stderr


def test_event_rejects_more_than_4096_target_paths(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    registry = write_registry(tmp_path / "registry.json")

    result = run_runtime(
        repo,
        registry,
        "dispatch",
        event(
            repo,
            event_type="before.push",
            target_paths=[f"p/{index:x}" for index in range(4097)],
        ),
    )

    assert result.returncode == 2
    assert "target_paths exceeds 4096 entries" in result.stderr


def test_sync_gate_timeout_fails_closed(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    marker = tmp_path / "marker.txt"
    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
    registry = write_registry(
        tmp_path / "registry.json",
        gates={"slow": gate_command(script, marker, timeout=0.05)},
    )

    result = run_runtime(repo, registry, "dispatch", event(repo))

    assert result.returncode == 1
    assert "timed out" in result.stderr
    assert len(result.stderr.encode()) <= 4096


def test_default_registry_doctor_is_available_through_wrapper(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    env = os.environ.copy()
    env["PYTHON"] = sys.executable

    result = subprocess.run(
        [str(WRAPPER), "doctor"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["registry_schema_version"] == 1
    assert payload["event_schema_version"] == 1
    assert payload["known_profiles"] == [
        "generic",
        "claude-edit-smoke",
        "mac-bootstrap-template",
        "python-repo-smoke",
        "mac-bootstrap-parent",
    ]
    assert payload["known_gates"] == [
        "python-syntax-smoke",
        "template-staged-python-syntax",
        "parent-submodule-pointer-reachable",
        "parent-repository-check",
        "parent-machine-check",
        "template-push-ref-integrity",
    ]
    assert payload["enabled"] is False


def test_default_generic_profile_dispatch_is_silent(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo, "generic")
    env = os.environ.copy()
    env.pop("PYTHON", None)
    env.pop("PYTHON_BIN", None)

    result = subprocess.run(
        [sys.executable, str(RUNTIME), "dispatch"],
        cwd=repo,
        input=json.dumps(event(repo)),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_async_gate_runs_outside_hot_path_and_logs_externally(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    marker = tmp_path / "async-marker.txt"
    script = tmp_path / "async_gate.py"
    script.write_text(
        "import pathlib, sys, time\n"
        "time.sleep(0.1)\n"
        "pathlib.Path(sys.argv[1]).write_text('done')\n",
        encoding="utf-8",
    )
    registry = write_registry(
        tmp_path / "registry.json",
        gates={"async-marker": gate_command(script, marker, mode="async")},
    )

    started = time.monotonic()
    result = run_runtime(repo, registry, "dispatch", event(repo))
    elapsed = time.monotonic() - started

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert elapsed < 1
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.05)
    assert marker.read_text(encoding="utf-8") == "done"
    assert list((tmp_path / "logs").rglob("evt-001-async-marker-*.log"))


def test_async_gate_timeout_is_recorded_in_external_log(tmp_path: Path):
    repo = tmp_path / "repo"
    init_repo(repo)
    opt_in(repo)
    marker = tmp_path / "should-not-exist.txt"
    script = tmp_path / "slow_async.py"
    script.write_text(
        "import pathlib, sys, time\n"
        "time.sleep(1)\n"
        "pathlib.Path(sys.argv[1]).write_text('late')\n",
        encoding="utf-8",
    )
    registry = write_registry(
        tmp_path / "registry.json",
        gates={
            "slow-async": gate_command(
                script, marker, mode="async", timeout=0.05
            )
        },
    )

    result = run_runtime(repo, registry, "dispatch", event(repo))

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    deadline = time.monotonic() + 3
    logs: list[Path] = []
    while time.monotonic() < deadline:
        logs = list((tmp_path / "logs").rglob("evt-001-slow-async-*.log"))
        if logs and "timed out" in logs[0].read_text(encoding="utf-8"):
            break
        time.sleep(0.05)
    assert logs
    assert "timed out" in logs[0].read_text(encoding="utf-8")
    assert marker.exists() is False
