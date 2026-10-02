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

# A resolved Herdr pane coordinate. Herdr IDs are opaque/alphanumeric
# (e.g. `w3:pB`, `wD:p1`), so validation must not assume decimal-only IDs.
COORDINATE_RE = re.compile(r"\bw[0-9A-Za-z]+:p[0-9A-Za-z]+\b")

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
TASK_MARKER = "[DISPATCH]"
TASK_RE = re.compile(r"^[ \t]*Task:[ \t]*(\S.*)$", re.MULTILINE)
LANE_RE = re.compile(r"^[ \t]*Lane:[ \t]*([0-9]+-[0-9]+)[ \t]*$", re.MULTILINE)
RUN_ID_RE = re.compile(r"^[ \t]*Run ID:[ \t]*(run-[0-9a-f]+)[ \t]*$", re.MULTILINE)
DISPATCH_ID_RE = re.compile(r"^[ \t]*Dispatch ID:[ \t]*(dispatch-[0-9a-f]+)[ \t]*$", re.MULTILINE)
CALLBACK_TARGET_RE = re.compile(r"^[ \t]*Callback target:[ \t]*(\S+)[ \t]*$", re.MULTILINE)
SIGNATURE_RE = re.compile(r"^[ \t]*Signature:[ \t]*(\S+)[ \t]*$", re.MULTILINE)
CALLBACK_COMMAND_RE = re.compile(r"^[ \t]*Callback command:[ \t]*(\S.*)$", re.MULTILINE)


# Escapes this module will expand. Deliberately tiny: only the three control
# escapes that make a report render as one line. Anything else -- `\\x41`, `\\u`,
# octal, and notably `\\\\` -- is left exactly as written.
#
# `\\\\` is excluded on purpose. Shell `$'...'` already collapses it before this
# code runs, so by the time a message arrives here a surviving `\\\\` is either
# something the caller genuinely meant (a Windows path, a regex) or an escaped
# backslash followed by an `n` we must not touch. Collapsing it ourselves makes
# `\\\\n` ambiguous between "escaped backslash + n" and "backslash-n escape",
# which quietly breaks the one property that makes this function safe to run
# twice: `path\\\\name` would come back as `path<newline>ame`.
EXPANDABLE = {"n": "\n", "r": "\r", "t": "\t"}

# Fenced-code delimiters. Their contents are passed through untouched: a shell
# example inside a report legitimately contains `\\n` as two characters, and
# expanding it would deform the sample the reader is meant to copy.
FENCE_CHARS = ("`", "~")
FENCE_MIN_RUN = 3


def _run_length(text: str, index: int, char: str) -> int:
    length = 0
    while index + length < len(text) and text[index + length] == char:
        length += 1
    return length


