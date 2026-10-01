"""Prompt protocol gate — TB-08.

The incident
------------
An orchestrator sent a bare, unstructured prompt straight through
``herdr agent prompt`` — no evaluated coordinate, no ``[NOTIFY]`` callback
contract — and the plugin system waved it through without the slightest
awareness. The receiving worker got prose where it expected a contract.

Why the plugin could not have caught it
---------------------------------------
``herdr agent prompt`` is a direct CLI/RPC invocation. Herdr's plugin extension
surface is a fixed enumeration of *state-change* notifications
(``pane.created``, ``pane.agent_status_changed``, ``worktree.*`` and so on),
declared in the manifest as ``[[events]] on = ...``. There is no pre-execution
hook, no command middleware and no veto anywhere in the plugin API: verified
against the full Herdr documentation, which contains zero interception points.
``agent.prompt`` is an RPC *command*, not an event, so a plugin cannot subscribe
to it.

So the rule existed as prose in one section of ``SKILL.md`` and as nothing
else. That is the actual defect, and it is not a bug in the validator — there
was no validator.

What this module is
-------------------
A mechanical check for the dispatch prompt contract, plus the sanctioned send
path built on top of it. It **judges and refuses**. It never repairs a prompt:
silently substituting ``${ORCH_PANE}`` would fabricate a coordinate the caller
never verified, and a gate that fixes its own input cannot be trusted to report
on it.

The contract, stated once
-------------------------
A prompt dispatched to a worker must:

1. carry a **resolved** callback coordinate — ``w3:p1``, never ``<orch-pane>``
   or an unexpanded ``${ORCH_PANE}`` (orchestrator lesson 3, coordinate
   misrouting and placeholder leakage);
2. carry a structured ``[NOTIFY]`` callback with ``DONE:`` and ``Handoff:``
   lines, so the worker knows how and where to report back.

Deliberate non-goals (Occam)
---------------------------
No parsing of the task body, no scheduling, no delivery. A prompt that trips
the gate is refused with a message naming every violation at once, so one fix
round clears the dispatch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

# A resolved Herdr pane coordinate: workspace `w<N>`, pane `p<N>`.
COORDINATE_RE = re.compile(r"\bw\d+:p\d+\b")

# Unresolved references. `${ORCH_PANE}` is the documented failure mode; the
# bare `$ORCH_PANE` and `${...}`/`$...` forms are included because they are the
# same bug wearing different clothes.
SHELL_VAR_RE = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?")

# Angle-bracket placeholders as they appear in SKILL.md templates:
# <orch-pane>, <pane_id>, <name>, <repo_slug>, <one-liner conclusion>.
ANGLE_PLACEHOLDER_RE = re.compile(r"<[a-z][a-z0-9_-]*(?: [a-z]+)?>")

# The structured callback markers.
#
# `[ \t]*` rather than `\s*` on purpose: `\s` spans newlines, so
# `^\s*DONE:\s*\S` would match an *empty* `DONE:` by stealing the first
# character of the following line, and a callback with no conclusion would
# sail through the gate it was supposed to fail.
NOTIFY_MARKER = "[NOTIFY]"
DONE_RE = re.compile(r"^[ \t]*DONE:[ \t]*\S", re.MULTILINE)
HANDOFF_RE = re.compile(r"^[ \t]*Handoff:[ \t]*\S", re.MULTILINE)

# Where a callback is being issued. Used to scope the coordinate requirement to
# prompts that actually talk back, rather than demanding a pane id from a prompt
# that never sends one.
CALLBACK_RE = re.compile(r"\bherdr\s+agent\s+prompt\b")


def normalise_escapes(text: str) -> str:
    """Turn literal ``\\n`` sequences into real newlines, for analysis only.

    The canonical template in SKILL.md is written as

        herdr agent prompt w3:p1 '\\n[NOTIFY] [...]\\nDONE: ...'

    Inside bash single quotes ``\\n`` survives as a literal backslash-n, so the
    worker receives escape *characters*, not line breaks. That is the project's
    own documented shape, so a gate that required real newlines would refuse
    every prompt written to its own spec.

    This is a read-side normalisation for structural checks. The text handed to
    ``herdr agent prompt`` is always the caller's original, byte for byte: the
    gate judges, it does not rewrite what will be delivered.
    """
    return (text or "").replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")


class PromptProtocolError(RuntimeError):
    """A prompt was dispatched without satisfying the dispatch contract."""


@dataclass
class PromptReport:
    """The gate's verdict on one prompt."""

    violations: List[str] = field(default_factory=list)
    coordinate: str = ""
    has_notify: bool = False
    has_done: bool = False
    has_handoff: bool = False

    @property
    def ok(self) -> bool:
        return not self.violations

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "coordinate": self.coordinate,
            "has_notify": self.has_notify,
            "has_done": self.has_done,
            "has_handoff": self.has_handoff,
            "violations": list(self.violations),
        }

    def render(self) -> str:
        if self.ok:
            return f"prompt gate: OK (coordinate={self.coordinate or '-'})"
        lines = ["prompt gate: REFUSED"]
        lines += [f"  - {v}" for v in self.violations]
        lines.append(
            "  The worker needs a resolved coordinate and a structured [NOTIFY] "
            "callback. This gate does not repair prompts."
        )
        return "\n".join(lines)


