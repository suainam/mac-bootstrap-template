"""Tests for the prompt protocol gate — TB-08.

The incident this gate exists for: an orchestrator sent bare, unstructured
prose straight through `herdr agent prompt` and the plugin system waved it
through without the slightest awareness.

Two things are worth knowing about why the tests are shaped this way.

**The gate cannot intercept.** Herdr's plugin surface is a fixed enumeration of
state-change events; `herdr agent prompt` is a direct CLI/RPC call with no
pre-execution hook, no middleware and no veto. So this gate is not a transparent
filter the orchestrator cannot bypass — it is the sanctioned path plus a check
that sits in front of delivery. These tests therefore pin the *delivery*
property (`--send` refuses before it sends), which is the part that actually
holds.

**The gate must not rewrite its input.** Constraint: judge and block only.
Silently substituting a coordinate would fabricate something the caller never
verified, so `test_the_gate_never_repairs_a_prompt` pins that the text handed to
Herdr is byte-identical to what the caller wrote.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "multiplexer" / "herdr-dispatch"
LIB = PLUGIN_ROOT / "lib"
BIN = PLUGIN_ROOT / "bin"
PROBE = REPO_ROOT / "scripts" / "prompt-gate-probe.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(LIB))
herdr = _load("dispatch_herdr_client", LIB / "herdr_client.py")
proto = _load("dispatch_prompt_protocol", LIB / "prompt_protocol.py")
plugin = _load("dispatch_plugin", BIN / "dispatch_plugin.py")

COMPLIANT = (
    "Read .dispatch/TASK.md and implement the fix.\n"
    "When complete, write the handoff and run:\n"
    "herdr agent prompt w3:p1 "
    "'\\n[NOTIFY] [w5:p1_opencode_mac-bootstrap]\\n"
    "DONE: 1-Lane-1-Worktree isolation landed\\n"
    "Handoff: /tmp/handoff/x-20261001_000000.md'"
)

# The literal prompt the orchestrator actually sent, verbatim.
INCIDENT = "看一下这个仓库的情况，然后把问题修掉。"


# --------------------------------------------------------------------------
# The incident
# --------------------------------------------------------------------------


def test_the_incident_prompt_is_refused() -> None:
    """The red case from the incident, as a regression test."""
    report = proto.validate_prompt(INCIDENT)
    assert not report.ok
    assert any("no [NOTIFY]" in v for v in report.violations)
    assert any("no resolved pane coordinate" in v for v in report.violations)


def test_a_compliant_prompt_passes() -> None:
    report = proto.validate_prompt(COMPLIANT)
    assert report.ok, report.violations
    assert report.coordinate == "w3:p1"
    assert report.has_notify and report.has_done and report.has_handoff


def test_alphanumeric_pane_coordinate_is_resolved() -> None:
    """Herdr 0.9.3 emits opaque IDs such as w3:pB and wD:p1."""
    prompt = COMPLIANT.replace("w3:p1", "w3:pB")
    report = proto.validate_prompt(prompt)
    assert report.ok, report.violations
    assert report.coordinate == "w3:pB"


# --------------------------------------------------------------------------
# Placeholders — orchestrator lesson 3
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "placeholder",
    ["<orch-pane>", "${ORCH_PANE}", "$ORCH_PANE", "<pane_id>", "<name>", "<repo_slug>"],
)
def test_placeholder_leakage_is_refused(placeholder: str) -> None:
    """An unevaluated placeholder misroutes the callback to nowhere."""
    prompt = COMPLIANT.replace("w3:p1", placeholder)
    report = proto.validate_prompt(prompt)
    assert not report.ok
    assert any("unresolved placeholder" in v for v in report.violations)


def test_a_prompt_with_neither_coordinate_nor_notify_is_refused() -> None:
    prompt = (
        "Read .dispatch/TASK.md and report back.\n"
        "herdr agent prompt <orch-pane> '\\n[NOTIFY]\\nDONE: work'"
    )
    report = proto.validate_prompt(prompt)
    assert not report.ok
    assert len(report.violations) >= 2


def test_notify_without_a_resolved_coordinate_is_refused() -> None:
    prompt = (
        "Read .dispatch/TASK.md.\n"
        "herdr agent prompt ${ORCH_PANE} '\\n[NOTIFY]\\nDONE: fixed it'"
    )
    assert not proto.validate_prompt(prompt).ok


# --------------------------------------------------------------------------
# Structured callback shape
# --------------------------------------------------------------------------


def test_notify_without_a_done_line_is_refused() -> None:
    prompt = (
        "herdr agent prompt w3:p1 '\\n[NOTIFY] [w5:p1]\\n"
        "Handoff: ~/x.md'"
    )
    report = proto.validate_prompt(prompt)
    assert not report.ok
    assert any("DONE:" in v for v in report.violations)


def test_notify_without_a_handoff_line_is_refused() -> None:
    prompt = "herdr agent prompt w3:p1 '\\n[NOTIFY] [w5:p1]\\nDONE: landed'"
    report = proto.validate_prompt(prompt)
    assert not report.ok
    assert any("Handoff:" in v for v in report.violations)


def test_an_empty_done_value_is_not_a_done_line() -> None:
    """`DONE:` with nothing after it carries no conclusion."""
    prompt = "herdr agent prompt w3:p1 '\\n[NOTIFY]\\nDONE:\\nHandoff: ~/x.md'"
    assert not proto.validate_prompt(prompt).ok


def test_every_violation_is_reported_at_once() -> None:
    """One fix round should clear the dispatch, not three."""
    report = proto.validate_prompt("herdr agent prompt <orch-pane> '\\n[NOTIFY]'")
    assert len(report.violations) >= 2


# --------------------------------------------------------------------------
# Escape normalisation — the canonical template uses literal \n
# --------------------------------------------------------------------------


def test_literal_backslash_n_callback_is_accepted() -> None:
    """SKILL.md's own template emits literal backslash-n through bash quotes.

    Requiring real newlines would refuse every prompt written to our own spec.
    """
    assert "\\n" in COMPLIANT  # the fixture really does use escapes
    assert proto.validate_prompt(COMPLIANT).ok


def test_real_newlines_are_accepted_too() -> None:
    prompt = (
        "Read .dispatch/TASK.md.\n"
        "herdr agent prompt w3:p1 "
        "'\n[NOTIFY] [w5:p1]\nDONE: landed\nHandoff: ~/x.md'"
    )
    assert proto.validate_prompt(prompt).ok


def test_normalise_is_a_no_op_on_real_newlines() -> None:
    assert proto.normalise_escapes("a\nb") == "a\nb"


def test_normalise_expands_escapes() -> None:
    assert proto.normalise_escapes("a\\nb") == "a\nb"
    assert proto.normalise_escapes("a\\r\\nb") == "a\nb"


# --------------------------------------------------------------------------
# The gate judges, it does not repair
# --------------------------------------------------------------------------


def test_the_gate_never_repairs_a_prompt() -> None:
    """Constraint: no silent mutation or fabricated arguments.

    A gate that fills in `${ORCH_PANE}` itself would invent a coordinate nobody
    verified, so the text handed to Herdr must be byte-identical to the input.
    """
    sent: list[tuple[str, str]] = []
    broken = COMPLIANT.replace("w3:p1", "${ORCH_PANE}")

    with pytest.raises(proto.PromptProtocolError):
        proto.send_prompt("w3:p1", broken, notifier=lambda t, x: sent.append((t, x)))

    assert sent == [], "a refused prompt must never be delivered"


def test_send_forwards_the_original_bytes_unchanged() -> None:
    sent: list[tuple[str, str]] = []
    proto.send_prompt("w3:p1", COMPLIANT, notifier=lambda t, x: sent.append((t, x)))
    assert sent == [("w3:p1", COMPLIANT)]


def test_assert_raises_with_a_readable_report() -> None:
    with pytest.raises(proto.PromptProtocolError) as excinfo:
        proto.assert_prompt_compliant(INCIDENT)
    assert "REFUSED" in str(excinfo.value)


def test_assert_returns_the_report_when_compliant() -> None:
    assert proto.assert_prompt_compliant(COMPLIANT).ok


def test_callback_can_be_waived_for_a_one_way_question() -> None:
    """A pure question has no return leg; demanding one would be noise."""
    assert proto.validate_prompt("Which module owns the state file?", require_callback=False).ok


def test_placeholders_are_still_refused_when_the_callback_is_waived() -> None:
    """The escape hatch covers the callback only, never the coordinate rule."""
    report = proto.validate_prompt(
        "herdr agent prompt <orch-pane> do the thing", require_callback=False
    )
    assert not report.ok


def test_a_callback_present_always_earns_the_full_check() -> None:
    """Waiving the callback must not waive it when a callback is actually there."""
    report = proto.validate_prompt(
        "herdr agent prompt <orch-pane> '\\n[NOTIFY]'", require_callback=False
    )
    assert not report.ok


# --------------------------------------------------------------------------
# Report shape
# --------------------------------------------------------------------------


def test_report_serialises() -> None:
    payload = proto.validate_prompt(COMPLIANT).as_dict()
    assert payload["ok"] is True
    assert payload["coordinate"] == "w3:p1"
    assert payload["has_done"] is True


def test_report_render_shows_ok_and_refused() -> None:
    assert "OK" in proto.validate_prompt(COMPLIANT).render()
    assert "REFUSED" in proto.validate_prompt(INCIDENT).render()


def test_contract_summary_names_both_rules() -> None:
    assert len(proto.contract_summary()) == 2


# --------------------------------------------------------------------------
# CLI surface
# --------------------------------------------------------------------------


def _run(args: list[str], stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BIN / "dispatch_plugin.py"), *args],
        input=stdin,
        capture_output=True,
        text=True,
    )


@pytest.fixture(autouse=True)
def _no_live_herdr(monkeypatch: pytest.MonkeyPatch):
    """Fail loudly rather than send a test prompt to a real pane.

    `plugin.herdr` is a *different module object* from this file's `herdr`: each
    was loaded from the same source under its own name. Patching the wrong one
    leaves the real client live, which silently turned a unit test into a real
    `herdr agent prompt` against the live session. This makes that impossible.
    """
    def refuse(*args, **kwargs):
        raise AssertionError(
            "test attempted a live Herdr call; patch plugin.herdr.run_herdr"
        )

    monkeypatch.setattr(plugin.herdr, "run_herdr", refuse)
    return refuse


def test_cli_refuses_the_incident_prompt() -> None:
    proc = _run(["prompt", "--stdin"], INCIDENT)
    assert proc.returncode == 2
    assert "REFUSED" in proc.stderr


def test_cli_accepts_a_compliant_prompt() -> None:
    proc = _run(["prompt", "--stdin"], COMPLIANT)
    assert proc.returncode == 0
    assert "prompt OK" in proc.stdout


def test_cli_json_output_carries_the_verdict() -> None:
    proc = _run(["prompt", "--stdin", "--json"], COMPLIANT)
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["source"] == "<stdin>"


def test_cli_reads_a_file(tmp_path: Path) -> None:
    path = tmp_path / "task.md"
    path.write_text(COMPLIANT, encoding="utf-8")
    assert _run(["prompt", "--file", str(path)]).returncode == 0


def test_cli_reports_a_missing_file() -> None:
    proc = _run(["prompt", "--file", "/nonexistent/nope.md"])
    assert proc.returncode == 2
    assert "cannot read" in proc.stderr


def test_cli_requires_a_source() -> None:
    assert _run(["prompt"]).returncode == 2


def test_send_requires_a_target() -> None:
    proc = _run(["prompt", "--stdin", "--send"], COMPLIANT)
    assert proc.returncode == 2
    assert "requires --target" in proc.stderr


def test_send_does_not_deliver_a_refused_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The load-bearing property: refusal happens strictly before delivery."""
    calls: list[list[str]] = []
    monkeypatch.setattr(plugin.herdr, "run_herdr", lambda args, **kw: calls.append(list(args)) or {})

    code = plugin.main(["prompt", "--text", INCIDENT, "--send", "--target", "w3:p9"])
    assert code == 2
    assert calls == [], "a refused prompt must never reach the worker"


