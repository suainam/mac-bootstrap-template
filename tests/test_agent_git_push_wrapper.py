from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = ROOT / "scripts" / "agent_git_hook_dispatcher.py"
REGISTRY = ROOT / "agent" / "runtime" / "registry.jsonc"
ZERO_OID = "0" * 40


def run(command, *, cwd: Path, env: dict[str, str], check: bool = True):
    return subprocess.run(
        list(command), cwd=cwd, env=env, capture_output=True, text=True, check=check
    )


def git(repo: Path, env: dict[str, str], *args: str, check: bool = True):
    return run(["git", *args], cwd=repo, env=env, check=check)


@dataclass(frozen=True)
class RuntimeRepo:
    home: Path
    env: dict[str, str]
    repo: Path
    remote: Path
    install_root: Path
    state_root: Path
    wrapper: Path


def setup_runtime_repo(tmp_path: Path) -> RuntimeRepo:
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env.update(
        HOME=str(home),
        XDG_STATE_HOME=str(home / ".local/state"),
        XDG_DATA_HOME=str(home / ".local/share"),
    )
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "PYTHON",
        "PYTHON_BIN",
        "AGENT_RUNTIME_SESSION_ID",
        "AGENT_RUNTIME_PUSH_OPERATION_ID",
        "AGENT_RUNTIME_PUSH_ARGV_JSON",
    ):
        env.pop(key, None)

    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    install_root = tmp_path / "install"
    state_root = tmp_path / "state"
    repo.mkdir()
    git(repo, env, "init", "-q", "-b", "main")
    git(repo, env, "config", "user.email", "push-wrapper@example.com")
    git(repo, env, "config", "user.name", "Push Wrapper Test")
    (repo / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(repo, env, "add", "sample.py")
    git(repo, env, "commit", "-qm", "initial")
    git(repo, env, "init", "--bare", "-q", str(remote))
    git(repo, env, "remote", "add", "origin", str(remote))
    git(repo, env, "config", "agent.runtime.enabled", "true")
    git(repo, env, "config", "agent.runtime.profile", "python-repo-smoke")

    installed = run(
        [
            sys.executable,
            str(DISPATCHER),
            "--repo",
            str(repo),
            "--install-root",
            str(install_root),
            "--state-root",
            str(state_root),
            "--python",
            sys.executable,
            "install",
            "--registry",
            str(REGISTRY),
        ],
        cwd=repo,
        env=env,
    )
    wrapper = install_root / "current/bin/agent-git-push"
    assert json.loads(installed.stdout)["push_wrapper"] == str(wrapper)
    assert wrapper.is_file() and os.access(wrapper, os.X_OK)
    return RuntimeRepo(home, env, repo, remote, install_root, state_root, wrapper)


def wrapper_push(runtime: RuntimeRepo, operation_id: str, *args: str, check=True):
    return run(
        [str(runtime.wrapper), "--operation-id", operation_id, *args],
        cwd=runtime.repo,
        env=runtime.env,
        check=check,
    )


def query_receipt(runtime: RuntimeRepo, operation_id: str, check=True):
    result = run(
        [str(runtime.wrapper), "--receipt", operation_id],
        cwd=runtime.repo,
        env=runtime.env,
        check=check,
    )
    if result.returncode != 0:
        return result, None
    return result, json.loads(result.stdout)


def remote_oid(runtime: RuntimeRepo, ref: str) -> str:
    return run(
        ["git", "--git-dir", str(runtime.remote), "rev-parse", ref],
        cwd=runtime.repo,
        env=runtime.env,
    ).stdout.strip()


def commit_value(runtime: RuntimeRepo, value: int, subject: str) -> str:
    (runtime.repo / "sample.py").write_text(f"VALUE = {value}\n", encoding="utf-8")
    git(runtime.repo, runtime.env, "add", "sample.py")
    git(runtime.repo, runtime.env, "commit", "-qm", subject)
    return git(runtime.repo, runtime.env, "rev-parse", "HEAD").stdout.strip()


def test_wrapper_records_first_push_only_after_remote_ref_updates(tmp_path: Path):
    runtime = setup_runtime_repo(tmp_path)

    pushed = wrapper_push(runtime, "op-first", "-u", "origin", "main", check=False)
    assert pushed.returncode == 0, pushed.stderr

    local_sha = git(runtime.repo, runtime.env, "rev-parse", "HEAD").stdout.strip()
    assert remote_oid(runtime, "refs/heads/main") == local_sha

    queried, receipt = query_receipt(runtime, "op-first")
    assert queried.stderr == ""
    assert receipt["event_type"] == "push.success"
    assert receipt["operation_id"] == "op-first"
    assert receipt["remote_name"] == "origin"
    assert receipt["git_args"] == ["-u", "origin", "main"]
    assert receipt["refs"] == [
        {
            "deleted": False,
            "force_update": False,
            "local_oid": local_sha,
            "local_ref": "refs/heads/main",
            "remote_oid_after": local_sha,
            "remote_oid_before": ZERO_OID,
            "remote_ref": "refs/heads/main",
        }
    ]
    assert Path(receipt["log_ref"]).is_file()
    assert Path(receipt["git_trace_ref"]).is_file()


def test_dry_run_and_rejected_push_do_not_create_success_receipts(tmp_path: Path):
    runtime = setup_runtime_repo(tmp_path)
    wrapper_push(runtime, "op-first", "-u", "origin", "main")
    first_remote = remote_oid(runtime, "refs/heads/main")
    commit_value(runtime, 2, "second")

    dry_run = wrapper_push(
        runtime, "op-dry", "--dry-run", "origin", "main", check=False
    )
    assert dry_run.returncode == 0
    assert remote_oid(runtime, "refs/heads/main") == first_remote
    missing_dry, _ = query_receipt(runtime, "op-dry", check=False)
    assert missing_dry.returncode == 2

    hook = runtime.remote / "hooks/pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o700)
    rejected = wrapper_push(runtime, "op-rejected", "origin", "main", check=False)
    assert rejected.returncode != 0
    assert remote_oid(runtime, "refs/heads/main") == first_remote
    missing_rejected, _ = query_receipt(runtime, "op-rejected", check=False)
    assert missing_rejected.returncode == 2


def test_multi_ref_delete_and_force_push_receipts_match_remote(tmp_path: Path):
    runtime = setup_runtime_repo(tmp_path)
    wrapper_push(runtime, "op-first", "-u", "origin", "main")
    base = remote_oid(runtime, "refs/heads/main")

    git(runtime.repo, runtime.env, "branch", "feature")
    git(runtime.repo, runtime.env, "tag", "v1")
    wrapper_push(runtime, "op-multi", "origin", "main", "feature", "v1")
    _, multi = query_receipt(runtime, "op-multi")
    assert {item["remote_ref"] for item in multi["refs"]} == {
        "refs/heads/feature",
        "refs/tags/v1",
    }

    wrapper_push(runtime, "op-delete", "--delete", "origin", "feature")
    _, deleted = query_receipt(runtime, "op-delete")
    assert deleted["refs"] == [
        {
            "deleted": True,
            "force_update": False,
            "local_oid": ZERO_OID,
            "local_ref": "(delete)",
            "remote_oid_after": ZERO_OID,
            "remote_oid_before": base,
            "remote_ref": "refs/heads/feature",
        }
    ]

    commit_value(runtime, 2, "remote advance")
    wrapper_push(runtime, "op-advance", "origin", "main")
    git(runtime.repo, runtime.env, "reset", "--hard", base)
    forced_oid = commit_value(runtime, 3, "divergent replacement")
    wrapper_push(runtime, "op-force", "--force", "origin", "main")
    _, forced = query_receipt(runtime, "op-force")
    assert forced["refs"][0]["force_update"] is True
    assert forced["refs"][0]["remote_oid_after"] == forced_oid
    assert remote_oid(runtime, "refs/heads/main") == forced_oid


def test_same_operation_id_is_idempotent_and_rejects_different_arguments(tmp_path: Path):
    runtime = setup_runtime_repo(tmp_path)
    wrapper_push(runtime, "op-stable", "-u", "origin", "main")
    _, first = query_receipt(runtime, "op-stable")

    repeated = wrapper_push(
        runtime, "op-stable", "-u", "origin", "main", check=False
    )
    assert repeated.returncode == 0
    _, second = query_receipt(runtime, "op-stable")
    assert second == first

    mismatched = wrapper_push(
        runtime, "op-stable", "origin", "main", check=False
    )
    assert mismatched.returncode == 2
    assert "different git arguments" in mismatched.stderr


def test_noop_push_succeeds_without_fabricating_receipt(tmp_path: Path):
    runtime = setup_runtime_repo(tmp_path)
    wrapper_push(runtime, "op-first", "-u", "origin", "main")

    noop = wrapper_push(runtime, "op-noop", "origin", "main", check=False)

    assert noop.returncode == 0
    missing, _ = query_receipt(runtime, "op-noop", check=False)
    assert missing.returncode == 2


def test_pre_push_gate_failure_does_not_contact_remote_or_write_receipt(tmp_path: Path):
    runtime = setup_runtime_repo(tmp_path)
    (runtime.repo / "Makefile").write_text(
        "repo-check:\n\t@echo blocked >&2; exit 17\n",
        encoding="utf-8",
    )
    git(runtime.repo, runtime.env, "add", "Makefile")
    git(runtime.repo, runtime.env, "commit", "-qm", "add failing gate")
    git(runtime.repo, runtime.env, "config", "agent.runtime.profile", "repository")

    blocked = wrapper_push(runtime, "op-blocked", "origin", "main", check=False)

    assert blocked.returncode != 0
    assert "blocked" in blocked.stderr
    remote_missing = run(
        ["git", "--git-dir", str(runtime.remote), "show-ref", "--verify", "refs/heads/main"],
        cwd=runtime.repo,
        env=runtime.env,
        check=False,
    )
    assert remote_missing.returncode != 0
    missing, _ = query_receipt(runtime, "op-blocked", check=False)
    assert missing.returncode == 2


def test_remote_success_with_receipt_failure_reports_irreversible_state(tmp_path: Path):
    runtime = setup_runtime_repo(tmp_path)
    env = dict(runtime.env)
    env["AGENT_RUNTIME_TESTING"] = "1"
    env["AGENT_RUNTIME_PUSH_FAIL_AT"] = "before-receipt-write"

    pushed = run(
        [str(runtime.wrapper), "--operation-id", "op-receipt-fail", "origin", "main"],
        cwd=runtime.repo,
        env=env,
        check=False,
    )

    local_sha = git(runtime.repo, runtime.env, "rev-parse", "HEAD").stdout.strip()
    assert remote_oid(runtime, "refs/heads/main") == local_sha
    assert pushed.returncode == 2
    assert "remote push succeeded" in pushed.stderr
    assert "receipt" in pushed.stderr
    missing, _ = query_receipt(runtime, "op-receipt-fail", check=False)
    assert missing.returncode == 2

    recovered = wrapper_push(
        runtime, "op-receipt-fail", "origin", "main", check=False
    )
    assert recovered.returncode == 0
    _, receipt = query_receipt(runtime, "op-receipt-fail")
    assert receipt["refs"][0]["remote_oid_after"] == local_sha


def test_latest_receipt_and_explain_are_scoped_to_current_worktree(tmp_path: Path):
    runtime = setup_runtime_repo(tmp_path)
    wrapper_push(runtime, "op-first", "-u", "origin", "main")
    commit_value(runtime, 2, "second")
    wrapper_push(runtime, "op-second", "origin", "main")

    latest = run(
        [str(runtime.wrapper), "--receipt", "latest"],
        cwd=runtime.repo,
        env=runtime.env,
    )
    explained = run(
        [str(runtime.wrapper), "--explain"],
        cwd=runtime.repo,
        env=runtime.env,
    )

    assert json.loads(latest.stdout)["operation_id"] == "op-second"
    explanation = json.loads(explained.stdout)
    assert explanation["repository_id"]
    assert explanation["worktree_id"]
    assert explanation["profile"] == "python-repo-smoke"
    assert explanation["runtime_release"]


def test_no_verify_and_missing_remote_never_create_success_receipts(tmp_path: Path):
    runtime = setup_runtime_repo(tmp_path)

    bypass = wrapper_push(
        runtime, "op-no-verify", "--no-verify", "origin", "main", check=False
    )
    assert bypass.returncode == 2
    assert "--no-verify" in bypass.stderr
    missing_bypass, _ = query_receipt(runtime, "op-no-verify", check=False)
    assert missing_bypass.returncode == 2

    missing_remote = wrapper_push(
        runtime, "op-missing-remote", "missing", "main", check=False
    )
    assert missing_remote.returncode != 0
    missing_receipt, _ = query_receipt(runtime, "op-missing-remote", check=False)
    assert missing_receipt.returncode == 2


def test_wrapper_preserves_nested_cwd_for_git_processes(tmp_path: Path):
    runtime = setup_runtime_repo(tmp_path)
    nested = runtime.repo / "nested"
    nested.mkdir()
    marker = tmp_path / "git-cwd.jsonl"
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    real_git = shutil.which("git")
    assert real_git
    shim = shim_dir / "git"
    shim.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,pathlib,sys\n"
        "marker=pathlib.Path(os.environ['GIT_CWD_MARKER'])\n"
        "with marker.open('a',encoding='utf-8') as stream:\n"
        "    stream.write(json.dumps({'cwd':os.getcwd(),'argv':sys.argv[1:]})+'\\n')\n"
        f"os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])\n",
        encoding="utf-8",
    )
    shim.chmod(0o700)
    env = dict(runtime.env)
    env["PATH"] = f"{shim_dir}:{env['PATH']}"
    env["GIT_CWD_MARKER"] = str(marker)

    pushed = run(
        [str(runtime.wrapper), "--operation-id", "op-nested", "origin", "main"],
        cwd=nested,
        env=env,
    )

    assert pushed.returncode == 0
    events = [json.loads(line) for line in marker.read_text(encoding="utf-8").splitlines()]
    push_events = [event for event in events if event["argv"][:1] == ["push"]]
    verify_events = [event for event in events if event["argv"][:2] == ["ls-remote", "--refs"]]
    assert push_events and push_events[0]["cwd"] == str(nested)
    assert verify_events and verify_events[-1]["cwd"] == str(nested)
    receipt = json.loads(
        run(
            [str(runtime.wrapper), "--receipt", "op-nested"],
            cwd=nested,
            env=runtime.env,
        ).stdout
    )
    assert receipt["repo_root"] == str(runtime.repo)
    assert receipt["remote_name"] == "origin"