def _placeholder_hits(text: str) -> List[str]:
    """Unresolved references, de-duplicated and ordered."""
    found: List[str] = []
    for match in SHELL_VAR_RE.findall(text):
        if match not in found:
            found.append(match)
    for match in ANGLE_PLACEHOLDER_RE.findall(text):
        if match not in found:
            found.append(match)
    return found


def validate_prompt(text: str, *, require_callback: bool = True) -> PromptReport:
    """Check a prompt against the dispatch contract.

    Pure: returns a report, raises nothing. Callers that must block use
    :func:`assert_prompt_compliant`.

    ``require_callback`` exists for prompts that legitimately end in a question
    with no return leg. It defaults to on, because the incident was precisely a
    prompt that should have had a callback and did not.
    """
    report = PromptReport()
    raw = text or ""
    # Structural checks run on the escape-normalised view; placeholders are
    # matched against the raw text, since `${ORCH_PANE}` survives either way.
    body = normalise_escapes(raw)

    report.coordinate = next(iter(COORDINATE_RE.findall(body)), "")
    report.has_notify = NOTIFY_MARKER in body
    report.has_done = bool(DONE_RE.search(body))
    report.has_handoff = bool(HANDOFF_RE.search(body))

    placeholders = _placeholder_hits(raw)
    if placeholders:
        report.violations.append(
            "unresolved placeholder(s) "
            + ", ".join(placeholders)
            + ": evaluate the real coordinate before dispatch "
            "(`ORCH_PANE=\"$(herdr pane current | jq -r '.result.pane.pane_id')\"`); "
            "an unevaluated placeholder misroutes the callback"
        )

    issues_callback = bool(CALLBACK_RE.search(body))

    if require_callback or issues_callback:
        if not report.has_notify:
            report.violations.append(
                "no [NOTIFY] callback contract: the worker is not told how to "
                "report back, so the orchestrator waits on an IPC that never arrives"
            )
        if not report.coordinate:
            report.violations.append(
                "no resolved pane coordinate (expected w<N>:p<N>): the callback "
                "cannot be addressed without one"
            )
        if report.has_notify:
            if not report.has_done:
                report.violations.append(
                    "[NOTIFY] is missing a 'DONE:' line: state the one-line conclusion"
                )
            if not report.has_handoff:
                report.violations.append(
                    "[NOTIFY] is missing a 'Handoff:' line: state the artifact path"
                )

    return report


def assert_prompt_compliant(text: str, *, require_callback: bool = True) -> PromptReport:
    """Gate for the send path: return the report, or raise.

    The single entry point in front of ``herdr agent prompt``. Raising here is
    the whole point — the incident was a prompt that sailed through because
    nothing stood in front of it.
    """
    report = validate_prompt(text, require_callback=require_callback)
    if not report.ok:
        raise PromptProtocolError(report.render())
    return report


def send_prompt(
    target: str,
    text: str,
    *,
    require_callback: bool = True,
    notifier: Optional[Any] = None,
) -> PromptReport:
    """Validate, then deliver — the sanctioned path to a worker.

    Validation happens strictly before delivery. A refusal means the prompt was
    never sent, so an orchestrator that ignores the exit code still cannot leak
    a malformed prompt to a worker.

    ``notifier`` is injected so the send stays testable and so this module never
    imports the Herdr client. It is called as ``notifier(target, text)``.
    """
    report = assert_prompt_compliant(text, require_callback=require_callback)
    if notifier is not None:
        notifier(target, text)
    return report


def contract_summary() -> Sequence[str]:
    """The rules, for documentation and error messages that need them."""
    return (
        "resolved callback coordinate (w<N>:p<N>), never a placeholder",
        "structured [NOTIFY] callback with DONE: and Handoff: lines",
    )