def test_send_delivers_a_compliant_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delivery expands standard escapes.

    This used to assert byte-identical delivery, which is precisely the
    behaviour that caused the one-line `[NOTIFY]` defect: bash single quotes
    deliver a literal backslash-n, and forwarding it verbatim meant the report
    rendered as a single long line. The contract changed deliberately.

    What still holds -- and is asserted below -- is that the gate never invents
    *semantic* content. It expands escapes and substitutes nothing.
    """
    calls: list[list[str]] = []
    monkeypatch.setattr(plugin.herdr, "run_herdr", lambda args, **kw: calls.append(list(args)) or {})

    assert plugin.main(
        ["prompt", "--text", COMPLIANT, "--send", "--target", "w3:p9"]
    ) == 0

    [argv] = calls
    assert argv[:3] == ["agent", "prompt", "w3:p9"]
    delivered = argv[3]
    # Escapes expanded into real control characters: every literal `\n` became a
    # real one, and the newlines that were already real are still there.
    assert "\\n" not in delivered
    assert delivered.count("\n") == COMPLIANT.count("\\n") + COMPLIANT.count("\n")
    # ...and nothing else was invented: every non-escape character is intact.
    assert "DONE: 1-Lane-1-Worktree isolation landed" in delivered
    assert "Handoff: /tmp/handoff/x-20261001_000000.md" in delivered


def test_send_never_invents_a_coordinate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Escape expansion is not a licence to fabricate.

    The gate must never resolve a coordinate on the caller's behalf -- that was
    the original "never repairs" rule, and widening the delivery transform must
    not quietly erode it.
    """
    calls: list[list[str]] = []
    monkeypatch.setattr(plugin.herdr, "run_herdr", lambda args, **kw: calls.append(list(args)) or {})

    with pytest.raises(proto.PromptProtocolError):
        proto.send_prompt("w3:p1", "bare", notifier=lambda *a: calls.append(a))

    assert calls == []


