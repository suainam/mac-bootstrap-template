"""Tests for Gate D: Zero-Token Semantic Watchdog (Issue #134).

Verifies semantic watchdog classification of child lane activity:
- Legitimate long-running work (compilation, test suite, package install)
  -> EXTEND_LEASE (10 min extension, 0 false alarms to human)
- Stalled / deadlocked activity (interactive prompt hang, deadlock)
  -> NUDGE or ABORT
- Tail 15-line buffer truncation and ANSI stripping
- Zero new external dependencies (pure Python stdlib urllib + typesafe Jev contract)
- Graceful offline fallback when Jev / TYPESAFE_API_KEY is unavailable
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB = REPO_ROOT / "multiplexer" / "herdr-dispatch" / "lib"
BIN = REPO_ROOT / "multiplexer" / "herdr-dispatch" / "bin"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


watchdog = _load("watchdog_judge", LIB / "watchdog_judge.py")
brain = _load("dispatch_orchestrator_state", LIB / "orchestrator_state.py")
plugin = _load("dispatch_plugin", BIN / "dispatch_plugin.py")


# --------------------------------------------------------------------------
# Buffer Truncation & ANSI Stripping
# --------------------------------------------------------------------------


def test_extract_tail_buffer_short() -> None:
    lines = ["line 1", "line 2", "line 3"]
    text = "\n".join(lines)
    result = watchdog.extract_tail_buffer(text, max_lines=15)
    assert result == "\n".join(lines)


def test_extract_tail_buffer_caps_at_15_lines() -> None:
    many_lines = [f"output line {i}" for i in range(50)]
    text = "\n".join(many_lines)
    result = watchdog.extract_tail_buffer(text, max_lines=15)
    extracted = result.splitlines()
    assert len(extracted) == 15
    assert extracted == many_lines[-15:]


def test_extract_tail_buffer_strips_ansi() -> None:
    colored_text = "\x1b[32mPASSED\x1b[0m test_example.py::test_case\n\x1b[1;34mCompiling\x1b[0m core v0.1.0"
    result = watchdog.extract_tail_buffer(colored_text, max_lines=15)
    assert "\x1b[" not in result
    assert "PASSED test_example.py::test_case" in result
    assert "Compiling core v0.1.0" in result


def test_extract_tail_buffer_empty() -> None:
    assert watchdog.extract_tail_buffer("", max_lines=15) == ""
    assert watchdog.extract_tail_buffer("   \n\n  \n", max_lines=15) == ""


def test_sanitize_online_buffer_redacts_prefixed_secret_assignments_and_tokens() -> None:
    synthetic_openai = "sk-" + "proj-abcdefghijk"
    synthetic_aws_secret = "super-" + "secret-value"
    synthetic_aws_id = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
    synthetic_gitlab = "glpat-" + "abcdefghijklmnop"
    raw = "\n".join(
        [
            f"OPENAI_API_KEY={synthetic_openai}",
            f"AWS_SECRET_ACCESS_KEY={synthetic_aws_secret}",
            f"AWS_ACCESS_KEY_ID={synthetic_aws_id}",
            f"GITLAB_TOKEN={synthetic_gitlab}",
            f'"AWS_SECRET_ACCESS_KEY": "{synthetic_aws_secret}"',
            f'"OPENAI_API_KEY": "{synthetic_openai}"',
            "safe=status-ok",
        ]
    )
    redacted = watchdog.sanitize_online_buffer(raw)
    assert synthetic_openai not in redacted
    assert synthetic_aws_secret not in redacted
    assert synthetic_aws_id not in redacted
    assert synthetic_gitlab not in redacted
    assert "OPENAI_API_KEY=[REDACTED]" in redacted
    assert "AWS_SECRET_ACCESS_KEY=[REDACTED]" in redacted
    assert "AWS_ACCESS_KEY_ID=[REDACTED]" in redacted
    assert "GITLAB_TOKEN=[REDACTED]" in redacted
    assert "safe=status-ok" in redacted


# --------------------------------------------------------------------------
# Semantic Watchdog Judgment with TypeSafe Jev System One
# --------------------------------------------------------------------------


def test_jev_judgment_legitimate_compilation() -> None:
    """Cargo build / compilation output with P(legitimate) > 0.70 -> EXTEND_LEASE."""
    cargo_buffer = """
    Compiling proc-macro2 v1.0.79
    Compiling unicode-ident v1.0.12
    Compiling quote v1.0.35
    Compiling syn v2.0.58
    Compiling serde_derive v1.0.197
    Compiling serde v1.0.197
    Building [=======================> ] 84/96: my-crate(bin)
    """

    mock_jev_response = {
        "model": "jev-latest",
        "answers": {
            "is_legitimate_long_running": {"type": "noul", "noul": 0.88},
            "is_stalled_or_deadlocked": {"type": "noul", "noul": 0.05},
        },
        "usage": {"input_tokens": 150, "output_tokens": 12},
    }

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_jev_response).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        judgment = watchdog.evaluate_watchdog_state(
            buffer_tail=cargo_buffer,
            process_name="cargo",
            key="placeholder-key",
            online=True,
        )

        assert judgment.verdict == watchdog.WatchdogVerdict.EXTEND_LEASE
        assert judgment.p_legitimate == 0.88
        assert judgment.p_stalled == 0.05
        # 1st step: 180s ± 15s jitter (3 minutes)
        assert 165 <= judgment.lease_extension_seconds <= 195


def test_jev_judgment_legitimate_pytest() -> None:
    """Pytest / test suite run with P(legitimate) > 0.70 -> EXTEND_LEASE."""
    pytest_buffer = """
    tests/test_large_suite.py::test_step_1 PASSED [ 20%]
    tests/test_large_suite.py::test_step_2 PASSED [ 40%]
    tests/test_large_suite.py::test_step_3 PASSED [ 60%]
    tests/test_large_suite.py::test_step_4 ...
    """

    mock_jev_response = {
        "model": "jev-latest",
        "answers": {
            "is_legitimate_long_running": {"type": "noul", "noul": 0.92},
            "is_stalled_or_deadlocked": {"type": "noul", "noul": 0.03},
        },
        "usage": {"input_tokens": 120, "output_tokens": 12},
    }

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_jev_response).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        judgment = watchdog.evaluate_watchdog_state(
            buffer_tail=pytest_buffer,
            process_name="pytest",
            key="placeholder-key",
            online=True,
        )

        assert judgment.verdict == watchdog.WatchdogVerdict.EXTEND_LEASE
        assert judgment.p_legitimate == 0.92
        assert 165 <= judgment.lease_extension_seconds <= 195


def test_jev_judgment_interactive_prompt_hang() -> None:
    """Interactive prompt hang with P(stalled) > 0.65 -> NUDGE."""
    prompt_buffer = """
    Would you like to install recommended dependencies?
    [y/N] 
    ❯ 
    """

    mock_jev_response = {
        "model": "jev-latest",
        "answers": {
            "is_legitimate_long_running": {"type": "noul", "noul": 0.08},
            "is_stalled_or_deadlocked": {"type": "noul", "noul": 0.85},
        },
        "usage": {"input_tokens": 90, "output_tokens": 12},
    }

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_jev_response).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        judgment = watchdog.evaluate_watchdog_state(
            buffer_tail=prompt_buffer,
            process_name="zsh",
            key="placeholder-key",
            online=True,
        )

        assert judgment.verdict == watchdog.WatchdogVerdict.NUDGE
        assert judgment.p_stalled == 0.85
        assert judgment.p_legitimate == 0.08


def test_jev_judgment_fatal_deadlock() -> None:
    """Deadlock / fatal freeze with P(stalled) > 0.65 -> ABORT."""
    deadlock_buffer = """
    [FATAL] Thread deadlock detected on Mutex<WorkerPool>
    Thread 0x1a stuck waiting on 0x1b
    Process completely frozen
    """

    mock_jev_response = {
        "model": "jev-latest",
        "answers": {
            "is_legitimate_long_running": {"type": "noul", "noul": 0.01},
            "is_stalled_or_deadlocked": {"type": "noul", "noul": 0.95},
        },
        "usage": {"input_tokens": 110, "output_tokens": 12},
    }

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_jev_response).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        judgment = watchdog.evaluate_watchdog_state(
            buffer_tail=deadlock_buffer,
            process_name="app",
            key="placeholder-key",
            online=True,
        )

        assert judgment.verdict == watchdog.WatchdogVerdict.ABORT
        assert judgment.p_stalled == 0.95


# --------------------------------------------------------------------------
# Offline / Fallback Heuristics
# --------------------------------------------------------------------------


def test_offline_heuristic_compilation_and_test() -> None:
    """Without API key, offline heuristic detects compilation and tests."""
    buffer = "Compiling crate v1.0\nRunning tests/unit_test.rs"
    judgment = watchdog.evaluate_watchdog_state(
        buffer_tail=buffer,
        process_name="cargo",
        key="",  # No key
    )
    assert judgment.verdict == watchdog.WatchdogVerdict.EXTEND_LEASE
    assert judgment.p_legitimate >= 0.70
    assert 165 <= judgment.lease_extension_seconds <= 195


def test_offline_heuristic_prompt_hang() -> None:
    """Without API key, offline heuristic detects interactive prompt."""
    buffer = "Waiting for input...\n❯ "
    judgment = watchdog.evaluate_watchdog_state(
        buffer_tail=buffer,
        process_name="shell",
        key="",
    )
    assert judgment.verdict == watchdog.WatchdogVerdict.NUDGE
    assert judgment.p_stalled >= 0.65


def test_offline_heuristic_deadlock() -> None:
    """Without API key, offline heuristic detects deadlock."""
    buffer = "deadlock detected in worker thread"
    judgment = watchdog.evaluate_watchdog_state(
        buffer_tail=buffer,
        process_name="binary",
        key="",
    )
    assert judgment.verdict == watchdog.WatchdogVerdict.ABORT
    assert judgment.p_stalled >= 0.65


def test_online_classification_is_opt_in_even_when_key_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "synthetic-key")
    with patch("urllib.request.urlopen") as mock_urlopen:
        judgment = watchdog.evaluate_watchdog_state(
            buffer_tail="cargo build still running",
            process_name="cargo",
        )
    assert judgment.model == "heuristic-fallback"
    mock_urlopen.assert_not_called()


def test_online_payload_redacts_secrets_and_caps_buffer_bytes() -> None:
    fixture_marker = "SYNTHETIC_SUPER_SECRET_VALUE"
    huge = f"{'API' + '_KEY'}={fixture_marker} " + ("x" * 100_000)
    mock_jev_response = {
        "model": "jev-latest",
        "answers": {
            "is_legitimate_long_running": {"type": "noul", "noul": 0.4},
            "is_stalled_or_deadlocked": {"type": "noul", "noul": 0.4},
        },
    }
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_jev_response).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response
        watchdog.evaluate_watchdog_state(
            buffer_tail=huge,
            process_name="worker --token=" + "ghp" + "_SYNTHETIC_PROCESS_SECRET",
            key="synthetic-key",
            online=True,
            facts={
                "lane": "1-4",
                "status": "working",
                "phase": "yield_and_guard",
                "state_change_seq": 10,
                "last_heartbeat_age_ms": 600_000,
                "private_path": "/" + "Users/example/private",
            },
        )
        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
    sent = payload["state"]["tail_buffer"]
    assert fixture_marker not in sent
    assert len(sent.encode("utf-8")) <= watchdog.MAX_ONLINE_BUFFER_BYTES
    assert payload["state"]["process_name"] == "worker"
    assert payload["state"]["facts"] == {
        "lane": "1-4",
        "status": "working",
        "phase": "yield_and_guard",
        "state_change_seq": 10,
        "last_heartbeat_age_ms": 600_000,
    }


def test_offline_deadlock_fact_beats_compiler_word() -> None:
    judgment = watchdog.evaluate_watchdog_state(
        buffer_tail="cargo build blocked: mutex deadlock detected",
        process_name="cargo",
        key="",
    )
    assert judgment.verdict == watchdog.WatchdogVerdict.ABORT


def test_network_failure_falls_back_gracefully() -> None:
    """Network exception during Jev call falls back safely rather than crashing."""
    buffer = "Compiling module..."
    with patch("urllib.request.urlopen", side_effect=OSError("Network unreachable")):
        judgment = watchdog.evaluate_watchdog_state(
            buffer_tail=buffer,
            process_name="cargo",
            key="placeholder-key",
            online=True,
        )
        # Should gracefully fall back to heuristic evaluation
        assert judgment.verdict == watchdog.WatchdogVerdict.EXTEND_LEASE


# --------------------------------------------------------------------------
# State Persistence & Lease Extension
# --------------------------------------------------------------------------


def test_extend_lease_updates_state(tmp_path: Path) -> None:
    state_file = tmp_path / "ORCHESTRATOR_STATE.json"
    state = brain.default_state()
    state["lanes"] = {"1-4": {"lane": "1-4", "status": "working", "pane_id": "w3:p4"}}
    brain.save(state_file, state)

    now = int(time.time() * 1000)
    updated = watchdog.apply_lease_extension(
        state_path=state_file,
        lane_id="1-4",
        verdict=watchdog.WatchdogVerdict.EXTEND_LEASE,
        extension_seconds=600,
        now_ms=now,
    )

    lane = updated["lanes"]["1-4"]
    assert lane["watchdog_verdict"] == "EXTEND_LEASE"
    assert lane["watchdog_lease_until_unix_ms"] == now + 600_000
    assert lane["watchdog_evaluated_at_unix_ms"] == now


def test_is_lane_lease_active() -> None:
    now = int(time.time() * 1000)
    assert watchdog.is_lease_active({"watchdog_lease_until_unix_ms": now + 5000}, now_ms=now) is True
    assert watchdog.is_lease_active({"watchdog_lease_until_unix_ms": now - 1000}, now_ms=now) is False
    assert watchdog.is_lease_active({}, now_ms=now) is False


# --------------------------------------------------------------------------
# CLI Plugin Integration
# --------------------------------------------------------------------------


def test_plugin_watchdog_command_evaluation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    state_file = tmp_path / "ORCHESTRATOR_STATE.json"
    state = brain.default_state()
    state["lanes"] = {
        "1-4": {
            "lane": "1-4",
            "status": "working",
            "pane_id": "w3:p4",
            "last_heartbeat": int(time.time() * 1000) - 600_000,
        }
    }
    brain.save(state_file, state)

    monkeypatch.setattr(plugin, "state_path", lambda args: state_file)
    monkeypatch.setattr(plugin.herdr, "in_herdr", lambda: True)
    monkeypatch.setattr(
        plugin.herdr,
        "run_herdr",
        lambda args: {"text": "Compiling crate v1\nBuilding [====> ] 50/100"},
    )
    monkeypatch.setattr(
        plugin.herdr,
        "agent_info",
        lambda pane: {"process_name": "cargo", "agent_status": "working", "state_change_seq": 10},
    )

    exit_code = plugin.main(["watchdog", "--lane", "1-4", "--repo", str(tmp_path), "--json"])
    assert exit_code == 0

    reloaded = brain.load(state_file)
    assert reloaded["lanes"]["1-4"]["watchdog_verdict"] == "EXTEND_LEASE"
    assert reloaded["lanes"]["1-4"]["watchdog_lease_until_unix_ms"] > int(time.time() * 1000)
    assert reloaded["lanes"]["1-4"]["consecutive_extensions"] == 1
    assert reloaded["lanes"]["1-4"]["last_seen_seq"] == 10


def test_plugin_watchdog_command_stepped_and_reset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI plugin tracks consecutive extensions on same seq, and resets counter on newer seq."""
    state_file = tmp_path / "ORCHESTRATOR_STATE.json"
    state = brain.default_state()
    state["lanes"] = {
        "1-4": {
            "lane": "1-4",
            "status": "working",
            "pane_id": "w3:p4",
            "last_heartbeat": int(time.time() * 1000) - 600_000,
        }
    }
    brain.save(state_file, state)

    seq_holder = {"seq": 10}

    monkeypatch.setattr(plugin, "state_path", lambda args: state_file)
    monkeypatch.setattr(plugin.herdr, "in_herdr", lambda: True)
    monkeypatch.setattr(
        plugin.herdr,
        "run_herdr",
        lambda args: {"text": "Compiling crate v1\nBuilding [====> ] 50/100"},
    )
    monkeypatch.setattr(
        plugin.herdr,
        "agent_info",
        lambda pane: {"process_name": "cargo", "agent_status": "working", "state_change_seq": seq_holder["seq"]},
    )

    # 1st run: seq 10 -> consecutive becomes 1
    assert plugin.main(["watchdog", "--lane", "1-4", "--repo", str(tmp_path), "--json"]) == 0
    out1 = json.loads(capsys.readouterr().out)
    assert out1["results"][0]["consecutive_extensions"] == 1
    lane1 = brain.load(state_file)["lanes"]["1-4"]
    assert lane1["consecutive_extensions"] == 1
    assert lane1["last_seen_seq"] == 10
    expired = brain.load(state_file)
    expired["lanes"]["1-4"]["watchdog_lease_until_unix_ms"] = int(time.time() * 1000) - 1
    brain.save(state_file, expired)

    # 2nd eligible run: still seq 10 -> consecutive becomes 2
    assert plugin.main(["watchdog", "--lane", "1-4", "--repo", str(tmp_path), "--json"]) == 0
    out2 = json.loads(capsys.readouterr().out)
    assert out2["results"][0]["consecutive_extensions"] == 2
    lane2 = brain.load(state_file)["lanes"]["1-4"]
    assert lane2["consecutive_extensions"] == 2
    expired = brain.load(state_file)
    expired["lanes"]["1-4"]["watchdog_lease_until_unix_ms"] = int(time.time() * 1000) - 1
    brain.save(state_file, expired)

    # 3rd eligible run: seq advances to 11 -> counter resets to 0 before award, then becomes 1
    seq_holder["seq"] = 11
    assert plugin.main(["watchdog", "--lane", "1-4", "--repo", str(tmp_path), "--json"]) == 0
    out3 = json.loads(capsys.readouterr().out)
    assert out3["results"][0]["consecutive_extensions"] == 1
    lane3 = brain.load(state_file)["lanes"]["1-4"]
    assert lane3["consecutive_extensions"] == 1
    assert lane3["last_seen_seq"] == 11


