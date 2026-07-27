from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = ROOT / "scripts" / "agent_git_hook_dispatcher.py"
ZERO_OID = "0" * 40


def clean_env(home: Path, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHON", None)
    env.pop("PYTHON_BIN", None)
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    env.pop("QUALITY_GATES_BYPASS", None)
    env.pop("QUALITY_GATES_BYPASS_REASON", None)
    env["HOME"] = str(home)
    env["XDG_STATE_HOME"] = str(home / ".local" / "state")
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    if extra:
        env.update(extra)
    return env


def run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        env=dict(env),
        input=input_text,
        capture_output=True,
        text=True,
        check=check,
    )


def git(
    repo: Path,
    env: Mapping[str, str],
    *args: str,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return run(
        ["git", *args],
        cwd=repo,
        env=env,
        input_text=input_text,
        check=check,
    )


def init_repo(path: Path, env: Mapping[str, str]) -> None:
    path.mkdir(parents=True)
    git(path, env, "init", "-q", "-b", "main")
    git(path, env, "config", "user.email", "dispatcher@example.com")
    git(path, env, "config", "user.name", "Dispatcher Test")
    (path / "sample.txt").write_text("initial\n", encoding="utf-8")
    git(path, env, "add", "sample.txt")
    git(path, env, "commit", "-qm", "initial")


def opt_in(repo: Path, env: Mapping[str, str], profile: str = "test") -> None:
    git(repo, env, "config", "--local", "agent.runtime.enabled", "true")
    git(repo, env, "config", "--local", "agent.runtime.profile", profile)


def gate(
    event_type: str,
    script: Path,
    marker: Path,
    *,
    failure_policy: str = "block",
) -> dict[str, object]:
    return {
        "events": [event_type],
        "path_globs": [],
        "command": [sys.executable, str(script), str(marker)],
        "cwd": "repo",
        "mode": "sync",
        "timeout_seconds": 10,
        "failure_policy": failure_policy,
        "output_policy": "diagnostic",
        "severity": "error",
        "rule_revision": "fixture-v1",
        "capabilities": [],
    }


def write_registry(
    path: Path,
    gates: dict[str, object] | None = None,
) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runtime": {
                    "diagnostic_limit": 5,
                    "diagnostic_bytes": 4096,
                    "log_dir": str(path.parent / "runtime-state"),
                },
                "profiles": {
                    "test": {"gates": list((gates or {}).keys())},
                    "generic": {"gates": []},
                },
                "gates": gates or {},
            }
        ),
        encoding="utf-8",
    )
    return path


def paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    return (
        tmp_path / "home" / ".local" / "share" / "agent-runtime-hooks",
        tmp_path / "home" / ".local" / "state" / "agent-runtime-hooks",
        tmp_path / "registry.json",
    )