def normalise_escapes(text: str) -> str:
    """Expand literal ``\\n`` / ``\\t`` / ``\\r`` into real control characters.

    The canonical SKILL.md template is written as

        herdr agent prompt w3:p1 '\\n[NOTIFY] [...]\\nDONE: ...'

    and bash single quotes keep ``\\n`` as two literal characters. The worker
    therefore receives escape sequences instead of line breaks and the report
    renders as one long single-line string -- the defect this fixes.

    Properties, each of which cost a naive implementation something:

    - **UTF-8 safe.** No latin-1 round trip, so non-ASCII passes through
      byte-for-byte. ``encode().decode('unicode_escape')`` would turn
      ``修复完成`` into ``ä¿®å¤å®``; every report here is full of Chinese.
    - **Code blocks are protected.** Fenced content is copied verbatim, so a
      shell sample containing ``\\n`` stays intact.
    - **Conservative.** Only ``\\n``, ``\\r``, ``\\t`` and ``\\\\`` are expanded.
      An unrecognised escape is preserved rather than interpreted.
    - **Idempotent.** Expanding twice equals expanding once.

    A single scanner rather than a regex split, because fence detection has to
    happen *before* expansion while the fence markers are still preceded by
    literal ``\\n``. Splitting on ``^```$`` first matches nothing on exactly the
    input that needs protecting: the escaping is what makes the line structure
    invisible.
    """
    if not text:
        return ""

    out: List[str] = []
    index = 0
    length = len(text)
    at_line_start = True
    fence_char = ""   # non-empty while inside a fenced block

    while index < length:
        char = text[index]

        if char == "\\" and index + 1 < length:
            following = text[index + 1]
            if fence_char:
                # Inside a fence: verbatim, but a real newline still ends a line.
                out.append(char)
                out.append(following)
                if following == "\n" or char == "\n":
                    at_line_start = True
                index += 2
                continue
            if following in EXPANDABLE:
                # A written `\r\n` is one line ending, not two control
                # characters, so collapse it the way a text editor would.
                # A lone `\r` stays a carriage return rather than being
                # silently promoted to a line feed.
                if (
                    following == "r"
                    and index + 3 < length
                    and text[index + 2] == "\\"
                    and text[index + 3] == "n"
                ):
                    out.append("\n")
                    index += 4
                else:
                    out.append(EXPANDABLE[following])
                    index += 2
            else:
                # Everything else -- including `\\` and unknown escapes -- is
                # copied verbatim rather than interpreted. See EXPANDABLE.
                out.append(char)
                out.append(following)
                index += 2
                continue
            at_line_start = True
            continue

        if char == "\n":
            out.append(char)
            index += 1
            at_line_start = True
            continue

        if at_line_start and char in FENCE_CHARS and _run_length(text, index, char) >= FENCE_MIN_RUN:
            run = _run_length(text, index, char)
            if fence_char:
                if char == fence_char:
                    fence_char = ""  # closing fence; leave at_line_start True
            else:
                fence_char = char
            out.append(char * run)
            index += run
            at_line_start = False
            continue

        out.append(char)
        index += 1
        at_line_start = False

    return "".join(out)


def has_literal_escape(text: str) -> bool:
    """True when standard escapes survive :func:`normalise_escapes`.

    Prose escapes are always expanded, so a survivor sat inside a fenced code
    block -- which is correct, not a fault. Callers use this to emit an
    informational note, never to refuse a message.
    """
    stripped = normalise_escapes(text or "")
    return "\\n" in stripped or "\\t" in stripped or "\\r" in stripped


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
                "no resolved pane coordinate (expected opaque Herdr id like w3:pB): the callback "
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


def validate_task_request(text: str) -> PromptReport:
    """Validate the request leg independently from a completion report.

    A dispatch request starts with ``[DISPATCH]`` and carries a concrete task
    reference plus a separately resolved callback target. It may describe how
    to emit a ``[NOTIFY]`` later, but it is never itself a completion report.
    """
    body = normalise_escapes(text or "")
    report = PromptReport()
    if not body.startswith(TASK_MARKER + "\n"):
        report.violations.append("task request must start with [DISPATCH]")
    task = TASK_RE.search(body)
    lane = LANE_RE.search(body)
    run_id = RUN_ID_RE.search(body)
    dispatch_id = DISPATCH_ID_RE.search(body)
    callback = CALLBACK_TARGET_RE.search(body)
    signature = SIGNATURE_RE.search(body)
    command = CALLBACK_COMMAND_RE.search(body)
    report.coordinate = callback.group(1) if callback else ""
    report.has_handoff = bool(HANDOFF_RE.search(body))
    if not task:
        report.violations.append("task request is missing a 'Task:' reference")
    if not lane:
        report.violations.append("task request is missing a resolved 'Lane:' identity")
    if not run_id:
        report.violations.append("task request is missing a stable 'Run ID:' identity")
    if not dispatch_id:
        report.violations.append("task request is missing a stable 'Dispatch ID:' identity")
    if not callback or not COORDINATE_RE.fullmatch(callback.group(1)):
        report.violations.append("task request has no resolved callback target")
    if not signature:
        report.violations.append("task request is missing a 'Signature:' identity")
    if not report.has_handoff:
        report.violations.append("task request is missing a 'Handoff:' artifact path")
    if not command or "dispatch_plugin.py notify" not in command.group(1):
        report.violations.append("task request is missing the executable notify callback command")
    return report


