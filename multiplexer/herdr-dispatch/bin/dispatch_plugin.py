"""Plugin entrypoint — TB-03.

Every command Herdr launches is a fresh, short-lived process, so this module
does no caching between invocations and owns no long-running state. It reads
the shared state file, projects lanes into the sidebar, and exits.

Decoupling
----------
The plugin is one of two deliberately orthogonal surfaces.

- **This side (Herdr)** is one-shot argv commands. It knows panes, worktrees,
  tokens and the board. It has no idea the omp extension exists.
- **The other side (omp)** is in-process. It owns the brain loop, routing and
  the human gate. It never touches the Herdr CLI.

They communicate through exactly one thing: the state file. Nothing here
imports anything omp-side, which is what keeps the plugin reusable in any
project.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import closeout_gate as gate  # noqa: E402
import dispatch_bus as bus  # noqa: E402
import herdr_client as herdr  # noqa: E402
import lane_isolation as isolation  # noqa: E402
import orchestrator_guard as guard_mod  # noqa: E402
import orchestrator_state as brain  # noqa: E402
import prompt_protocol as promptproto  # noqa: E402
import watchdog_judge as watchdog  # noqa: E402

PLUGIN_SOURCE = "plugin:herdr-dispatch"

# Gate refusals are a distinct exit code from a generic failure: 2 means "the
# lifecycle rules refused this", which an orchestrator must not retry past.
EXIT_GATE_REFUSED = 2


def state_path(args: argparse.Namespace) -> Path:
    return brain.state_path(Path(args.repo) if args.repo else None)


def _state(repo: Optional[str]) -> Dict[str, Any]:
    path = brain.state_path(Path(repo) if repo else None)
    try:
        return brain.load(path)
    except brain.StateError as exc:
        print(f"dispatch: {exc}", file=sys.stderr)
        return brain.default_state()


def _lanes(state: Mapping[str, Any]) -> List[Dict[str, Any]]:
    lanes = state.get("lanes") or {}
    out: List[Dict[str, Any]] = []
    for lane_id, lane in sorted(lanes.items()):
        if isinstance(lane, Mapping):
            entry = dict(lane)
            entry.setdefault("lane", lane_id)
            out.append(entry)
    return out


# --------------------------------------------------------------------------
# startup
# --------------------------------------------------------------------------


def cmd_startup(args: argparse.Namespace) -> int:
    """Reconcile the pane registry after a session restore.

    Runs once per enabled plugin after Herdr restores the session and its API
    socket is ready. It is not a daemon: a failure here must not stop the
    server, so every error path reports and returns rather than raising.
    """
    state = _state(args.repo)
    phase = state.get("orchestrator_phase", "unknown")

    # Retire lanes whose pane no longer exists, keeping the evidence. Silently
    # dropping them would make a crashed worker look like a finished one.
    live: Dict[str, Any] = {}
    if herdr.in_herdr():
        try:
            live = {
                a.get("pane_id"): a
                for a in herdr.agent_list()
                if a.get("pane_id")
            }
        except herdr.HerdrError as exc:
            print(f"dispatch startup: agent list unavailable ({exc})")

    lanes = _lanes(state)
    orphans: List[str] = []
    for lane in lanes:
        pane_id = lane.get("pane_id") or lane.get("pane")
        if not pane_id:
            continue
        if pane_id in live:
            # Read-only: Herdr's integration owns this value.
            lane["status"] = live[pane_id].get("agent_status", lane.get("status"))
        else:
            lane["status"] = "orphaned"
            lane["orphan_pane"] = pane_id
            orphans.append(lane["lane"])

    if lanes:
        try:
            brain.update(state_path(args), {"lanes": {l["lane"]: l for l in lanes}})
        except brain.StateError as exc:
            print(f"dispatch startup: state update skipped ({exc})")

    # The view projection is opt-in and off by default; installing it unasked
    # would replace the session's agent_panel_sort policy.
    if herdr.view_enabled_by_default():
        try:
            herdr.set_agent_view(plugin_id=herdr.plugin_root().name, enabled=True)
        except herdr.HerdrError as exc:
            print(f"dispatch startup: agent view not applied ({exc})")

    print(
        f"dispatch startup: phase={phase} lanes={len(lanes)} orphaned={len(orphans)}"
    )
    return 0


# --------------------------------------------------------------------------
# project
# --------------------------------------------------------------------------


def cmd_project(args: argparse.Namespace) -> int:
    """Publish each lane's presentation tokens into the Herdr sidebar.

    Token publication only. Lifecycle status keeps coming from the integration
    that owns it, which is why this reads ``agent_status`` and never writes a
    lifecycle value.
    """
    state = _state(args.repo)
    phase = state.get("orchestrator_phase", "")

    published = 0
    for lane in _lanes(state):
        pane_id = lane.get("pane_id") or lane.get("pane")
        if not pane_id:
            continue
        try:
            herdr.report_lane_metadata(pane_id, lane, brain_phase=phase)
            published += 1
        except herdr.HerdrError as exc:
            print(f"dispatch: pane {pane_id} not projected ({exc})", file=sys.stderr)

    print(f"dispatch: projected {published} lane(s)")
    return 0


# --------------------------------------------------------------------------
# status / harvest / view
# --------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    state = _state(args.repo)
    if args.json:
        print(json.dumps(state, indent=2, ensure_ascii=False))
        return 0
    print(f"brain: {state.get('orchestrator_phase')}")
    if state.get("blocked_reason"):
        print(f"  {state['blocked_reason']}")
    for lane in _lanes(state):
        pane = lane.get("pane_id") or lane.get("pane") or "-"
        print(
            f"  {lane['lane']:<22} {lane.get('status', '?'):<10} "
            f"pane={pane} handoff={'yes' if lane.get('handoff') else 'no'}"
        )
    return 0


def cmd_harvest(args: argparse.Namespace) -> int:
    """Collect lane handoffs and surface any lane still waiting on one.

    Publication stays with the human: this reports, it never pushes.
    """
    state = _state(args.repo)
    ready: List[str] = []
    waiting: List[str] = []
    for lane in _lanes(state):
        handoff = lane.get("handoff")
        if handoff and Path(os.path.expanduser(str(handoff))).is_file():
            ready.append(f"{lane['lane']}: {handoff}")
        else:
            waiting.append(lane["lane"])

    for entry in ready:
        print(f"ready  {entry}")
    for entry in waiting:
        print(f"wait   {entry}")

    if args.notify and ready:
        herdr.notify(
            f"dispatch: {len(ready)} lane(s) ready",
            "; ".join(r.split(":")[0] for r in ready)[:200],
        )
    return 0


def cmd_view(args: argparse.Namespace) -> int:
    if args.off:
        print(json.dumps(herdr.set_agent_view(plugin_id=herdr.plugin_root().name, enabled=False)))
        return 0
    if not args.on:
        print(
            "pass --on or --off; the projection replaces the session's "
            "agent_panel_sort policy, so it is opt-in"
        )
        return 0
    print(json.dumps(herdr.set_agent_view(plugin_id=herdr.plugin_root().name, enabled=True)))
    return 0


# --------------------------------------------------------------------------
# isolation / closeout gates
# --------------------------------------------------------------------------


def cmd_claim(args: argparse.Namespace) -> int:
    """Claim a worktree and branch for a lane, or refuse.

    The dispatch-time anti-stomping check. ``--worktree``/``--branch`` describe
    the lane about to be dispatched; the refusal is the product, so a collision
    exits 2 rather than degrading to a warning.
    """
    state = _state(args.repo)
    lanes = state.get("lanes") or {}

    audit = isolation.audit_claim(
        lanes,
        args.lane,
        worktree=args.worktree or "",
        branch=args.branch or "",
    )
    if args.json:
        print(json.dumps(audit.as_dict(), indent=2, ensure_ascii=False))
        return 0 if audit.ok else EXIT_GATE_REFUSED

    if not audit.ok:
        for violation in audit.violations:
            print(f"dispatch: lane {args.lane}: {violation}", file=sys.stderr)
        return EXIT_GATE_REFUSED

    print(f"dispatch: lane {args.lane} may claim {audit.worktree} @ {audit.branch}")
    return 0


def cmd_closeout(args: argparse.Namespace) -> int:
    """Evaluate the Closeout Lifecycle Gate for one lane.

    Reports whether the worktree may be destroyed and whether the worker pane
    may be closed. It never closes anything itself: the gate that authorises an
    irreversible action cannot also be the thing that performs it.
    """
    evidence: Dict[str, Dict[str, Any]] = {}
    if args.evidence:
        try:
            loaded = json.loads(args.evidence)
        except json.JSONDecodeError as exc:
            print(f"dispatch: --evidence is not valid JSON ({exc})", file=sys.stderr)
            return 2
        if not isinstance(loaded, dict):
            print("dispatch: --evidence must be a JSON object", file=sys.stderr)
            return 2
        evidence = {k: v for k, v in loaded.items() if isinstance(v, dict)}

    report = gate.evaluate_closeout(args.lane, evidence)
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(report.render())
    return 0 if report.allowed else EXIT_GATE_REFUSED


def cmd_prompt(args: argparse.Namespace) -> int:
    """Validate a worker prompt, and optionally deliver it.

    The gate stands in front of ``herdr agent prompt`` because nothing upstream
    can: Herdr's plugin surface is a fixed set of state-change events with no
    pre-execution hook, so a direct CLI prompt is unobservable to a plugin. This
    is the sanctioned path, and ``--send`` refuses *before* delivery so a
    malformed prompt never reaches a worker.
    """
    if args.stdin:
        text = sys.stdin.read()
        origin = "<stdin>"
    elif args.file:
        path = Path(os.path.expanduser(args.file))
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"dispatch: cannot read {path} ({exc})", file=sys.stderr)
            return 2
        origin = str(path)
    elif args.text:
        text = args.text
        origin = "<arg>"
    else:
        print("dispatch: pass --stdin, --file or --text", file=sys.stderr)
        return 2

    report = promptproto.validate_prompt(text, require_callback=not args.allow_no_callback)

    if not report.ok:
        if args.json:
            print(json.dumps({"source": origin, **report.as_dict()}, indent=2, ensure_ascii=False))
        else:
            print(f"dispatch: {report.render()}", file=sys.stderr)
        return EXIT_GATE_REFUSED

    if args.send:
        if not args.target:
            print("dispatch: --send requires --target <pane>", file=sys.stderr)
            return 2
        # Deliver the expanded text. The single-quoted '\n[NOTIFY] ...' form is
        # what produced the one-line report: bash keeps the backslash-n as two
        # characters, so the worker got escape sequences instead of line breaks.
        # Validation still judged the caller's text; only the bytes on the wire
        # are normalised. --keep-escapes opts out for anyone who means them.
        payload = text if getattr(args, "keep_escapes", False) else promptproto.normalise_escapes(text)
        try:
            herdr.run_herdr(["agent", "prompt", args.target, payload])
        except herdr.HerdrError as exc:
            print(f"dispatch: prompt not delivered ({exc})", file=sys.stderr)
            return 2
        if promptproto.has_literal_escape(payload) and not args.json:
            print(
                "dispatch: note - some backslash escapes remain literal "
                "(expected inside fenced code, or a doubled backslash such as "
                "\\\\n). Write a single \\n for a real line break.",
                file=sys.stderr,
            )
        print(f"dispatch: prompt delivered to {args.target}")
        return 0

    if args.json:
        print(json.dumps({"source": origin, **report.as_dict()}, indent=2, ensure_ascii=False))
    else:
        print(f"dispatch: prompt OK (coordinate={report.coordinate or '-'}) from {origin}")
    return 0


def cmd_notify(args: argparse.Namespace) -> int:
    """Build and send the standard structured report, with real newlines.

    The reason this exists: `herdr agent prompt p '\\n[NOTIFY] ...'` keeps the
    backslash-n as two literal characters, because bash single quotes do not
    expand escapes. The report then renders as one long line. Generating the
    text here means callers never hand-quote it at all.
    """
    sections: Dict[str, List[str]] = {}
    for raw in args.section or []:
        title, _, items = raw.partition("=")
        sections[title.strip()] = [i.strip() for i in items.split("|") if i.strip()]

    text = promptproto.build_notify(
        args.signature,
        args.done,
        args.handoff,
        args.target,
        highlights=args.highlight or [],
        risks=args.risk or [],
        sections=sections,
    )

    if not args.send:
        print(text)
        return 0

    try:
        herdr.run_herdr(["agent", "prompt", args.target, text])
    except herdr.HerdrError as exc:
        print(f"dispatch: report not delivered ({exc})", file=sys.stderr)
        return 2
    print(f"dispatch: report delivered to {args.target}", file=sys.stderr)
    return 0


def cmd_guard(args: argparse.Namespace) -> int:
    """Enforce the orchestrator permission whitelist for one action.

    The phase defaults to whatever the shared state file records, because the
    whole point is to police the brain as it actually is rather than what the
    caller believes it is.
    """
    phase = args.phase
    if not phase:
        state = _state(args.repo)
        phase = str(state.get("orchestrator_phase") or brain.DEFAULT_BRAIN_PHASE)

    try:
        guard = guard_mod.OrchestratorGuard(phase, wake_signal=args.wake_signal or "")
    except ValueError as exc:
        print(f"dispatch: {exc}", file=sys.stderr)
        return EXIT_GATE_REFUSED

    if args.list:
        print(json.dumps({"phase": phase, "allowed": guard.allowed_actions()}, indent=2))
        return 0

    verdict = guard.evaluate(args.action)
    if args.json:
        print(json.dumps(verdict.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(verdict.render(), file=sys.stdout if verdict.allowed else sys.stderr)
    return 0 if verdict.allowed else EXIT_GATE_REFUSED


def cmd_dispatch(args: argparse.Namespace) -> int:
    """Dispatch a lane in one atomic command.

    Replaces six manual steps, each of which could be skipped: contract lint,
    the claim gate, pane rename, timestamp minting, envelope assembly and the
    brain state flush. Planning happens before any mutation, so a refusal from
    any gate leaves the pane name, the state file and the worker untouched.

    Exits 1 for a malformed contract and 2 for a rule refusal, so an
    orchestrator can tell "fix your task file" from "this lane is unsafe".
    """
    # The bus owns the pane rename so planning stays pure; it resolves the Herdr
    # client itself, so nothing here needs rebinding.
    try:
        plan = bus.DispatchPlan.plan(
            repo=Path(args.repo) if args.repo else Path.cwd(),
            task=Path(os.path.expanduser(args.task)),
            lane=args.lane,
            lane_name=args.lane_name,
            target=args.target,
            signature=args.signature,
            worktree=args.worktree or "",
            branch=args.branch or "",
            highlights=args.highlight or [],
            risks=args.risk or [],
        )
    except bus.DispatchRefused as exc:
        print(f"dispatch: {exc}", file=sys.stderr)
        return exc.exit_code

    plan.commit()

    # Delivery last: it is the only mutation the worker can observe, and it must
    # go through the same prompt gate the bus validated the envelope against.
    report = promptproto.validate_prompt(plan.envelope)
    if not report.ok:
        # Unreachable in practice: planning asserts compliance. Left in place
        # because a silent skip here is exactly the omission this command exists
        # to prevent.
        print(f"dispatch: refusing to deliver: {report.render()}", file=sys.stderr)
        return EXIT_GATE_REFUSED

    try:
        herdr.run_herdr(["agent", "prompt", plan.target, plan.envelope])
    except herdr.HerdrError as exc:
        print(f"dispatch: delivery failed ({exc})", file=sys.stderr)
        return EXIT_GATE_REFUSED

    print(bus.receipt(plan))
    return 0


def cmd_watchdog(args: argparse.Namespace) -> int:
    """Gate D: Zero-Token Semantic Watchdog check (Issue #134).

    Evaluates whether a quiet child lane is running heavy computation (compilation/test)
    or is stalled/deadlocked. If legitimate, extends lease by 10m (zero false alarms).
    If stalled, nudges or alerts.
    """
    path = state_path(args)
    try:
        state = brain.load(path)
    except brain.StateError:
        state = _state(getattr(args, "repo", None))
    lanes = _lanes(state)
    target_lanes: List[Dict[str, Any]] = []

    if args.lane:
        matched = [l for l in lanes if l.get("lane") == args.lane]
        if matched:
            target_lanes = matched
        else:
            lane_dict = state.get("lanes", {}).get(args.lane, {})
            target_lanes = [{"lane": args.lane, "pane_id": lane_dict.get("pane_id") or lane_dict.get("pane")}]
    elif args.sweep:
        awaiting = state.get("brain", {}).get("awaiting_lanes", [])
        if awaiting:
            target_lanes = [l for l in lanes if l.get("lane") in awaiting]
        else:
            target_lanes = lanes
    else:
        print("dispatch watchdog: specify --lane <lane> or --sweep", file=sys.stderr)
        return 1

    results = []
    for lane_entry in target_lanes:
        lane_id = lane_entry.get("lane")
        pane_id = lane_entry.get("pane_id") or lane_entry.get("pane")
        if not lane_id:
            continue

        buffer_text = ""
        process_name = ""
        if pane_id and herdr.in_herdr():
            try:
                read_res = herdr.run_herdr(["pane", "read", pane_id, "--source", "visible"])
                if isinstance(read_res, Mapping):
                    buffer_text = read_res.get("text", "")
                elif isinstance(read_res, str):
                    buffer_text = read_res
            except herdr.HerdrError:
                buffer_text = ""
            try:
                info = herdr.agent_info(pane_id)
                process_name = info.get("process_name") or info.get("command") or ""
            except herdr.HerdrError:
                pass
        elif getattr(args, "buffer", ""):
            buffer_text = getattr(args, "buffer", "")
            process_name = getattr(args, "process", "")

        judgment = watchdog.evaluate_watchdog_state(
            buffer_tail=buffer_text,
            process_name=process_name,
        )

        res: Dict[str, Any] = {
            "lane": lane_id,
            "pane_id": pane_id or "",
            "verdict": judgment.verdict.value,
            "p_legitimate": judgment.p_legitimate,
            "p_stalled": judgment.p_stalled,
            "reason": judgment.reason,
            "model": judgment.model,
        }

        if judgment.verdict == watchdog.WatchdogVerdict.EXTEND_LEASE:
            watchdog.apply_lease_extension(
                state_path(args),
                lane_id,
                judgment.verdict,
                extension_seconds=judgment.lease_extension_seconds,
            )
            res["lease_extended_seconds"] = judgment.lease_extension_seconds
        elif judgment.verdict == watchdog.WatchdogVerdict.NUDGE:
            if pane_id and herdr.in_herdr() and judgment.nudge_command:
                try:
                    herdr.run_herdr(["pane", "send-keys", pane_id, judgment.nudge_command])
                    res["nudge_sent"] = True
                except herdr.HerdrError:
                    res["nudge_sent"] = False

        results.append(res)

    if args.json:
        print(json.dumps({"results": results}, indent=2, ensure_ascii=False))
    else:
        for r in results:
            print(f"[{r['verdict']}] Lane {r['lane']} (pane {r['pane_id']}): {r['reason']}")
            if "lease_extended_seconds" in r:
                print(f"  -> Watchdog lease extended by {r['lease_extended_seconds']}s")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dispatch-plugin", description="herdr-dispatch plugin commands (TB-03)"
    )
    parser.add_argument("--repo", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    startup = sub.add_parser("startup", help="reconcile panes after session restore")
    startup.set_defaults(func=cmd_startup)

    project = sub.add_parser("project", help="publish lane tokens to the sidebar")
    project.set_defaults(func=cmd_project)

    status = sub.add_parser("status", help="show brain phase and lanes")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    harvest = sub.add_parser("harvest", help="collect lane handoffs")
    harvest.add_argument("--notify", action="store_true")
    harvest.set_defaults(func=cmd_harvest)

    view = sub.add_parser("view", help="install or clear the Agents view projection")
    view.add_argument("--on", action="store_true")
    view.add_argument("--off", action="store_true")
    view.set_defaults(func=cmd_view)

    claim = sub.add_parser(
        "claim", help="claim a worktree and branch for a lane (1 Lane = 1 Worktree = 1 Branch)"
    )
    claim.add_argument("--lane", required=True)
    claim.add_argument("--worktree", default="")
    claim.add_argument("--branch", default="")
    claim.add_argument("--json", action="store_true")
    claim.set_defaults(func=cmd_claim)

    closeout = sub.add_parser(
        "closeout", help="evaluate the Closeout Lifecycle Gate before cleanup/pane close"
    )
    closeout.add_argument("--lane", default="")
    closeout.add_argument(
        "--evidence", default="", help="JSON object of closeout step facts"
    )
    closeout.add_argument("--json", action="store_true")
    closeout.set_defaults(func=cmd_closeout)

    prompt = sub.add_parser(
        "prompt",
        help="validate a worker prompt against the dispatch contract (and optionally send it)",
    )
    source = prompt.add_mutually_exclusive_group(required=True)
    source.add_argument("--stdin", action="store_true", help="read the prompt from stdin")
    source.add_argument("--file", default="", help="read the prompt from a file")
    source.add_argument("--text", default="", help="the prompt itself")
    prompt.add_argument("--send", action="store_true", help="deliver after validating")
    prompt.add_argument("--target", default="", help="target pane for --send")
    prompt.add_argument("--json", action="store_true")
    prompt.add_argument(
        "--allow-no-callback",
        action="store_true",
        help="permit a prompt with no [NOTIFY] return leg (questions, one-way nudges)",
    )
    prompt.add_argument(
        "--keep-escapes",
        action="store_true",
        help="deliver the text byte-for-byte instead of expanding standard escapes",
    )
    prompt.set_defaults(func=cmd_prompt)

    notify = sub.add_parser(
        "notify",
        help="build and send the standard multi-line [NOTIFY] report",
    )
    notify.add_argument("--signature", required=True, help="pane_id_agent_kind_repo_slug")
    notify.add_argument("--done", required=True, help="one-line conclusion")
    notify.add_argument("--handoff", required=True, help="handoff artifact path")
    notify.add_argument("--target", required=True, help="destination pane, e.g. w3:p1")
    notify.add_argument(
        "--highlight", action="append", default=[], help="core result bullet (repeatable)"
    )
    notify.add_argument(
        "--risk", action="append", default=[], help="risk / leftover bullet (repeatable)"
    )
    notify.add_argument(
        "--section",
        action="append",
        default=[],
        help="extra titled section as 'Title=item|item' (repeatable)",
    )
    notify.add_argument("--send", action="store_true", help="deliver instead of printing")
    notify.set_defaults(func=cmd_notify)

    guard = sub.add_parser(
        "guard",
        help="check an orchestrator action against the per-phase permission whitelist",
    )
    guard.add_argument("--action", default="", help="the orchestrator action to check")
    guard.add_argument(
        "--phase",
        default="",
        help="brain phase (default: whatever the state file records)",
    )
    guard.add_argument("--wake-signal", default="", help="signal when checking a wake action")
    guard.add_argument("--list", action="store_true", help="list what is permitted in the phase")
    guard.add_argument("--json", action="store_true")
    guard.set_defaults(func=cmd_guard)

    dispatch = sub.add_parser(
        "dispatch",
        help="dispatch a lane atomically: lint, claim, rename, timestamp, state flush, deliver",
    )
    dispatch.add_argument("--task", required=True, help="task contract file (7-section + #125)")
    dispatch.add_argument("--lane", required=True, help="lane id, e.g. 1-3")
    dispatch.add_argument(
        "--lane-name",
        required=True,
        help=f"pane label, must match {bus.LANE_NAME_PATTERN} (e.g. 1-3-dispatch)",
    )
    dispatch.add_argument("--target", required=True, help="target pane, e.g. w3:p9")
    dispatch.add_argument(
        "--signature", default="", help="[NOTIFY] signature, defaults to <lane-name>_<target>"
    )
    dispatch.add_argument("--worktree", default="", help="worktree to claim (optional)")
    dispatch.add_argument("--branch", default="", help="branch to claim (optional)")
    dispatch.add_argument("--highlight", action="append", default=[])
    dispatch.add_argument("--risk", action="append", default=[])
    dispatch.set_defaults(func=cmd_dispatch)

    watchdog_p = sub.add_parser(
        "watchdog",
        help="Gate D: evaluate semantic watchdog on quiet lane(s) (Issue #134)",
    )
    watchdog_p.add_argument("--lane", default="", help="lane id to evaluate, e.g. 1-4")
    watchdog_p.add_argument("--repo", default=None, help="repository root")
    watchdog_p.add_argument("--sweep", action="store_true", help="sweep all awaiting lanes")
    watchdog_p.add_argument("--buffer", default="", help="test buffer override")
    watchdog_p.add_argument("--process", default="", help="test process name override")
    watchdog_p.add_argument("--json", action="store_true")
    watchdog_p.set_defaults(func=cmd_watchdog)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except (
        brain.StateError,
        herdr.HerdrError,
        isolation.LaneCollisionError,
        gate.CloseoutGateError,
        promptproto.PromptProtocolError,
        guard_mod.IllegalOrchestratorActionError,
        bus.DispatchRefused,
    ) as exc:
        # A plugin command must fail visibly but never wedge the server. Gate
        # refusals land here too, and deliberately share exit 2: an orchestrator
        # must not be able to tell "the lifecycle rules refused this" apart from
        # "something broke" and sail past it.
        print(f"dispatch: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())