def test_send_reports_a_herdr_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def boom(args, **kwargs):
        raise plugin.herdr.HerdrError("target is gone")

    monkeypatch.setattr(plugin.herdr, "run_herdr", boom)
    assert plugin.main(["prompt", "--text", COMPLIANT, "--send", "--target", "w3:p9"]) == 2
    assert "not delivered" in capsys.readouterr().err


# --------------------------------------------------------------------------
# The structural claim, pinned
# --------------------------------------------------------------------------


def test_herdr_exposes_no_prompt_event_to_subscribe_to() -> None:
    """Pin *why* this is a gate and not an interceptor.

    If Herdr ever adds a pre-prompt hook, this test is the reminder that the
    sanctioned-path workaround could be replaced by real enforcement. The event
    list is the documented plugin surface.
    """
    known_events = {
        "workspace.created", "workspace.updated", "workspace.closed", "workspace.focused",
        "tab.created", "tab.closed", "tab.focused",
        "pane.created", "pane.closed", "pane.focused", "pane.exited",
        "pane.agent_detected", "pane.agent_status_changed",
        "pane.output_matched", "pane.scroll_changed",
        "layout.updated",
        "worktree.created", "worktree.opened", "worktree.removed",
    }
    assert not any("prompt" in name for name in known_events)