def test_plugin_watchdog_refuses_lane_from_another_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_file = tmp_path / "ORCHESTRATOR_STATE.json"
    state = brain.default_state()
    state["run_id"] = "run-current"
    state["lanes"] = {
        "1-4": {
            "lane": "1-4",
            "run_id": "run-stale",
            "status": "working",
            "pane_id": "w3:p4",
            "last_heartbeat": int(time.time() * 1000) - 600_000,
        }
    }
    brain.save(state_file, state)
    monkeypatch.setattr(plugin, "state_path", lambda args: state_file)
    evaluate = MagicMock(side_effect=AssertionError("stale run lane must not be classified"))
    monkeypatch.setattr(plugin.watchdog, "evaluate_watchdog_state", evaluate)

    assert plugin.main(["watchdog", "--lane", "1-4", "--repo", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert evaluate.call_count == 0
    assert "current run" in payload["results"][0]["reason"]


def test_plugin_watchdog_skips_terminal_recent_and_leased_lanes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    now = int(time.time() * 1000)
    state_file = tmp_path / "ORCHESTRATOR_STATE.json"
    state = brain.default_state()
    state["brain"]["awaiting_lanes"] = ["1-1", "1-2", "1-3", "1-4"]
    state["lanes"] = {
        "1-1": {"lane": "1-1", "status": "released", "phase": "closed", "last_heartbeat": now - 600_000},
        "1-2": {"lane": "1-2", "status": "working", "last_heartbeat": now - 1_000},
        "1-3": {
            "lane": "1-3",
            "status": "working",
            "last_heartbeat": now - 600_000,
            "watchdog_lease_until_unix_ms": now + 600_000,
        },
        "1-4": {"lane": "1-4", "status": "done", "phase": "done", "last_heartbeat": now - 600_000},
    }
    brain.save(state_file, state)
    monkeypatch.setattr(plugin, "state_path", lambda args: state_file)
    evaluate = MagicMock(side_effect=AssertionError("filtered lane must not be classified"))
    monkeypatch.setattr(plugin.watchdog, "evaluate_watchdog_state", evaluate)

    assert plugin.main(["watchdog", "--sweep", "--repo", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert evaluate.call_count == 0
    reasons = {row["lane"]: row["reason"] for row in payload["results"]}
    assert "terminal" in reasons["1-1"]
    assert "not silent" in reasons["1-2"]
    assert "lease" in reasons["1-3"]
    assert "terminal" in reasons["1-4"]


def test_plugin_watchdog_skips_when_herdr_agent_is_not_active(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_file = tmp_path / "ORCHESTRATOR_STATE.json"
    state = brain.default_state()
    state["lanes"] = {
        "1-4": {
            "lane": "1-4",
            "status": "working",
            "pane_id": "w3:p4",
            "last_heartbeat": int(time.time() * 1000) - 600_000,
        }
    }
    brain.save(state_file, state)
    monkeypatch.setattr(plugin, "state_path", lambda args: state_file)
    monkeypatch.setattr(plugin.herdr, "in_herdr", lambda: True)
    monkeypatch.setattr(plugin.herdr, "run_herdr", lambda args: {"text": "quiet"})
    monkeypatch.setattr(
        plugin.herdr,
        "agent_info",
        lambda pane: {"process_name": "worker", "agent_status": "exited", "state_change_seq": 10},
    )
    evaluate = MagicMock(side_effect=AssertionError("inactive agent must not be classified"))
    monkeypatch.setattr(plugin.watchdog, "evaluate_watchdog_state", evaluate)

    assert plugin.main(["watchdog", "--lane", "1-4", "--repo", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert evaluate.call_count == 0
    assert "not active" in payload["results"][0]["reason"]


def test_plugin_watchdog_never_blindly_sends_enter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_file = tmp_path / "ORCHESTRATOR_STATE.json"
    state = brain.default_state()
    state["lanes"] = {
        "1-4": {
            "lane": "1-4",
            "status": "working",
            "pane_id": "w3:p4",
            "last_heartbeat": int(time.time() * 1000) - 600_000,
        }
    }
    brain.save(state_file, state)
    calls = []
    monkeypatch.setattr(plugin, "state_path", lambda args: state_file)
    monkeypatch.setattr(plugin.herdr, "in_herdr", lambda: True)

    def run_herdr(argv):
        calls.append(argv)
        if argv[:2] == ["pane", "read"]:
            return {"text": "Waiting for input...\n❯ "}
        raise AssertionError(f"unexpected mutating Herdr call: {argv}")

    monkeypatch.setattr(plugin.herdr, "run_herdr", run_herdr)
    monkeypatch.setattr(
        plugin.herdr,
        "agent_info",
        lambda pane: {"process_name": "shell", "agent_status": "working", "state_change_seq": 10},
    )

    assert plugin.main(["watchdog", "--lane", "1-4", "--repo", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["verdict"] == "NUDGE"
    assert payload["results"][0]["operator_action"] == "review_and_nudge"
    assert all(argv[:2] != ["pane", "send-keys"] for argv in calls)


# --------------------------------------------------------------------------
# Stepped Exponential Backoff with Jitter & Self-Healing Resets
# --------------------------------------------------------------------------


def test_compute_stepped_lease_seconds_progression() -> None:
    """1st extension 3m (180s) -> 2nd 5m (300s) -> 3rd+ 10m (600s ceiling)."""
    assert watchdog.compute_stepped_lease_seconds(0, jitter_range=0) == 180
    assert watchdog.compute_stepped_lease_seconds(1, jitter_range=0) == 300
    assert watchdog.compute_stepped_lease_seconds(2, jitter_range=0) == 600
    assert watchdog.compute_stepped_lease_seconds(3, jitter_range=0) == 600
    assert watchdog.compute_stepped_lease_seconds(10, jitter_range=0) == 600


def test_compute_stepped_lease_seconds_jitter() -> None:
    """Jitter is strictly bounded within [-15s, +15s] and adds variance."""
    import random

    # Deterministic test with fixed seed
    rng = random.Random(42)
    val = watchdog.compute_stepped_lease_seconds(0, jitter_range=15, rng=rng)
    assert 165 <= val <= 195

    # Statistical distribution test across multiple calls
    results = [watchdog.compute_stepped_lease_seconds(0, jitter_range=15) for _ in range(50)]
    assert all(165 <= r <= 195 for r in results)
    assert len(set(results)) > 1, "Jitter should introduce variance across calls"

    results_step2 = [watchdog.compute_stepped_lease_seconds(1, jitter_range=15) for _ in range(50)]
    assert all(285 <= r <= 315 for r in results_step2)

    results_step3 = [watchdog.compute_stepped_lease_seconds(2, jitter_range=15) for _ in range(50)]
    assert all(585 <= r <= 615 for r in results_step3)


def test_apply_lease_extension_stepped_sequence(tmp_path: Path) -> None:
    """Consecutive extensions without state movement advance 180s -> 300s -> 600s."""
    state_file = tmp_path / "ORCHESTRATOR_STATE.json"
    state = brain.default_state()
    state["lanes"] = {"1-4": {"lane": "1-4", "status": "working", "pane_id": "w3:p4"}}
    brain.save(state_file, state)

    now = 1_000_000_000

    # 1st extension: consecutive becomes 1, lease +180s
    res1 = watchdog.apply_lease_extension(
        state_path=state_file,
        lane_id="1-4",
        verdict=watchdog.WatchdogVerdict.EXTEND_LEASE,
        current_seq=10,
        now_ms=now,
        jitter_range=0,
    )
    lane1 = res1["lanes"]["1-4"]
    assert lane1["consecutive_extensions"] == 1
    assert lane1["last_seen_seq"] == 10
    assert lane1["watchdog_lease_until_unix_ms"] == now + 180_000

    # 2nd consecutive extension with same seq (10): consecutive becomes 2, lease +300s
    res2 = watchdog.apply_lease_extension(
        state_path=state_file,
        lane_id="1-4",
        verdict=watchdog.WatchdogVerdict.EXTEND_LEASE,
        current_seq=10,
        now_ms=now,
        jitter_range=0,
    )
    lane2 = res2["lanes"]["1-4"]
    assert lane2["consecutive_extensions"] == 2
    assert lane2["last_seen_seq"] == 10
    assert lane2["watchdog_lease_until_unix_ms"] == now + 300_000

    # 3rd consecutive extension with same seq (10): consecutive becomes 3, lease +600s
    res3 = watchdog.apply_lease_extension(
        state_path=state_file,
        lane_id="1-4",
        verdict=watchdog.WatchdogVerdict.EXTEND_LEASE,
        current_seq=10,
        now_ms=now,
        jitter_range=0,
    )
    lane3 = res3["lanes"]["1-4"]
    assert lane3["consecutive_extensions"] == 3
    assert lane3["last_seen_seq"] == 10
    assert lane3["watchdog_lease_until_unix_ms"] == now + 600_000


def test_apply_lease_extension_forward_progress_resets_counter(tmp_path: Path) -> None:
    """When state_change_seq advances, consecutive counter resets to 0 and lease returns to 3m."""
    state_file = tmp_path / "ORCHESTRATOR_STATE.json"
    state = brain.default_state()
    state["lanes"] = {
        "1-4": {
            "lane": "1-4",
            "status": "working",
            "pane_id": "w3:p4",
            "consecutive_extensions": 3,
            "last_seen_seq": 10,
        }
    }
    brain.save(state_file, state)

    now = 1_000_000_000

    # Agent made progress: seq moved from 10 to 11
    res = watchdog.apply_lease_extension(
        state_path=state_file,
        lane_id="1-4",
        verdict=watchdog.WatchdogVerdict.EXTEND_LEASE,
        current_seq=11,
        now_ms=now,
        jitter_range=0,
    )
    lane = res["lanes"]["1-4"]
    # Counter was reset to 0 then incremented to 1 for this 1st extension
    assert lane["consecutive_extensions"] == 1
    assert lane["last_seen_seq"] == 11
    # Lease is back to 180s (3 minutes)
    assert lane["watchdog_lease_until_unix_ms"] == now + 180_000


def test_apply_lease_extension_non_extend_verdict_resets_on_progress(tmp_path: Path) -> None:
    """Non-extend verdict (e.g. NUDGE) also resets counter on forward progress."""
    state_file = tmp_path / "ORCHESTRATOR_STATE.json"
    state = brain.default_state()
    state["lanes"] = {
        "1-4": {
            "lane": "1-4",
            "status": "working",
            "pane_id": "w3:p4",
            "consecutive_extensions": 2,
            "last_seen_seq": 10,
        }
    }
    brain.save(state_file, state)

    now = 1_000_000_000
    res = watchdog.apply_lease_extension(
        state_path=state_file,
        lane_id="1-4",
        verdict=watchdog.WatchdogVerdict.NUDGE,
        current_seq=15,
        now_ms=now,
    )
    lane = res["lanes"]["1-4"]
    assert lane["consecutive_extensions"] == 0
    assert lane["last_seen_seq"] == 15
    assert "watchdog_lease_until_unix_ms" not in lane


def test_single_writer_partition_allows_watchdog_stepped_fields(tmp_path: Path) -> None:
    """Plugin writer owns consecutive_extensions and last_seen_seq without violating single-writer."""
    state_file = tmp_path / "ORCHESTRATOR_STATE.json"
    state = brain.default_state()
    state["lanes"] = {"1-4": {"lane": "1-4"}}
    brain.save(state_file, state)

    updated = brain.update_lane(
        state_file,
        "1-4",
        {"consecutive_extensions": 2, "last_seen_seq": 42},
        writer="plugin",
    )
    lane = updated["lanes"]["1-4"]
    assert lane["consecutive_extensions"] == 2
    assert lane["last_seen_seq"] == 42

