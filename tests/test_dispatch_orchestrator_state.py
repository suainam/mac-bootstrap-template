"""Tests for the orchestrator brain state store — TB-01.

The behaviours asserted here are the ones that remove orchestration
antipatterns: a brain state that is queryable, a park that cannot be roused by a
todo reminder, and a human gate that no automatic path can cross.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(
    0, str(REPO_ROOT / "multiplexer" / "herdr-dispatch" / "lib")
)

import orchestrator_state as brain  # noqa: E402


@pytest.fixture()
def state_path(tmp_path: Path) -> Path:
    return tmp_path / ".git" / "dispatch" / "ORCHESTRATOR_STATE.json"


# --------------------------------------------------------------------------
# Path anchoring
# --------------------------------------------------------------------------


def test_state_path_anchors_on_git_common_dir(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "a.txt").write_text("a\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)

    main_state = brain.state_path(repo)
    assert main_state.parent.name == "dispatch"
    assert main_state.name == "ORCHESTRATOR_STATE.json"
    assert ".git" in main_state.parts

    # A linked worktree must resolve to the same file, otherwise the brain
    # splits in two.
    worktree = tmp_path / "wt"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "wt", str(worktree)],
        check=True,
    )
    assert brain.state_path(worktree) == main_state


def test_state_path_falls_back_without_git(tmp_path: Path) -> None:
    resolved = brain.state_path(tmp_path)
    assert resolved == tmp_path / ".dispatch" / "ORCHESTRATOR_STATE.json"


# --------------------------------------------------------------------------
# Schema 2 = expand of schema 1
# --------------------------------------------------------------------------


def test_default_state_is_schema_2_with_brain_fields() -> None:
    state = brain.default_state("task-1")
    assert state["schema"] == 2
    assert state["task_id"] == "task-1"
    assert state["orchestrator_phase"] == "contract"
    assert set(state["brain"]) == {
        "entered_phase_unix_ms",
        "awaiting_lanes",
        "notifications_seen",
    }
    assert state["active_panes"] == {"orchestrator": "", "lanes": {}}


def test_schema_1_fields_survive_upgrade() -> None:
    legacy = {
        "schema": 1,
        "task_id": "t-9",
        "phase": "writer_implementation",
        "review_round": 2,
        "max_review_rounds": 3,
        "lanes": {"1-1": {"pane": "w3:p5", "status": "working"}},
        "known_facts": {"probe": "done"},
        "awaiting_human_gate": True,
        "extra_data": {"note": "keep me"},
    }
    state = brain.normalise(legacy)
    assert state["schema"] == 2
    for key in (
        "task_id",
        "phase",
        "review_round",
        "max_review_rounds",
        "known_facts",
        "awaiting_human_gate",
        "extra_data",
    ):
        assert state[key] == legacy[key], key
    assert state["lanes"]["1-1"]["status"] == "working"
    assert state["orchestrator_phase"] == "contract"


def test_unknown_schema_is_refused() -> None:
    with pytest.raises(brain.StateError):
        brain.normalise({"schema": 99})


def test_invalid_brain_phase_is_refused_not_defaulted(tmp_path: Path) -> None:
    """A wrong brain state must never look authoritative."""
    path = tmp_path / "state.json"
    brain.save(path, brain.default_state())
    path.write_text(json.dumps({"schema": 2, "orchestrator_phase": "vibes"}))

    with pytest.raises(brain.BrainPhaseError):
        brain.load(path)


# --------------------------------------------------------------------------
# Brain loop transitions
# --------------------------------------------------------------------------


def test_full_closed_loop() -> None:
    state = brain.default_state()
    brain.advance(state, "topology")
    brain.park(state, ["1-1", "1-2"], orchestrator_pane="w3:p1")
    assert brain.is_parked(state)
    brain.wake(state, signal="notify", lane="1-1")
    assert state["orchestrator_phase"] == "synthesis"
    brain.advance(state, "decision")
    brain.advance(state, "human_gate")
    brain.advance(state, "closed", wake_signal="human")
    assert state["orchestrator_phase"] == "closed"


def test_park_records_what_and_why() -> None:
    """Recording the wait is what stops improvised work."""
    state = brain.default_state()
    brain.advance(state, "topology")
    brain.park(state, ["1-1"], orchestrator_pane="w3:p1")

    assert state["orchestrator_phase"] == "yield_and_guard"
    assert state["brain"]["awaiting_lanes"] == ["1-1"]
    assert "w3:p1" in state["blocked_reason"]
    assert "NOTIFY" in state["blocked_reason"]
    assert state["active_panes"]["orchestrator"] == "w3:p1"
    assert state["active_panes"]["lanes"]["__orchestrator__"]["role"] == "orchestrator"


def test_reparking_merges_awaiting_lanes() -> None:
    """A second wave must not blind the orchestrator to the first."""
    state = brain.default_state()
    brain.advance(state, "topology")
    brain.park(state, ["1-1"], orchestrator_pane="w3:p1")
    brain.park(state, ["1-2"], orchestrator_pane="w3:p1")
    assert state["brain"]["awaiting_lanes"] == ["1-1", "1-2"]

    brain.park(state, ["1-2"], orchestrator_pane="w3:p1")  # idempotent
    assert state["brain"]["awaiting_lanes"] == ["1-1", "1-2"]


def test_todo_reminder_cannot_rouse_the_park() -> None:
    """The false-busywork guard: only a real wake signal leaves the park."""
    state = brain.default_state()
    brain.advance(state, "topology")
    brain.park(state, ["1-1"], orchestrator_pane="w3:p1")

    for bogus in (None, "", "todo_reminder", "reminder", "poll"):
        with pytest.raises(brain.BrainPhaseError):
            brain.advance(state, "synthesis", wake_signal=bogus)

    assert state["orchestrator_phase"] == "yield_and_guard"


def test_stall_alarm_is_a_valid_wake_signal() -> None:
    state = brain.default_state()
    brain.advance(state, "topology")
    brain.park(state, ["1-1"])
    brain.advance(state, "synthesis", wake_signal="stall_alarm")
    assert state["orchestrator_phase"] == "synthesis"


def test_wake_counts_notifications_and_clears_lane() -> None:
    state = brain.default_state()
    brain.advance(state, "topology")
    brain.park(state, ["1-1", "1-2"], orchestrator_pane="w3:p1")

    brain.wake(state, signal="notify", lane="1-1")
    assert state["brain"]["notifications_seen"] == 1
    assert state["brain"]["awaiting_lanes"] == ["1-2"]
    assert state["orchestrator_phase"] == "synthesis"


def test_wake_rejects_unknown_signal() -> None:
    state = brain.default_state()
    with pytest.raises(brain.BrainPhaseError):
        brain.wake(state, signal="because")


def test_human_gate_requires_human_authorisation() -> None:
    """No automatic path may publish."""
    state = brain.default_state()
    brain.advance(state, "topology")
    brain.park(state, [])
    brain.wake(state, signal="notify")
    brain.advance(state, "decision")
    brain.advance(state, "human_gate")

    for automatic in (None, "notify", "stall_alarm"):
        with pytest.raises(brain.BrainPhaseError):
            brain.advance(state, "closed", wake_signal=automatic)

    assert state["orchestrator_phase"] == "human_gate"
    brain.advance(state, "closed", wake_signal="human")
    assert state["orchestrator_phase"] == "closed"


def test_human_gate_can_reject_back_to_synthesis() -> None:
    state = brain.default_state()
    brain.advance(state, "topology")
    brain.park(state, [])
    brain.wake(state, signal="notify")
    brain.advance(state, "decision")
    brain.advance(state, "human_gate")
    brain.advance(state, "synthesis", wake_signal="human")
    assert state["orchestrator_phase"] == "synthesis"


def test_illegal_skips_are_refused() -> None:
    state = brain.default_state()
    with pytest.raises(brain.BrainPhaseError):
        brain.advance(state, "human_gate")  # contract -> human_gate
    with pytest.raises(brain.BrainPhaseError):
        brain.advance(state, "nonexistent")


def test_closed_is_terminal() -> None:
    state = brain.default_state()
    brain.advance(state, "topology")
    brain.park(state, [])
    brain.wake(state, signal="notify")
    brain.advance(state, "decision")
    brain.advance(state, "human_gate")
    brain.advance(state, "closed", wake_signal="human")
    with pytest.raises(brain.BrainPhaseError):
        brain.advance(state, "contract", wake_signal="human")


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


def test_roundtrip_preserves_brain_state(state_path: Path) -> None:
    state = brain.default_state("t-1")
    brain.advance(state, "topology")
    brain.park(state, ["1-1"], orchestrator_pane="w3:p1")
    brain.save(state_path, state)

    reloaded = brain.load(state_path)
    assert reloaded["orchestrator_phase"] == "yield_and_guard"
    assert reloaded["brain"]["awaiting_lanes"] == ["1-1"]
    assert reloaded["blocked_reason"] == state["blocked_reason"]
    assert reloaded["active_panes"]["orchestrator"] == "w3:p1"


def test_write_is_atomic_and_leaves_no_temp_files(state_path: Path) -> None:
    brain.save(state_path, brain.default_state())
    brain.save(state_path, brain.default_state("t-2"))
    leftovers = [p.name for p in state_path.parent.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []
    assert brain.load(state_path)["task_id"] == "t-2"


def test_failed_write_leaves_previous_document_intact(
    state_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    brain.save(state_path, brain.default_state("original"))

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        brain.save(state_path, brain.default_state("replacement"))
    monkeypatch.undo()

    assert brain.load(state_path)["task_id"] == "original"
    assert [p.name for p in state_path.parent.iterdir() if p.suffix == ".tmp"] == []


def test_missing_state_returns_defaults(tmp_path: Path) -> None:
    assert brain.load(tmp_path / "nope.json")["schema"] == 2


def test_corrupt_state_raises(tmp_path: Path) -> None:
    bad = tmp_path / "state.json"
    bad.write_text("{not json")
    with pytest.raises(brain.StateError):
        brain.load(bad)


# --------------------------------------------------------------------------
# Field-partitioned concurrent writes
# --------------------------------------------------------------------------


def test_lane_writers_are_partitioned(state_path: Path) -> None:
    """Plugin and extension own disjoint lane fields; neither may cross over."""
    brain.save(state_path, brain.default_state())

    brain.update_lane(
        state_path, "1-1", {"status": "working", "tokens": {"lane": "1-1"}}, writer="plugin"
    )
    brain.update_lane(
        state_path, "1-1", {"phase": "research", "notified_at": 1234}, writer="extension"
    )

    lane = brain.load(state_path)["lanes"]["1-1"]
    assert lane["status"] == "working"
    assert lane["tokens"] == {"lane": "1-1"}
    assert lane["phase"] == "research"
    assert lane["notified_at"] == 1234

    with pytest.raises(brain.StateError):
        brain.update_lane(state_path, "1-1", {"phase": "x"}, writer="plugin")
    with pytest.raises(brain.StateError):
        brain.update_lane(state_path, "1-1", {"status": "x"}, writer="extension")


def test_concurrent_writers_do_not_lose_fields(state_path: Path) -> None:
    """The real failure this prevents: read-modify-write clobbering."""
    brain.save(state_path, brain.default_state())
    errors: list[BaseException] = []

    def plugin_writer() -> None:
        try:
            for _ in range(12):
                brain.update_lane(
                    state_path,
                    "1-1",
                    {"status": "working", "pane_id": "w3:p5"},
                    writer="plugin",
                )
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    def extension_writer() -> None:
        try:
            for _ in range(12):
                brain.update_lane(
                    state_path,
                    "1-1",
                    {"phase": "research", "handoff": "~/h.md"},
                    writer="extension",
                )
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=plugin_writer), threading.Thread(target=extension_writer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    lane = brain.load(state_path)["lanes"]["1-1"]
    # Neither side's fields may vanish because the other rewrote the document.
    assert lane["status"] == "working"
    assert lane["pane_id"] == "w3:p5"
    assert lane["phase"] == "research"
    assert lane["handoff"] == "~/h.md"


def test_stale_lock_is_taken_over(state_path: Path) -> None:
    brain.save(state_path, brain.default_state())
    lock = state_path.parent / brain.LOCK_FILE_NAME
    lock.write_text("999999 0\n")
    old = brain.time.time() - (brain.DEFAULT_LOCK_STALE_SECONDS + 60)
    os.utime(lock, (old, old))

    state = brain.load(state_path)
    brain.save(state_path, state)  # must not wedge
    assert not lock.exists()


def test_lock_timeout_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    lock = tmp_path / brain.LOCK_FILE_NAME
    lock.write_text("1 0\n")
    with pytest.raises(brain.LockTimeout):
        with brain.state_lock(path, timeout=0.2, stale_after=10_000):
            pass  # pragma: no cover


# --------------------------------------------------------------------------
# Migration
# --------------------------------------------------------------------------


def test_migration_plan_is_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy_dir = tmp_path / ".omp" / "dispatch-omp" / "run-1"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "state.json").write_text(
        json.dumps({"schema": 1, "lanes": {"1-1": {"pane": "w3:p5", "status": "working"}}})
    )

    plan = brain.migration_plan(tmp_path)
    assert plan["sources"], plan
    assert plan["sources"][0]["lane_count"] == 1
    assert not plan["target_exists"]


def test_migration_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy_dir = tmp_path / ".omp" / "dispatch-fleet" / "run-7"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "state.json").write_text(
        json.dumps({"schema": 1, "lanes": {"2-1": {"pane": "w3:p4", "phase": "research"}}})
    )
    target = tmp_path / ".dispatch" / "ORCHESTRATOR_STATE.json"

    assert brain.main(["migrate", "--repo", str(tmp_path)]) == 0
    first = brain.load(target)["lanes"]
    assert first["2-1"]["pane"] == "w3:p4"

    assert brain.main(["migrate", "--repo", str(tmp_path)]) == 0
    assert brain.load(target)["lanes"] == first


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_park_wake_roundtrip(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    assert brain.main(["advance", "--repo", str(repo), "--to", "topology"]) == 0
    assert (
        brain.main(
            ["park", "--repo", str(repo), "--pane", "w3:p1", "--lane", "1-1"]
        )
        == 0
    )
    capsys.readouterr()

    assert brain.main(["show", "--repo", str(repo), "--brain"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["orchestrator_phase"] == "yield_and_guard"
    assert out["parked"] is True

    assert brain.main(["wake", "--repo", str(repo), "--lane", "1-1"]) == 0
    capsys.readouterr()
    assert brain.main(["show", "--repo", str(repo), "--brain"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["orchestrator_phase"] == "synthesis"
    assert out["brain"]["notifications_seen"] == 1


def test_cli_refuses_reminder_driven_advance(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    brain.main(["advance", "--repo", str(repo), "--to", "topology"])
    brain.main(["park", "--repo", str(repo), "--pane", "w3:p1"])

    exit_code = brain.main(
        ["advance", "--repo", str(repo), "--to", "synthesis", "--wake-signal", "todo_reminder"]
    )
    assert exit_code == 2


def test_cli_path(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    assert brain.main(["path", "--repo", str(repo)]) == 0
    assert capsys.readouterr().out.strip().endswith("dispatch/ORCHESTRATOR_STATE.json")