def dispatcher_cli(
    repo: Path,
    home: Path,
    install_root: Path,
    state_root: Path,
    *args: str,
    check: bool = True,
    extra_env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return run(
        [
            sys.executable,
            str(DISPATCHER),
            "--repo",
            str(repo),
            "--install-root",
            str(install_root),
            "--state-root",
            str(state_root),
            *args,
        ],
        cwd=repo,
        env=clean_env(home, extra_env),
        check=check,
    )


def install(
    repo: Path,
    home: Path,
    registry: Path,
    install_root: Path,
    state_root: Path,
    approved: Sequence[tuple[str, Path]] = (),
) -> dict[str, object]:
    args = ["install", "--registry", str(registry)]
    for event, hook in approved:
        args.extend(["--approve-hook", f"{event}={hook}"])
    result = dispatcher_cli(
        repo,
        home,
        install_root,
        state_root,
        *args,
    )
    assert result.stderr == ""
    return json.loads(result.stdout)


def doctor(
    repo: Path,
    home: Path,
    install_root: Path,
    state_root: Path,
) -> dict[str, object]:
    result = dispatcher_cli(
        repo,
        home,
        install_root,
        state_root,
        "doctor",
    )
    assert result.stderr == ""
    return json.loads(result.stdout)


def make_executable(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_real_commit_checks_staged_snapshot_not_unstaged_worktree(tmp_path: Path):
    home = tmp_path / "home"
    env = clean_env(home)
    repo = tmp_path / "repo"
    init_repo(repo, env)
    opt_in(repo, env)
    install_root, state_root, registry = paths(tmp_path)
    marker = tmp_path / "staged-marker.txt"
    gate_script = tmp_path / "staged_gate.py"
    gate_script.write_text(
        "import json, os, pathlib, sys\n"
        "event = json.loads(os.environ['AGENT_RUNTIME_EVENT_JSON'])\n"
        "snapshot = pathlib.Path(event['metadata']['staged_snapshot_dir']) / event['target_paths'][0]\n"
        "pathlib.Path(sys.argv[1]).write_bytes(snapshot.read_bytes())\n",
        encoding="utf-8",
    )
    write_registry(
        registry,
        {"staged": gate("before.commit", gate_script, marker)},
    )
    installed = install(repo, home, registry, install_root, state_root)

    (repo / "sample.txt").write_text("staged\n", encoding="utf-8")
    git(repo, env, "add", "sample.txt")
    (repo / "sample.txt").write_text("unstaged\n", encoding="utf-8")
    result = git(repo, env, "commit", "-m", "staged scope", check=False)

    assert result.returncode == 0, result.stderr
    assert marker.read_text(encoding="utf-8") == "staged\n"
    assert git(repo, env, "show", "HEAD:sample.txt").stdout == "staged\n"
    assert (repo / "sample.txt").read_text(encoding="utf-8") == "unstaged\n"
    assert Path(installed["hooks_path"]).is_absolute()
    assert git(repo, env, "config", "--get", "core.hooksPath").stdout.strip() == installed["hooks_path"]
    assert list(state_root.rglob("staged")) == []
    details = doctor(repo, home, install_root, state_root)
    assert details["healthy"] is True
    assert details["hooks_path_matches"] is True
    assert details["runtime_available"] is True
    assert details["registry_available"] is True
    assert details["trusted_python_available"] is True
    assert Path(details["trusted_python"]).is_relative_to(repo) is False


def test_commit_gate_mutation_blocks_and_preserves_index_for_review(tmp_path: Path):
    home = tmp_path / "home"
    env = clean_env(home)
    repo = tmp_path / "repo"
    init_repo(repo, env)
    opt_in(repo, env)
    install_root, state_root, registry = paths(tmp_path)
    mutator = tmp_path / "mutator.py"
    marker = tmp_path / "unused.txt"
    mutator.write_text(
        "import json, os, pathlib, sys\n"
        "event = json.loads(os.environ['AGENT_RUNTIME_EVENT_JSON'])\n"
        "target = pathlib.Path(os.environ['AGENT_RUNTIME_REPO_ROOT']) / event['target_paths'][0]\n"
        "target.write_text('gate mutation\\n')\n",
        encoding="utf-8",
    )
    write_registry(
        registry,
        {"mutator": gate("before.commit", mutator, marker)},
    )
    install(repo, home, registry, install_root, state_root)
    original_head = git(repo, env, "rev-parse", "HEAD").stdout.strip()
    (repo / "sample.txt").write_text("candidate\n", encoding="utf-8")
    git(repo, env, "add", "sample.txt")

    result = git(repo, env, "commit", "-m", "must block", check=False)

    assert result.returncode != 0
    assert "restore-unapproved-mutation" in result.stderr
    assert git(repo, env, "rev-parse", "HEAD").stdout.strip() == original_head
    assert git(repo, env, "show", ":sample.txt").stdout == "candidate\n"
    assert (repo / "sample.txt").read_text(encoding="utf-8") == "candidate\n"


def test_real_git_lifecycle_hooks_map_to_standard_events(tmp_path: Path):
    home = tmp_path / "home"
    env = clean_env(home)
    repo = tmp_path / "repo"
    init_repo(repo, env)
    opt_in(repo, env)
    install_root, state_root, registry = paths(tmp_path)
    marker = tmp_path / "events.jsonl"
    capture = tmp_path / "capture_events.py"
    capture.write_text(
        "import json, os, pathlib, sys\n"
        "path = pathlib.Path(sys.argv[1])\n"
        "event = json.loads(os.environ['AGENT_RUNTIME_EVENT_JSON'])\n"
        "with path.open('a') as handle: handle.write(json.dumps({'type': event['event_type'], 'metadata': event['metadata']}) + '\\n')\n",
        encoding="utf-8",
    )
    event_types = [
        "before.commit",
        "before.commit-message",
        "after.commit",
        "after.checkout",
        "after.merge",
        "after.rewrite",
    ]
    write_registry(
        registry,
        {
            event_type: gate(event_type, capture, marker, failure_policy="diagnose")
            for event_type in event_types
        },
    )
    install(repo, home, registry, install_root, state_root)

    (repo / "sample.txt").write_text("commit\n", encoding="utf-8")
    git(repo, env, "add", "sample.txt")
    git(repo, env, "commit", "-qm", "lifecycle")
    git(repo, env, "checkout", "-qb", "topic")
    (repo / "topic.txt").write_text("topic\n", encoding="utf-8")
    git(repo, env, "add", "topic.txt")
    git(repo, env, "commit", "-qm", "topic")
    git(repo, env, "checkout", "-q", "main")
    git(repo, env, "merge", "--no-ff", "topic", "-m", "merge", check=True)
    git(repo, env, "commit", "--amend", "--no-edit", "-q")

    recorded = [json.loads(line) for line in marker.read_text(encoding="utf-8").splitlines()]
    seen = {entry["type"] for entry in recorded}
    assert set(event_types).issubset(seen)
    commit_message = next(entry for entry in recorded if entry["type"] == "before.commit-message")
    assert commit_message["metadata"]["commit_message_path"]
    checkout = next(entry for entry in recorded if entry["type"] == "after.checkout")
    assert len(checkout["metadata"]["hook_args"]) == 3


def test_real_push_caches_refs_handles_multi_delete_force_and_replays_approved_hooks(tmp_path: Path):
    home = tmp_path / "home"
    env = clean_env(home)
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    init_repo(repo, env)
    remote.mkdir()
    git(remote, env, "init", "--bare", "-q")
    git(repo, env, "remote", "add", "origin", str(remote))
    opt_in(repo, env)
    install_root, state_root, registry = paths(tmp_path)
    runtime_marker = tmp_path / "push-events.jsonl"
    chain_marker = tmp_path / "chains.jsonl"
    capture = tmp_path / "capture_push.py"
    capture.write_text(
        "import json, os, pathlib, sys\n"
        "event = json.loads(os.environ['AGENT_RUNTIME_EVENT_JSON'])\n"
        "stdin_path = pathlib.Path(event['metadata']['push_stdin_path'])\n"
        "record = {'refs': event['metadata']['refs'], 'stdin': stdin_path.read_text(), 'paths': event['target_paths']}\n"
        "with pathlib.Path(sys.argv[1]).open('a') as handle: handle.write(json.dumps(record) + '\\n')\n",
        encoding="utf-8",
    )
    write_registry(
        registry,
        {"push": gate("before.push", capture, runtime_marker)},
    )
    hooks: list[tuple[str, Path]] = []
    for order in (1, 2):
        hook = make_executable(
            tmp_path / f"approved-{order}",
            "#!/usr/bin/env python3\n"
            "import hashlib, json, pathlib, sys\n"
            "data = sys.stdin.buffer.read()\n"
            f"record = {{'order': {order}, 'sha256': hashlib.sha256(data).hexdigest(), 'argv': sys.argv[1:]}}\n"
            f"with pathlib.Path({str(chain_marker)!r}).open('a') as handle: handle.write(json.dumps(record) + '\\n')\n",
        )
        hooks.append(("pre-push", hook))
    install(repo, home, registry, install_root, state_root, hooks)

    git(repo, env, "push", "-u", "origin", "main")
    git(repo, env, "checkout", "-qb", "one")
    (repo / "one.txt").write_text("one\n", encoding="utf-8")
    git(repo, env, "add", "one.txt")
    git(repo, env, "commit", "-qm", "one")
    git(repo, env, "checkout", "-qb", "two", "main")
    (repo / "two.txt").write_text("two\n", encoding="utf-8")
    git(repo, env, "add", "two.txt")
    git(repo, env, "commit", "-qm", "two")
    git(repo, env, "push", "origin", "one", "two")
    git(repo, env, "push", "origin", ":one")
    old_two = git(repo, env, "rev-parse", "two").stdout.strip()
    git(repo, env, "checkout", "-q", "two")
    git(repo, env, "reset", "--hard", "main", "-q")
    (repo / "two.txt").write_text("rewritten\n", encoding="utf-8")
    git(repo, env, "add", "two.txt")
    git(repo, env, "commit", "-qm", "rewrite two")
    git(repo, env, "push", "--force", "origin", "two")

    events = [json.loads(line) for line in runtime_marker.read_text(encoding="utf-8").splitlines()]
    assert events[0]["refs"][0]["remote_oid"] == ZERO_OID
    multi = next(event for event in events if len(event["refs"]) == 2)
    assert {ref["remote_ref"] for ref in multi["refs"]} == {"refs/heads/one", "refs/heads/two"}
    deletion = next(
        event
        for event in events
        if any(ref["local_oid"] == ZERO_OID for ref in event["refs"])
    )
    assert any(ref["remote_ref"] == "refs/heads/one" for ref in deletion["refs"])
    forced = events[-1]["refs"][0]
    assert forced["remote_oid"] == old_two
    assert forced["force_update"] is True

    chains = [json.loads(line) for line in chain_marker.read_text(encoding="utf-8").splitlines()]
    assert len(chains) == len(events) * 2
    for event_record, first, second in zip(events, chains[::2], chains[1::2]):
        assert [first["order"], second["order"]] == [1, 2]
        assert first["sha256"] == second["sha256"]
        assert first["sha256"] == hashlib.sha256(event_record["stdin"].encode()).hexdigest()
        assert first["argv"] == second["argv"]
    assert list(state_root.rglob("pre-push-stdin.txt")) == []


def test_blocking_git_event_rejects_async_runtime_gate(tmp_path: Path):
    home = tmp_path / "home"
    env = clean_env(home)
    repo = tmp_path / "repo"
    init_repo(repo, env)
    opt_in(repo, env)
    install_root, state_root, registry = paths(tmp_path)
    noop = tmp_path / "noop.py"
    marker = tmp_path / "marker"
    noop.write_text("raise SystemExit(0)\n", encoding="utf-8")
    async_gate = gate("before.push", noop, marker, failure_policy="diagnose")
    async_gate["mode"] = "async"
    write_registry(registry, {"async-push": async_gate})

    result = dispatcher_cli(
        repo,
        home,
        install_root,
        state_root,
        "install",
        "--registry",
        str(registry),
        check=False,
    )

    assert result.returncode != 0
    assert "must run synchronously" in result.stderr
    assert git(repo, env, "config", "--get", "core.hooksPath", check=False).returncode == 1


def test_multiple_runtime_gate_failures_are_aggregated_without_overwrite(tmp_path: Path):
    home = tmp_path / "home"
    env = clean_env(home)
    repo = tmp_path / "repo"
    init_repo(repo, env)
    opt_in(repo, env)
    install_root, state_root, registry = paths(tmp_path)
    gates: dict[str, object] = {}
    for index in (1, 2):
        failing = tmp_path / f"fail-{index}.py"
        marker = tmp_path / f"marker-{index}"
        failing.write_text(
            f"import sys\nprint('failure-{index}', file=sys.stderr)\nraise SystemExit({index + 2})\n",
            encoding="utf-8",
        )
        gates[f"failure-{index}"] = gate("before.commit", failing, marker)
    write_registry(registry, gates)
    installed = install(repo, home, registry, install_root, state_root)
    (repo / "sample.txt").write_text("candidate\n", encoding="utf-8")
    git(repo, env, "add", "sample.txt")

    result = run(
        [str(Path(installed["hooks_path"]) / "pre-commit")],
        cwd=repo,
        env=env,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    payload = json.loads(result.stderr)
    runtime_diagnostics = [
        item for item in payload["diagnostics"] if item["source"] == "runtime"
    ]
    assert len(runtime_diagnostics) == 2
    assert {item["gate_id"] for item in runtime_diagnostics} == {
        "failure-1",
        "failure-2",
    }


def test_unknown_repository_hook_is_inventoried_but_never_executed(tmp_path: Path):
    home = tmp_path / "home"
    env = clean_env(home)
    repo = tmp_path / "repo"
    init_repo(repo, env)
    opt_in(repo, env, "generic")
    install_root, state_root, registry = paths(tmp_path)
    write_registry(registry)
    marker = tmp_path / "unknown-ran"
    repo_hooks = repo / "repo-hooks"
    make_executable(
        repo_hooks / "pre-commit",
        f"#!/usr/bin/env bash\ntouch {marker}\n",
    )
    git(repo, env, "config", "core.hooksPath", "repo-hooks")

    inventory = dispatcher_cli(
        repo,
        home,
        install_root,
        state_root,
        "inventory",
    )
    data = json.loads(inventory.stdout)
    assert data["hooks"][0]["classification"] == "repository-self-hook"
    rejected = dispatcher_cli(
        repo,
        home,
        install_root,
        state_root,
        "install",
        "--registry",
        str(registry),
        "--approve-hook",
        f"pre-commit={repo_hooks / 'pre-commit'}",
        check=False,
    )
    assert rejected.returncode != 0
    assert "repository self hook cannot be approved" in rejected.stderr
    install(repo, home, registry, install_root, state_root)
    (repo / "sample.txt").write_text("next\n", encoding="utf-8")
    git(repo, env, "add", "sample.txt")
    git(repo, env, "commit", "-qm", "safe")

    assert marker.exists() is False


def test_install_rejects_repository_controlled_python_interpreter(tmp_path: Path):
    home = tmp_path / "home"
    env = clean_env(home)
    repo = tmp_path / "repo"
    init_repo(repo, env)
    opt_in(repo, env, "generic")
    install_root, state_root, registry = paths(tmp_path)
    write_registry(registry)
    repository_python = make_executable(
        repo / "python3",
        "#!/usr/bin/env bash\nexec /opt/homebrew/bin/python3 \"$@\"\n",
    )

    result = dispatcher_cli(
        repo,
        home,
        install_root,
        state_root,
        "--python",
        str(repository_python),
        "install",
        "--registry",
        str(registry),
        check=False,
    )

    assert result.returncode != 0
    assert "outside the repository worktree" in result.stderr
    assert git(repo, env, "config", "--get", "core.hooksPath", check=False).returncode == 1


def test_registry_rejects_repository_controlled_gate_command(tmp_path: Path):
    home = tmp_path / "home"
    env = clean_env(home)
    repo = tmp_path / "repo"
    init_repo(repo, env)
    opt_in(repo, env)
    install_root, state_root, registry = paths(tmp_path)
    repository_script = repo / "gate.py"
    repository_script.write_text("raise SystemExit(0)\n", encoding="utf-8")
    marker = tmp_path / "marker"
    write_registry(
        registry,
        {"repo-gate": gate("before.commit", repository_script, marker)},
    )

    result = dispatcher_cli(
        repo,
        home,
        install_root,
        state_root,
        "install",
        "--registry",
        str(registry),
        check=False,
    )

    assert result.returncode != 0
    assert "references repository-controlled path" in result.stderr
    assert git(repo, env, "config", "--get", "core.hooksPath", check=False).returncode == 1


def test_install_root_cannot_switch_to_a_different_state_root(tmp_path: Path):
    home = tmp_path / "home"
    env = clean_env(home)
    first_repo = tmp_path / "first"
    second_repo = tmp_path / "second"
    init_repo(first_repo, env)
    init_repo(second_repo, env)
    opt_in(first_repo, env, "generic")
    opt_in(second_repo, env, "generic")
    install_root, state_root, registry = paths(tmp_path)
    write_registry(registry)
    install(first_repo, home, registry, install_root, state_root)

    result = dispatcher_cli(
        second_repo,
        home,
        install_root,
        tmp_path / "other-state",
        "install",
        "--registry",
        str(registry),
        check=False,
    )

    assert result.returncode != 0
    assert "different trusted state_root" in result.stderr
    assert doctor(first_repo, home, install_root, state_root)["healthy"] is True


def test_doctor_accepts_shared_bundle_upgrade_with_same_state_root(tmp_path: Path):
    home = tmp_path / "home"
    env = clean_env(home)
    repo = tmp_path / "repo"
    init_repo(repo, env)
    opt_in(repo, env, "generic")
    install_root, state_root, registry = paths(tmp_path)
    write_registry(registry)
    installed = install(repo, home, registry, install_root, state_root)
    record_path = Path(installed["installation_record"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["release"] = str(install_root / "releases" / "older-release")
    record_path.write_text(json.dumps(record), encoding="utf-8")

    details = doctor(repo, home, install_root, state_root)

    assert details["healthy"] is True
    assert details["bundle_matches_record"] is False
    assert details["bundle_state_matches_record"] is True


def test_bypass_requires_reason_is_audited_and_fails_closed_when_audit_is_unwritable(tmp_path: Path):
    home = tmp_path / "home"
    env = clean_env(home)
    repo = tmp_path / "repo"
    init_repo(repo, env)
    opt_in(repo, env)
    install_root, state_root, registry = paths(tmp_path)
    failing = tmp_path / "fail.py"
    marker = tmp_path / "unused"
    failing.write_text("raise SystemExit(9)\n", encoding="utf-8")
    write_registry(
        registry,
        {"fail": gate("before.commit", failing, marker)},
    )
    install(repo, home, registry, install_root, state_root)
    (repo / "sample.txt").write_text("candidate\n", encoding="utf-8")
    git(repo, env, "add", "sample.txt")

    missing_reason = git(
        repo,
        clean_env(home, {"QUALITY_GATES_BYPASS": "1"}),
        "commit",
        "-m",
        "missing reason",
        check=False,
    )
    assert missing_reason.returncode != 0
    assert "QUALITY_GATES_BYPASS_REASON" in missing_reason.stderr

    bypass_env = clean_env(
        home,
        {
            "QUALITY_GATES_BYPASS": "1",
            "QUALITY_GATES_BYPASS_REASON": "incident recovery",
        },
    )
    committed = git(repo, bypass_env, "commit", "-m", "bypassed", check=False)
    assert committed.returncode == 0
    details = doctor(repo, home, install_root, state_root)
    audit_path = Path(details["bypass_audit_path"])
    records = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
    ]
    assert {record["event_type"] for record in records[-2:]} == {
        "before.commit",
        "before.commit-message",
    }
    pre_commit_record = next(
        record for record in records if record["event_type"] == "before.commit"
    )
    assert pre_commit_record["reason"] == "incident recovery"
    assert pre_commit_record["profile"] == "test"
    assert pre_commit_record["target_paths"] == ["sample.txt"]

    (repo / "sample.txt").write_text("next\n", encoding="utf-8")
    git(repo, env, "add", "sample.txt")
    audit_path.chmod(0o400)
    try:
        blocked = git(repo, bypass_env, "commit", "-m", "audit blocked", check=False)
    finally:
        audit_path.chmod(0o600)
    assert blocked.returncode != 0
    assert "bypass audit" in blocked.stderr.lower()


def test_missing_runtime_fails_closed_for_blocking_hook_and_only_diagnoses_post_hook(tmp_path: Path):
    home = tmp_path / "home"
    env = clean_env(home)
    repo = tmp_path / "repo"
    init_repo(repo, env)
    opt_in(repo, env, "generic")
    install_root, state_root, registry = paths(tmp_path)
    write_registry(registry)
    installed = install(repo, home, registry, install_root, state_root)
    runtime = install_root / "current" / "lib" / "agent_runtime.py"
    runtime.unlink()
    (repo / "sample.txt").write_text("candidate\n", encoding="utf-8")
    git(repo, env, "add", "sample.txt")

    pre_commit = run(
        [str(Path(installed["hooks_path"]) / "pre-commit")],
        cwd=repo,
        env=env,
        check=False,
    )
    post_commit = run(
        [str(Path(installed["hooks_path"]) / "post-commit")],
        cwd=repo,
        env=env,
        check=False,
    )

    assert pre_commit.returncode == 1
    pre_payload = json.loads(pre_commit.stderr)
    assert pre_payload["status"] == "blocked"
    assert pre_payload["diagnostics"][0]["source"] == "runtime"
    assert post_commit.returncode == 0
    post_payload = json.loads(post_commit.stderr)
    assert post_payload["status"] == "diagnosed"
    assert post_payload["diagnostics"][0]["source"] == "runtime"
    details = doctor(repo, home, install_root, state_root)
    assert details["healthy"] is False
    assert details["runtime_available"] is False


def test_approved_hook_exit_code_and_failure_source_are_preserved_with_bounded_output(tmp_path: Path):
    home = tmp_path / "home"
    env = clean_env(home)
    repo = tmp_path / "repo"
    init_repo(repo, env)
    opt_in(repo, env, "generic")
    install_root, state_root, registry = paths(tmp_path)
    write_registry(registry)
    hook = make_executable(
        tmp_path / "approved-fail",
        "#!/usr/bin/env python3\nimport sys\nprint('legacy failed ' + 'x' * 8000, file=sys.stderr)\nraise SystemExit(42)\n",
    )
    installed = install(
        repo,
        home,
        registry,
        install_root,
        state_root,
        [("pre-push", hook)],
    )
    pre_push = Path(installed["hooks_path"]) / "pre-push"
    line = f"refs/heads/main {git(repo, env, 'rev-parse', 'HEAD').stdout.strip()} refs/heads/main {ZERO_OID}\n"

    result = run(
        [str(pre_push), "origin", "example://remote"],
        cwd=repo,
        env=env,
        input_text=line,
        check=False,
    )

    assert result.returncode == 42
    assert result.stdout == ""
    assert len(result.stderr.encode("utf-8")) <= 4096
    payload = json.loads(result.stderr)
    assert payload["status"] == "blocked"
    assert payload["diagnostics"][0]["source"].startswith("approved-hook:")
    assert payload["diagnostics"][0]["exit_code"] == 42
    assert payload["diagnostics"][0]["log_ref"]


def test_install_uninstall_restores_previous_hooks_path_and_invalid_install_is_atomic(tmp_path: Path):
    home = tmp_path / "home"
    env = clean_env(home)
    repo = tmp_path / "repo"
    init_repo(repo, env)
    opt_in(repo, env, "generic")
    install_root, state_root, registry = paths(tmp_path)
    write_registry(registry)
    git(repo, env, "config", "core.hooksPath", "legacy-hooks")

    invalid = dispatcher_cli(
        repo,
        home,
        install_root,
        state_root,
        "install",
        "--registry",
        str(tmp_path / "missing.json"),
        check=False,
    )
    assert invalid.returncode != 0
    assert git(repo, env, "config", "--get", "core.hooksPath").stdout.strip() == "legacy-hooks"

    installed = install(repo, home, registry, install_root, state_root)
    record_path = Path(installed["installation_record"])
    assert record_path.exists()
    record_before = record_path.read_bytes()
    hooks_path_before = git(repo, env, "config", "--get", "core.hooksPath").stdout.strip()

    for failure_point in ("before-state-transaction", "after-state-swap"):
        interrupted = dispatcher_cli(
            repo,
            home,
            install_root,
            state_root,
            "install",
            "--registry",
            str(registry),
            check=False,
            extra_env={
                "AGENT_RUNTIME_TESTING": "1",
                "AGENT_RUNTIME_INSTALL_FAIL_AT": failure_point,
            },
        )
        assert interrupted.returncode != 0
        assert "simulated install failure" in interrupted.stderr
        assert record_path.read_bytes() == record_before
        assert git(repo, env, "config", "--get", "core.hooksPath").stdout.strip() == hooks_path_before

    removed = dispatcher_cli(
        repo,
        home,
        install_root,
        state_root,
        "uninstall",
    )
    assert removed.stderr == ""
    payload = json.loads(removed.stdout)
    assert payload["restored_hooks_path"] == "legacy-hooks"
    assert git(repo, env, "config", "--get", "core.hooksPath").stdout.strip() == "legacy-hooks"
    assert Path(installed["installation_record"]).exists() is False


def test_inventory_identifies_unapproved_git_lfs_hook(tmp_path: Path):
    home = tmp_path / "home"
    env = clean_env(home)
    repo = tmp_path / "repo"
    init_repo(repo, env)
    install_root, state_root, _ = paths(tmp_path)
    hooks_dir = Path(git(repo, env, "rev-parse", "--git-path", "hooks").stdout.strip())
    if not hooks_dir.is_absolute():
        hooks_dir = repo / hooks_dir
    make_executable(
        hooks_dir / "pre-push",
        "#!/usr/bin/env bash\ngit lfs pre-push \"$@\"\n",
    )

    result = dispatcher_cli(
        repo,
        home,
        install_root,
        state_root,
        "inventory",
    )
    payload = json.loads(result.stdout)

    hook = next(item for item in payload["hooks"] if item["event"] == "pre-push")
    assert hook["classification"] == "git-lfs"
    assert hook["approved"] is False
    assert hook["sha256"].startswith("sha256:")
