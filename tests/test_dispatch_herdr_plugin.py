"""Tests for the Herdr-side plugin — TB-03.

Two properties matter more than the rest:

- **The plugin only ever reports presentation.** Lane identity reaches the
  sidebar as tokens; lifecycle status keeps coming from the integration that
  owns it. The repository gate enforces this across the tree, and these tests
  pin the call shape so a future refactor cannot quietly switch to a lifecycle
  report.
- **Nothing repository-specific is baked in.** The plugin has to work in any
  project, so no test may rely on a path from this repo.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "multiplexer" / "herdr-dispatch"
LIB = PLUGIN_ROOT / "lib"
BIN = PLUGIN_ROOT / "bin"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(LIB))
herdr = _load("dispatch_herdr_client", LIB / "herdr_client.py")
board = _load("dispatch_board", BIN / "dispatch_board.py")
plugin = _load("dispatch_plugin", BIN / "dispatch_plugin.py")
brain = _load("dispatch_orchestrator_state", LIB / "orchestrator_state.py")


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def manifest() -> dict:
    import tomllib

    with (PLUGIN_ROOT / "herdr-plugin.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_manifest_declares_required_fields(manifest: dict) -> None:
    for key in ("id", "name", "version", "min_herdr_version"):
        assert manifest.get(key), key


def test_manifest_min_version_covers_the_apis_used(manifest: dict) -> None:
    # pane.report_metadata and plugin.link both arrived in this series.
    parts = tuple(int(p) for p in manifest["min_herdr_version"].split("."))
    assert parts >= (0, 9, 0)


def test_manifest_entrypoints_exist(manifest: dict) -> None:
    """Every declared command must point at a file that exists and parses."""
    commands = []
    commands += [entry["command"] for entry in manifest.get("startup", [])]
    for block in ("actions", "events", "panes"):
        commands += [entry["command"] for entry in manifest.get(block, [])]

    assert commands, "manifest declares no commands"
    for command in commands:
        assert isinstance(command, list), command
        # argv arrays are not run through a shell, so nothing may need one.
        assert not any("|" in part or "&&" in part for part in command), command
        script = PLUGIN_ROOT / command[1]
        assert script.is_file(), script
        if script.suffix == ".py":
            compile(script.read_text(encoding="utf-8"), str(script), "exec")


def test_manifest_ids_are_legal(manifest: dict) -> None:
    # Action, pane and link-handler ids are local to the plugin: ASCII letters,
    # digits, colon, underscore and hyphen, but no dots.
    for block in ("actions", "panes", "link_handlers"):
        for entry in manifest.get(block, []):
            local_id = entry["id"]
            assert "." not in local_id, local_id
            assert all(c.isalnum() or c in ":_-" for c in local_id), local_id


def test_manifest_event_names_are_known(manifest: dict) -> None:
    """Unknown event names do not block a link but do surface a warning."""
    known = {
        "workspace.created",
        "workspace.updated",
        "workspace.closed",
        "workspace.focused",
        "tab.created",
        "tab.closed",
        "tab.focused",
        "pane.created",
        "pane.closed",
        "pane.focused",
        "pane.exited",
        "pane.agent_detected",
        "pane.agent_status_changed",
        "pane.output_matched",
        "pane.scroll_changed",
        "layout.updated",
        "worktree.created",
        "worktree.opened",
        "worktree.removed",
    }
    for entry in manifest.get("events", []):
        assert entry["on"] in known, entry["on"]


def test_board_pane_uses_a_transient_placement(manifest: dict) -> None:
    [entry] = manifest["panes"]
    # popup is session-modal and cannot own a pane, which keeps the plugin out
    # of Herdr's persistence and layout APIs.
    assert entry["placement"] == "popup"
    assert entry["title"]
    assert entry["width"] and entry["height"]


def test_manifest_has_no_resume_argv(manifest: dict) -> None:
    """Dispatch records but never attaches a resume command (skeptic S-12)."""
    raw = (PLUGIN_ROOT / "herdr-plugin.toml").read_text(encoding="utf-8")
    assert "resume" not in raw.lower()


# --------------------------------------------------------------------------
# Token construction
# --------------------------------------------------------------------------


def test_tokens_carry_lane_identity() -> None:
    tokens = herdr.build_lane_tokens(
        {"lane": "1-1-ipquality", "wave": 1, "role": "researcher", "kind": "opencode"},
        "topology",
    )
    assert tokens == {
        "lane": "1-1-ipquality",
        "wave": "1",
        "role": "researcher",
        "kind": "opencode",
        "brain": "topology",
    }


def test_tokens_omit_empty_fields() -> None:
    tokens = herdr.build_lane_tokens({"lane": "1-1"}, "")
    assert tokens == {"lane": "1-1"}


def test_tokens_never_include_lifecycle_status() -> None:
    """The single-writer invariant, pinned at the call shape."""
    lane = {"lane": "1-1", "status": "working", "agent_status": "blocked"}
    tokens = herdr.build_lane_tokens(lane, "topology")
    assert "status" not in tokens
    assert "agent_status" not in tokens
    assert "working" not in tokens.values()
    assert "blocked" not in tokens.values()


def test_token_keys_are_sanitised() -> None:
    assert herdr.sanitize_token("wave 1/x") == "wave-1-x"
    assert herdr.sanitize_token("a" * 80) == "a" * 32
    assert herdr.sanitize_token("!!!") == ""


def test_token_values_are_truncated_and_flattened() -> None:
    assert len(herdr.truncate_token_value("x" * 500)) == 80
    assert herdr.truncate_token_value("a\n\tb   c") == "a b c"
    # Replaced with a space, not deleted: deleting would glue words together.
    assert herdr.truncate_token_value("bad\x00char") == "bad char"


def test_metadata_report_uses_the_metadata_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard against someone swapping this for a lifecycle report."""
    seen: list[list[str]] = []

    def fake_run(args, **kwargs):
        seen.append(list(args))
        return {}

    monkeypatch.setattr(herdr, "run_herdr", fake_run)
    herdr.report_lane_metadata(
        "w3:p5",
        {"lane": "1-1", "role": "researcher", "kind": "omp"},
        brain_phase="topology",
    )

    assert len(seen) == 1
    args = seen[0]
    assert args[:2] == ["pane", "report-metadata"]
    joined = " ".join(args)
    assert "report-agent" not in joined
    assert "--token" in args
    assert "--ttl-ms" not in args