def test_the_plugin_declares_no_prompt_event_hook() -> None:
    """We cannot intercept, so we must not pretend to have subscribed."""
    raw = (PLUGIN_ROOT / "herdr-plugin.toml").read_text(encoding="utf-8")
    assert "prompt" not in raw.lower().split("[[actions]]")[0]


def test_the_gate_never_substitutes_a_coordinate() -> None:
    """No fabricated arguments: the module holds no send-path of its own."""
    code = "\n".join(
        line
        for line in (LIB / "prompt_protocol.py").read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("#")
    )
    assert "subprocess" not in code
    assert "run_herdr" not in code


# --------------------------------------------------------------------------
# The feedback loop itself
# --------------------------------------------------------------------------


def test_the_probe_goes_green() -> None:
    """Phase 1 loop, re-run as a regression test.

    The probe distinguishes "gate refused this" from "gate does not exist"; an
    absent gate makes argparse exit 2 for *every* input, which would otherwise
    look like a fully working gate.
    """
    proc = subprocess.run(
        [sys.executable, str(PROBE)], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all cases behave as specified" in proc.stdout


def test_the_probe_would_catch_a_regression() -> None:
    """Negative control: the probe is not vacuously green."""
    source = PROBE.read_text(encoding="utf-8")
    assert "ABSENT" in source
    assert "expected=" in source
    # It must contain at least one case that must be refused and one that must
    # pass, or it cannot discriminate.
    assert source.count("        2,") >= 1
    assert source.count("        0,") >= 1