def test_push_success_is_dispatched_as_a_standard_runtime_event(tmp_path: Path):
    runtime = setup_runtime_repo(tmp_path)
    marker = tmp_path / "push-success-event.json"
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runtime": {
                    "diagnostic_limit": 5,
                    "diagnostic_bytes": 4096,
                    "log_dir": str(tmp_path / "runtime-logs"),
                },
                "profiles": {"receipt-profile": {"gates": ["capture"]}},
                "gates": {
                    "capture": {
                        "events": ["push.success"],
                        "path_globs": [],
                        "command": [
                            sys.executable,
                            "-c",
                            (
                                "import os,pathlib; "
                                "pathlib.Path(os.environ['PUSH_EVENT_MARKER']).write_text("
                                "os.environ['AGENT_RUNTIME_EVENT_JSON'],encoding='utf-8')"
                            ),
                        ],
                        "cwd": "repo",
                        "mode": "sync",
                        "timeout_seconds": 5,
                        "failure_policy": "block",
                        "output_policy": "diagnostic",
                        "capabilities": ["read-only"],
                        "stage": "generic",
                        "action": "check",
                        "severity": "error",
                        "rule_revision": "1",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    git(runtime.repo, runtime.env, "config", "agent.runtime.profile", "receipt-profile")
    run(
        [
            sys.executable,
            str(DISPATCHER),
            "--repo",
            str(runtime.repo),
            "--install-root",
            str(runtime.install_root),
            "--state-root",
            str(runtime.state_root),
            "--python",
            sys.executable,
            "install",
            "--registry",
            str(registry),
        ],
        cwd=runtime.repo,
        env=runtime.env,
    )
    env = dict(runtime.env)
    env["PUSH_EVENT_MARKER"] = str(marker)

    pushed = run(
        [str(runtime.wrapper), "--operation-id", "op-event", "origin", "main"],
        cwd=runtime.repo,
        env=env,
    )

    assert pushed.returncode == 0
    event = json.loads(marker.read_text(encoding="utf-8"))
    assert event["event_type"] == "push.success"
    assert event["source_adapter"] == "git-push-wrapper"
    assert event["metadata"]["operation_id"] == "op-event"
    assert event["metadata"]["refs"][0]["remote_ref"] == "refs/heads/main"


def test_same_operation_id_is_isolated_between_linked_worktrees(tmp_path: Path):
    runtime = setup_runtime_repo(tmp_path)
    linked = tmp_path / "linked"
    git(runtime.repo, runtime.env, "worktree", "add", "-q", "-b", "linked", str(linked))

    main_push = wrapper_push(runtime, "op-shared", "-u", "origin", "main")
    linked_push = run(
        [str(runtime.wrapper), "--operation-id", "op-shared", "-u", "origin", "linked"],
        cwd=linked,
        env=runtime.env,
    )

    assert main_push.returncode == 0
    assert linked_push.returncode == 0
    main_receipt = json.loads(
        run(
            [str(runtime.wrapper), "--receipt", "op-shared"],
            cwd=runtime.repo,
            env=runtime.env,
        ).stdout
    )
    linked_receipt = json.loads(
        run(
            [str(runtime.wrapper), "--receipt", "op-shared"],
            cwd=linked,
            env=runtime.env,
        ).stdout
    )
    assert main_receipt["repository_id"] == linked_receipt["repository_id"]
    assert main_receipt["worktree_id"] != linked_receipt["worktree_id"]
    assert main_receipt["refs"][0]["remote_ref"] == "refs/heads/main"
    assert linked_receipt["refs"][0]["remote_ref"] == "refs/heads/linked"