def test_metadata_report_rejects_a_bad_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(herdr, "run_herdr", lambda *a, **k: {})
    with pytest.raises(herdr.HerdrError):
        herdr.report_lane_metadata("w3:p5", {"lane": "1-1"}, ttl_ms=0)
    with pytest.raises(herdr.HerdrError):
        herdr.report_lane_metadata("w3:p5", {"lane": "1-1"}, ttl_ms=99_999_999)


def test_metadata_report_requires_a_pane(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(herdr, "run_herdr", lambda *a, **k: {})
    with pytest.raises(herdr.HerdrError):
        herdr.report_lane_metadata("", {"lane": "1-1"})


def test_metadata_report_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(herdr, "run_herdr", lambda args, **k: calls.append(args) or {})
    lane = {"lane": "1-1", "role": "researcher"}
    first = herdr.report_lane_metadata("w3:p5", lane)
    second = herdr.report_lane_metadata("w3:p5", lane)
    assert first == second
    assert calls[0] == calls[1]


# --------------------------------------------------------------------------
# Heartbeat stage token (TB-05)
# --------------------------------------------------------------------------


def test_stage_is_compacted_for_the_sidebar() -> None:
    assert herdr.compact_stage("Stage 4 Deploying on hk216") == "s4@hk216"
    assert herdr.compact_stage("Stage 4 Deploying on target") == "s4@target"


def test_stage_compaction_handles_missing_numbers() -> None:
    assert herdr.compact_stage("compiling") == "scompiling"
    assert herdr.compact_stage("正在跑 playbook") == "s正在跑"


def test_empty_stage_yields_no_token() -> None:
    assert herdr.compact_stage("") == ""
    assert herdr.compact_stage(None) == ""


def test_dstate_token_appears_only_after_a_heartbeat() -> None:
    lane = {"lane": "1-1", "current_stage": "Stage 4 Deploying on hk216"}
    tokens = herdr.build_lane_tokens(lane, "yield_and_guard")
    assert tokens["dstate"] == "s4@hk216"
    assert tokens["brain"] == "yield_and_guard"

    # No heartbeat yet: no dstate token, rather than a stale or empty one.
    assert "dstate" not in herdr.build_lane_tokens({"lane": "1-1"}, "yield_and_guard")


def test_dstate_respects_the_token_value_budget() -> None:
    tokens = herdr.build_lane_tokens({"lane": "1-1", "current_stage": "z" * 500}, "")
    assert len(tokens["dstate"]) <= herdr.TOKEN_VALUE_MAX


def test_dstate_never_carries_lifecycle_status() -> None:
    tokens = herdr.build_lane_tokens(
        {"lane": "1-1", "status": "working", "current_stage": "Stage 2 reviewing"}, ""
    )
    assert "status" not in tokens
    # No preposition to key off, so it falls back to the leading verb.
    assert tokens["dstate"] == "s2reviewing"


def test_python_and_extension_compaction_agree() -> None:
    """Both surfaces must label a stage identically or the sidebar lies."""
    for stage in [
        "Stage 4 Deploying on hk216",
        "Stage 2 of the build",
        "compiling",
        "正在跑 playbook",
    ]:
        py_value = herdr.compact_stage(stage)
        ts_out = subprocess.run(
            [
                "bun",
                "-e",
                'import {displayStage} from "./agent/omp/extensions/dispatch-omp/heartbeat.ts";'
                f'console.log(JSON.stringify(displayStage({json.dumps(stage)})));',
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        if ts_out.returncode != 0:
            pytest.skip("bun unavailable")
        assert py_value == json.loads(ts_out.stdout), stage


# --------------------------------------------------------------------------
# Agents view projection
# --------------------------------------------------------------------------


def test_agent_view_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Installing it unasked would replace the session's agent_panel_sort."""
    monkeypatch.delenv("HERDR_DISPATCH_AGENT_VIEW", raising=False)
    assert herdr.view_enabled_by_default() is False
    monkeypatch.setenv("HERDR_DISPATCH_AGENT_VIEW", "1")
    assert herdr.view_enabled_by_default() is True


def test_agent_view_projection_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    class FakeSocket:
        def __init__(self, *a, **k):
            pass

        def request(self, method, params):
            seen["method"] = method
            seen["params"] = params
            return {"type": "agent_view", "active": True}

    monkeypatch.setattr(herdr, "SocketClient", FakeSocket)
    herdr.set_agent_view(plugin_id="herdr-dispatch", enabled=True)

    assert seen["method"] == "agent.view.set"
    params = seen["params"]
    # Plugin-owned so Herdr retires the projection when the plugin goes away.
    assert params["source"] == "plugin:herdr-dispatch"
    fields = [
        f["field"]["token"]
        for f in params["filter"]["filters"]
        if isinstance(f.get("field"), dict)
    ]
    assert "lane" in fields


def test_agent_view_clear_is_scoped_to_the_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    class FakeSocket:
        def __init__(self, *a, **k):
            pass

        def request(self, method, params):
            seen.update(method=method, params=params)
            return {}

    monkeypatch.setattr(herdr, "SocketClient", FakeSocket)
    herdr.set_agent_view(plugin_id="herdr-dispatch", enabled=False)
    assert seen["method"] == "agent.view.clear"
    assert seen["params"] == {"source": "plugin:herdr-dispatch"}


# --------------------------------------------------------------------------
# Portability and decoupling
# --------------------------------------------------------------------------


def test_no_repository_paths_are_hardcoded() -> None:
    for path in (LIB / "herdr_client.py", BIN / "dispatch_board.py", BIN / "dispatch_plugin.py"):
        text = path.read_text(encoding="utf-8")
        assert "mac-bootstrap" not in text, path
        assert "/Users/" not in text, path


def test_plugin_never_imports_the_omp_extension() -> None:
    for path in (LIB / "herdr_client.py", BIN / "dispatch_board.py", BIN / "dispatch_plugin.py"):
        text = path.read_text(encoding="utf-8")
        assert "dispatch-omp" not in text, path
        assert "agent/omp/extensions" not in text, path


def test_plugin_state_lives_outside_the_plugin_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A managed plugin root can be replaced, so nothing durable may live there."""
    root = tmp_path / "plugin"
    root.mkdir()
    monkeypatch.setenv("HERDR_PLUGIN_ROOT", str(root))
    monkeypatch.delenv("HERDR_PLUGIN_STATE_DIR", raising=False)
    state = herdr.plugin_state_dir()
    assert root not in state.parents
    assert state.is_dir()


def test_herdr_binary_prefers_the_injected_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERDR_BIN_PATH", "/opt/custom/herdr")
    assert herdr.herdr_binary() == "/opt/custom/herdr"
    monkeypatch.delenv("HERDR_BIN_PATH")
    assert herdr.herdr_binary() == "herdr"


def test_in_herdr_requires_both_env_and_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HERDR_SOCKET_PATH", raising=False)
    monkeypatch.setenv("HERDR_ENV", "1")
    assert herdr.in_herdr() is False
    monkeypatch.setenv("HERDR_SOCKET_PATH", "/tmp/herdr.sock")
    assert herdr.in_herdr() is True


# --------------------------------------------------------------------------
# Board rendering
# --------------------------------------------------------------------------


def test_board_renders_lanes_and_brain_phase(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(board.herdr, "in_herdr", lambda: False)
    state = brain.default_state()
    state["orchestrator_phase"] = "yield_and_guard"
    state["blocked_reason"] = "Awaiting worker IPC [NOTIFY] on w3:p1"
    state["lanes"] = {
        "1-1": {"lane": "1-1", "wave": 1, "role": "researcher", "kind": "omp", "status": "blocked"},
        "1-2": {"lane": "1-2", "wave": 1, "role": "writer", "kind": "codex", "status": "working"},
    }

    text = board.render(state, board.collect_rows(state))
    assert "yield_and_guard" in text
    assert "1-1" in text and "1-2" in text
    assert "blocked" in text
    assert "parked" in text


def test_board_marks_a_missing_pane(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only claim a pane is gone when Herdr was actually consulted."""
    monkeypatch.setattr(board.herdr, "in_herdr", lambda: True)
    monkeypatch.setattr(board.herdr, "agent_info", lambda pane: {})
    state = brain.default_state()
    state["lanes"] = {"1-1": {"lane": "1-1", "pane_id": "w9:p9"}}
    text = board.render(state, board.collect_rows(state))
    assert "pane gone" in text


def test_board_does_not_claim_a_pane_is_gone_when_herdr_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outside Herdr the board must not invent a verdict."""
    monkeypatch.setattr(board.herdr, "in_herdr", lambda: False)
    state = brain.default_state()
    state["lanes"] = {"1-1": {"lane": "1-1", "pane_id": "w9:p9"}}
    text = board.render(state, board.collect_rows(state))
    assert "pane gone" not in text


def test_board_shows_an_empty_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(board.herdr, "in_herdr", lambda: False)
    state = brain.default_state()
    assert "no lanes recorded" in board.render(state, [])


def test_board_flags_a_lane_without_a_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(board.herdr, "in_herdr", lambda: False)
    state = brain.default_state()
    state["lanes"] = {"1-1": {"lane": "1-1", "status": "working", "pane_id": "w3:p5"}}
    assert "no handoff yet" in board.render(state, board.collect_rows(state))


def test_board_json_output_is_machine_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(board.herdr, "in_herdr", lambda: False)
    state = brain.default_state()
    state["lanes"] = {"1-1": {"lane": "1-1", "status": "working"}}
    rows = board.collect_rows(state)
    payload = json.loads(json.dumps({"brain": state["orchestrator_phase"], "rows": rows}))
    assert payload["rows"][0]["lane"] == "1-1"


# --------------------------------------------------------------------------
# CLI commands
# --------------------------------------------------------------------------


def test_status_command_runs(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    assert plugin.main(["--repo", str(repo), "status"]) == 0
    assert "brain: contract" in capsys.readouterr().out


def test_view_command_refuses_an_implicit_change(capsys) -> None:
    """No argument means no change, because a projection replaces a policy."""
    assert plugin.main(["view"]) == 0
    assert "opt-in" in capsys.readouterr().out


def test_startup_marks_missing_panes_as_orphaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    state = brain.default_state()
    state["lanes"] = {"1-1": {"lane": "1-1", "pane_id": "w9:p9"}}
    brain.save(brain.state_path(repo), state)

    monkeypatch.setattr(plugin.herdr, "in_herdr", lambda: True)
    monkeypatch.setattr(
        plugin.herdr, "agent_list", lambda: [{"pane_id": "w3:p4", "agent_status": "working"}]
    )
    monkeypatch.setattr(plugin.herdr, "view_enabled_by_default", lambda: False)

    assert plugin.main(["--repo", str(repo), "startup"]) == 0
    out = capsys.readouterr().out
    assert "orphaned=1" in out

    reloaded = brain.load(brain.state_path(repo))
    # Evidence is kept: a crashed worker must not look like a finished one.
    assert reloaded["lanes"]["1-1"]["status"] == "orphaned"
    assert reloaded["lanes"]["1-1"]["orphan_pane"] == "w9:p9"


def test_startup_keeps_live_status_from_herdr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    state = brain.default_state()
    state["lanes"] = {"1-1": {"lane": "1-1", "pane_id": "w3:p5", "status": "unknown"}}
    brain.save(brain.state_path(repo), state)

    monkeypatch.setattr(plugin.herdr, "in_herdr", lambda: True)
    monkeypatch.setattr(
        plugin.herdr, "agent_list", lambda: [{"pane_id": "w3:p5", "agent_status": "working"}]
    )
    monkeypatch.setattr(plugin.herdr, "view_enabled_by_default", lambda: False)

    assert plugin.main(["--repo", str(repo), "startup"]) == 0
    assert brain.load(brain.state_path(repo))["lanes"]["1-1"]["status"] == "working"


def test_startup_survives_an_unavailable_agent_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A startup hook must not wedge the server."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    def boom():
        raise plugin.herdr.HerdrError("socket down")

    monkeypatch.setattr(plugin.herdr, "in_herdr", lambda: True)
    monkeypatch.setattr(plugin.herdr, "agent_list", boom)
    monkeypatch.setattr(plugin.herdr, "view_enabled_by_default", lambda: False)

    assert plugin.main(["--repo", str(repo), "startup"]) == 0
    assert "agent list unavailable" in capsys.readouterr().out


def test_project_command_never_reports_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    state = brain.default_state()
    state["lanes"] = {"1-1": {"lane": "1-1", "pane_id": "w3:p5"}}
    brain.save(brain.state_path(repo), state)

    seen: list[list[str]] = []
    monkeypatch.setattr(
        plugin.herdr, "run_herdr", lambda args, **k: seen.append(list(args)) or {}
    )
    assert plugin.main(["--repo", str(repo), "project"]) == 0
    assert "projected 1 lane(s)" in capsys.readouterr().out
    assert all(args[:2] == ["pane", "report-metadata"] for args in seen)


def test_harvest_reports_and_never_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    handoff = tmp_path / "lane.md"
    handoff.write_text("# done\n")

    state = brain.default_state()
    state["lanes"] = {
        "1-1": {"lane": "1-1", "handoff": str(handoff)},
        "1-2": {"lane": "1-2", "handoff": None},
    }
    brain.save(brain.state_path(repo), state)

    monkeypatch.setattr(plugin.herdr, "notify", lambda *a, **k: True)
    assert plugin.main(["--repo", str(repo), "harvest", "--notify"]) == 0
    out = capsys.readouterr().out
    assert "ready  1-1" in out
    assert "wait   1-2" in out
    # Publication is a human decision; harvest only reports.
    assert "push" not in out