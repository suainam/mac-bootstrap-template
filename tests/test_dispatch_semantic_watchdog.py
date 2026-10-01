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
        )

        assert judgment.verdict == watchdog.WatchdogVerdict.EXTEND_LEASE
        assert judgment.p_legitimate == 0.88
        assert judgment.p_stalled == 0.05
        assert judgment.lease_extension_seconds == 600  # 10 minutes


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
        )

        assert judgment.verdict == watchdog.WatchdogVerdict.EXTEND_LEASE
        assert judgment.p_legitimate == 0.92
        assert judgment.lease_extension_seconds == 600


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
    assert judgment.lease_extension_seconds == 600


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


def test_network_failure_falls_back_gracefully() -> None:
    """Network exception during Jev call falls back safely rather than crashing."""
    buffer = "Compiling module..."
    with patch("urllib.request.urlopen", side_effect=OSError("Network unreachable")):
        judgment = watchdog.evaluate_watchdog_state(
            buffer_tail=buffer,
            process_name="cargo",
            key="placeholder-key",
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
    state["lanes"] = {"1-4": {"lane": "1-4", "status": "working", "pane_id": "w3:p4"}}
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