def assert_task_request_compliant(text: str) -> PromptReport:
    report = validate_task_request(text)
    if not report.ok:
        raise PromptProtocolError(report.render())
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


def build_task_request(
    task: str,
    lane: str,
    run_id: str,
    dispatch_id: str,
    signature: str,
    handoff: str,
    callback_target: str,
    *,
    plugin_path: str,
) -> str:
    """Build the request leg; completion semantics stay in ``build_notify``."""
    import shlex

    command = (
        "test -n \"${DONE_SUMMARY:-}\" && "
        f"python3 {shlex.quote(plugin_path)} notify "
        f"--signature {shlex.quote(signature)} --done \"$DONE_SUMMARY\" "
        f"--handoff {shlex.quote(handoff)} --target {shlex.quote(callback_target)} --send"
    )
    body = (
        f"{TASK_MARKER}\n"
        f"Task: {task}\n"
        f"Lane: {lane}\n"
        f"Run ID: {run_id}\n"
        f"Dispatch ID: {dispatch_id}\n"
        "Read the task contract above and execute it within its stated boundaries.\n"
        f"Callback target: {callback_target}\n"
        f"Signature: {signature}\n"
        f"Handoff: {handoff}\n"
        "When complete, write the handoff, set DONE_SUMMARY to a one-line conclusion, then run:\n"
        f"Callback command: {command}"
    )
    assert_task_request_compliant(body)
    return body


def contract_summary() -> Sequence[str]:
    """The rules, for documentation and error messages that need them."""
    return (
        "resolved opaque callback coordinate (e.g. w3:pB), never a placeholder",
        "structured [NOTIFY] callback with DONE: and Handoff: lines",
    )


# --------------------------------------------------------------------------
# Standard report formatting
# --------------------------------------------------------------------------

NOTIFY_TEMPLATE = (
    "[NOTIFY] [{signature}]\n"
    "DONE: {done}\n"
    "Handoff: {handoff}\n"
    "回调目标坐标: {target}\n"
    "\n"
    "[核心成果与证据]\n"
    "{highlights}\n"
    "\n"
    "[风险与遗留]\n"
    "{risks}"
)


def _bullets(items: Sequence[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- 无"


def build_notify(
    signature: str,
    done: str,
    handoff: str,
    target: str,
    *,
    highlights: Sequence[str] = (),
    risks: Sequence[str] = (),
    sections: Mapping[str, Sequence[str]] = (),
    normalise: bool = True,
) -> str:
    """Render the standard multi-line dispatch report.

    Building the text here rather than in a shell command is the point: the
    single-quoted ``'\\n[NOTIFY] ...'`` form that produced the one-line defect is
    a quoting accident waiting to happen, and every caller should not have to
    remember ``$'...'``.

    ``normalise`` runs the escape expansion, so a caller that still passes
    literal ``\\n`` gets real newlines rather than a silently single-line
    report.
    """
    body = NOTIFY_TEMPLATE.format(
        signature=signature,
        done=done,
        handoff=handoff,
        target=target,
        highlights=_bullets(highlights),
        risks=_bullets(risks),
    )
    for title, items in (sections or {}).items():
        body += f"\n\n[{title}]\n{_bullets(items)}"
    return normalise_escapes(body) if normalise else body


def format_notify_lines(
    signature: str,
    done: str,
    handoff: str,
    target: str,
    *,
    highlights: Sequence[str] = (),
    risks: Sequence[str] = (),
) -> str:
    """The same report as shell-ready, newline-joined arguments.

    Emits one shell-quoted token per line for callers that prefer to build the
    command themselves. ``shlex.quote`` keeps a line containing spaces or
    quotes intact, which is the other way these reports get mangled.
    """
    import shlex

    report = build_notify(
        signature, done, handoff, target, highlights=highlights, risks=risks
    )
    return " ".join(shlex.quote(line) for line in report.splitlines())