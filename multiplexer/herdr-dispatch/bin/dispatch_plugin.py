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
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

AUTHORIZATION_KEY_ENV = "HERDR_DISPATCH_RUNTIME_AUTH_KEY"
# Capture once and remove immediately, before importing any repository modules.
# The proof key belongs only to this frozen Python process; Git, Herdr and any
# future subprocess must never inherit it through the ambient environment.
_AUTHORIZATION_RUNTIME_KEY = os.environ.pop(AUTHORIZATION_KEY_ENV, "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import closeout_gate as gate  # noqa: E402
import dispatch_bus as bus  # noqa: E402
import handoff_judge as handoff  # noqa: E402
import herdr_client as herdr  # noqa: E402
import lane_isolation as isolation  # noqa: E402
import orchestrator_guard as guard_mod  # noqa: E402
import orchestrator_state as brain  # noqa: E402
import prompt_protocol as promptproto  # noqa: E402
import watchdog_judge as watchdog  # noqa: E402

PLUGIN_SOURCE = "plugin:herdr-dispatch"
CAPABILITY_STATUS = {
    "routing": "enabled",
    "external_lane_routing": "enabled",
    "resource_admission": "omp_spawn_enabled",
    "host_memory_probe": "enabled",
    "semantic_watchdog": "offline_default_online_opt_in",
    "automatic_nudge": "disabled",
    "automatic_abort": "disabled",
    "context_pruning": "policy_only_disabled",
    "session_rollover": "policy_only_disabled",
    "phase_model_downgrade": "policy_only_disabled",
}


def _command_version(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        return "unavailable"
    try:
        result = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return (result.stdout or result.stderr).strip().splitlines()[0] or "unknown"


def _certification_state(actual: str, expected: str) -> str:
    if actual == "unavailable":
        return "unsupported"
    if actual == "unknown":
        return "unknown"
    return "certified" if expected in actual else "not_verified"


def capability_status() -> Dict[str, Any]:
    baseline = {
        "omp": "18.5.0",
        "herdr": "0.9.3",
        "codex": "0.160.0",
        "bun": "1.4.2",
    }
    versions = {name: _command_version(name) for name in baseline}
    return {
        **CAPABILITY_STATUS,
        "plugin_entrypoint": "enabled",
        "omp_extension": "separate_surface_not_probed",
        "host_versions": versions,
        "certification_baseline": baseline,
        "certification_status": {
            name: _certification_state(versions[name], expected)
            for name, expected in baseline.items()
        },
    }


# Gate refusals are a distinct exit code from a generic failure: 2 means "the
# lifecycle rules refused this", which an orchestrator must not retry past.
EXIT_GATE_REFUSED = 2

# Delivery failed *after* the plan committed. Its own code because the remedy is
# the opposite of every other failure: the lane is recorded and holding a claim,
# so retrying collides with itself. Reporting this as 2 tells the caller
# "nothing was renamed, written or delivered", which is false here — the state
# file has a lane marked working that no worker will ever pick up.
EXIT_DELIVERY_FAILED = 3

# The status a lane carries when the dispatch committed but the worker was never
# told to start. Distinct from "working" because the two mean opposite things to
# a watchdog: "working" implies a running process, and a stall alarm on a lane
# that was never dispatched sends the orchestrator to investigate a worker that
# does not exist.
DELIVERY_UNKNOWN_STATUS = "delivery_unknown"
DELIVERY_REJECTED_STATUS = "delivery_rejected"


def state_path(args: argparse.Namespace) -> Path:
    return brain.state_path(Path(args.repo) if args.repo else None)


def _state(repo: Optional[str]) -> Dict[str, Any]:
    """Load authoritative state; corruption is a refusal, never an empty run."""
    path = brain.state_path(Path(repo) if repo else None)
    return brain.load(path)


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

    # Lifecycle observation is evidence, not ownership. A query failure or a
    # pane absent from one snapshot cannot release a worktree claim.
    live: Dict[str, Any] = {}
    lifecycle_observed = False
    if herdr.in_herdr():
        try:
            live = {
                a.get("pane_id"): a
                for a in herdr.agent_list()
                if a.get("pane_id")
            }
            lifecycle_observed = True
        except herdr.HerdrError as exc:
            print(f"dispatch startup: agent list unavailable ({exc})")

    lanes = _lanes(state)
    recovery_required: List[str] = []
    if lifecycle_observed and lanes:
        def reconcile(current: Dict[str, Any]) -> Dict[str, Any]:
            current_lanes = current.setdefault("lanes", {})
            for lane_id, lane in list(current_lanes.items()):
                if not isinstance(lane, dict):
                    continue
                pane_id = lane.get("pane_id") or lane.get("pane")
                if not pane_id:
                    continue
                if pane_id in live:
                    lane["status"] = live[pane_id].get("agent_status", lane.get("status"))
                    lane.pop("recovery_pane", None)
                else:
                    lane["status"] = "recovery_required"
                    lane["recovery_pane"] = pane_id
                    recovery_required.append(str(lane_id))
            return current

        brain.mutate(state_path(args), reconcile)

    # The view projection is opt-in and off by default; installing it unasked
    # would replace the session's agent_panel_sort policy.
    if herdr.view_enabled_by_default():
        try:
            herdr.set_agent_view(plugin_id=herdr.plugin_root().name, enabled=True)
        except herdr.HerdrError as exc:
            print(f"dispatch startup: agent view not applied ({exc})")

    print(
        f"dispatch startup: phase={phase} lanes={len(lanes)} "
        f"recovery_required={len(recovery_required)}"
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
    if getattr(args, "capabilities", False):
        capabilities = capability_status()
        if args.json:
            print(json.dumps({"capabilities": capabilities}, indent=2, ensure_ascii=False))
        else:
            for name, status in capabilities.items():
                if isinstance(status, Mapping):
                    print(f"{name}: {json.dumps(status, ensure_ascii=False, sort_keys=True)}")
                else:
                    print(f"{name}: {status}")
        return 0

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


def _closeout_evidence(raw: str) -> tuple[Dict[str, Dict[str, Any]], str]:
    if not raw:
        return {}, ""
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"dispatch: --evidence is not valid JSON ({exc})"
    if not isinstance(loaded, dict):
        return {}, "dispatch: --evidence must be a JSON object"
    return {k: v for k, v in loaded.items() if isinstance(v, dict)}, ""


def _formal_gate_c_truth(
    lane: Mapping[str, Any],
    authority: Optional[Mapping[str, Any]] = None,
) -> tuple[Dict[str, Any], str]:
    gate_c = lane.get("gate_c")
    if not isinstance(gate_c, Mapping) or gate_c.get("accepted") is not True:
        return {}, "dispatch: current lane has no accepted formal Gate C report"
    binding = gate_c.get("binding")
    if not isinstance(binding, Mapping):
        return {}, "dispatch: current Gate C report has no binding"
    proof_ok = _gate_c_proof_valid(gate_c)
    if not proof_ok and isinstance(authority, Mapping):
        proof_ok = bool(
            _authorization_proof_valid(authority)
            and authority.get("gate_c_report_id") == gate_c.get("report_id")
            and authority.get("revision") == binding.get("revision")
            and authority.get("run_id") == binding.get("run_id")
            and authority.get("dispatch_id") == binding.get("dispatch_id")
        )
    if not proof_ok:
        return {}, "dispatch: current formal Gate C proof is invalid or stale"
    return {
        "handoff_verdict": "ACCEPTED",
        "handoff_accepted": True,
        "verified": True,
    }, ""


def _authorization_payload(record: Mapping[str, Any]) -> str:
    fields = (
        "authorization_id",
        "action",
        "repo",
        "remote",
        "push_url",
        "ref",
        "destination_ref",
        "pr_url",
        "pr_base",
        "pr_head_ref",
        "cleanup_evidence_digest",
        "run_id",
        "lane",
        "dispatch_id",
        "gate_c_report_id",
        "revision",
        "outcome",
        "delivery_scope",
        "authorized_unix_ms",
        "consumed_unix_ms",
    )
    return "\n".join(
        "" if record.get(field) is None else str(record.get(field))
        for field in fields
    )


def _authorization_proof(record: Mapping[str, Any], key: str) -> str:
    if not key:
        return ""
    return hmac.new(
        key.encode("utf-8"),
        _authorization_payload(record).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _authorization_proof_valid(record: Mapping[str, Any]) -> bool:
    key = _AUTHORIZATION_RUNTIME_KEY
    proof = str(record.get("authorization_proof") or "")
    return bool(key and proof) and hmac.compare_digest(
        proof, _authorization_proof(record, key)
    )


def _matching_authorization(
    state: Mapping[str, Any],
    lane_id: str,
    *,
    action: str,
    repo: str,
    ref: str,
    consumed: Optional[bool] = None,
) -> Optional[Mapping[str, Any]]:
    lane = (state.get("lanes") or {}).get(lane_id)
    if not isinstance(lane, Mapping):
        return None
    gate_c = lane.get("gate_c")
    if not isinstance(gate_c, Mapping):
        return None
    binding = gate_c.get("binding")
    if not isinstance(binding, Mapping):
        return None

    for record in ((state.get("extra_data") or {}).get("authorizations") or []):
        if not isinstance(record, Mapping):
            continue
        if not _authorization_proof_valid(record):
            continue
        is_consumed = bool(record.get("consumed_unix_ms"))
        if consumed is not None and is_consumed is not consumed:
            continue
        if (
            record.get("action") == action
            and record.get("repo") == repo
            and record.get("ref") == ref
            and record.get("run_id") == state.get("run_id")
            and record.get("lane") == lane_id
            and record.get("dispatch_id") == lane.get("dispatch_id")
            and record.get("gate_c_report_id") == gate_c.get("report_id")
            and record.get("revision") == binding.get("revision")
            and str(record.get("outcome") or "") == str(gate_c.get("outcome") or "delivered")
            and str(record.get("delivery_scope") or "") == str(binding.get("delivery_scope") or "")
        ):
            return record
    return None


def _revoke_lane_closeout_state(state: Dict[str, Any], lane_id: str) -> None:
    """Invalidate Gate C and every authority derived from it for one lane."""
    lane = (state.get("lanes") or {}).get(lane_id)
    if not isinstance(lane, dict):
        return
    lane.pop("gate_c", None)
    lane.pop("cleanup_authorization", None)
    for field in (
        "cleanup_started_unix_ms",
        "cleanup_started_authorization_id",
        "cleanup_executor_pid",
        "cleanup_removed_unix_ms",
        "cleanup_finalized_unix_ms",
    ):
        lane.pop(field, None)
    extra = state.get("extra_data") or {}
    records = extra.get("authorizations")
    if isinstance(records, list):
        extra["authorizations"] = [
            record
            for record in records
            if not (
                isinstance(record, Mapping)
                and record.get("lane") == lane_id
                and record.get("run_id") == state.get("run_id")
            )
        ]


def _gate_c_payload(gate_c: Mapping[str, Any]) -> str:
    binding = gate_c.get("binding") or {}
    fields = (
        gate_c.get("report_id"),
        gate_c.get("accepted"),
        gate_c.get("outcome"),
        binding.get("repo"),
        binding.get("run_id"),
        binding.get("lane"),
        binding.get("dispatch_id"),
        binding.get("handoff"),
        binding.get("revision"),
        binding.get("delivery_scope"),
        binding.get("evidence_digest"),
        gate_c.get("verified_unix_ms"),
    )
    def canonical(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    return "\n".join(canonical(value) for value in fields)


def _gate_c_proof(gate_c: Mapping[str, Any], key: str) -> str:
    if not key:
        return ""
    return hmac.new(
        key.encode("utf-8"),
        _gate_c_payload(gate_c).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _gate_c_proof_valid(gate_c: Mapping[str, Any]) -> bool:
    key = _AUTHORIZATION_RUNTIME_KEY
    proof = str(gate_c.get("gate_c_proof") or "")
    return bool(key and proof) and hmac.compare_digest(proof, _gate_c_proof(gate_c, key))


def _cleanup_payload(lane: Mapping[str, Any], cleanup: Mapping[str, Any]) -> str:
    fields = (
        cleanup.get("authorization_id"),
        cleanup.get("gate_c_report_id"),
        cleanup.get("run_id"),
        cleanup.get("dispatch_id"),
        cleanup.get("worktree"),
        cleanup.get("revision"),
        cleanup.get("outcome"),
        cleanup.get("delivery_scope"),
        cleanup.get("cleanup_evidence_digest"),
        cleanup.get("reauthorized_from_authorization_id"),
        lane.get("cleanup_started_unix_ms"),
        lane.get("cleanup_started_authorization_id"),
        lane.get("cleanup_executor_pid"),
        lane.get("cleanup_removed_unix_ms"),
    )
    return "\n".join(str(value or "") for value in fields)


def _cleanup_proof(lane: Mapping[str, Any], cleanup: Mapping[str, Any], key: str) -> str:
    if not key:
        return ""
    return hmac.new(
        key.encode("utf-8"),
        _cleanup_payload(lane, cleanup).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _cleanup_proof_valid(lane: Mapping[str, Any], cleanup: Mapping[str, Any]) -> bool:
    key = _AUTHORIZATION_RUNTIME_KEY
    proof = str(cleanup.get("cleanup_proof") or "")
    return bool(key and proof) and hmac.compare_digest(
        proof, _cleanup_proof(lane, cleanup, key)
    )


def _resign_cleanup(lane: Dict[str, Any], cleanup: Dict[str, Any]) -> None:
    key = _AUTHORIZATION_RUNTIME_KEY
    if not key:
        raise brain.StateError("protected cleanup executor has no runtime authorization key")
    cleanup["cleanup_proof"] = _cleanup_proof(lane, cleanup, key)


def _resign_authorization(record: Dict[str, Any]) -> None:
    key = _AUTHORIZATION_RUNTIME_KEY
    if not key:
        raise brain.StateError("protected cleanup executor has no runtime authorization key")
    record["authorization_proof"] = _authorization_proof(record, key)


def cmd_record_outcome(args: argparse.Namespace) -> int:
    """Record an honest failed/cancelled terminal lane without releasing its claim."""
    path = state_path(args)

    def record(state: Dict[str, Any]) -> Dict[str, Any]:
        lane = (state.get("lanes") or {}).get(args.lane)
        if not isinstance(lane, dict):
            raise brain.StateError(f"lane {args.lane!r} is not in the current run")
        if (
            lane.get("run_id") != state.get("run_id")
            or not lane.get("dispatch_id")
        ):
            raise brain.StateError("lane identity does not match the current run")

        _revoke_lane_closeout_state(state, args.lane)
        lane = state["lanes"][args.lane]
        lane["status"] = args.outcome
        lane["phase"] = "terminal"
        lane["terminal_outcome"] = args.outcome
        lane["terminal_reason"] = args.reason
        lane["terminal_unix_ms"] = brain.now_unix_ms()

        waiting = list((state.get("brain") or {}).get("awaiting_lanes") or [])
        state.setdefault("brain", {})["awaiting_lanes"] = [
            lane_id for lane_id in waiting if lane_id != args.lane
        ]
        if (
            state.get("orchestrator_phase") == "yield_and_guard"
            and not state["brain"]["awaiting_lanes"]
        ):
            signal = "stall_alarm" if args.outcome == "failed" else "human"
            brain.advance(state, "synthesis", wake_signal=signal)
        return state

    try:
        updated = brain.mutate(path, record)
    except brain.StateError as exc:
        print(f"dispatch: {exc}", file=sys.stderr)
        return EXIT_GATE_REFUSED

    payload = {
        "lane": args.lane,
        "outcome": args.outcome,
        "reason": args.reason,
        "claim_released": False,
        "orchestrator_phase": updated.get("orchestrator_phase"),
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(
            f"dispatch: lane {args.lane} recorded {args.outcome}; "
            "physical claim remains held for recovery/cleanup"
        )
    return 0


def cmd_authorize_cleanup(args: argparse.Namespace) -> int:
    """Prove that the current lane may have its exact worktree removed."""
    evidence, err = _closeout_evidence(args.evidence)
    if err:
        print(err, file=sys.stderr)
        return EXIT_GATE_REFUSED

    state = _state(args.repo)
    lane = (state.get("lanes") or {}).get(args.lane)
    if not isinstance(lane, Mapping):
        print(f"dispatch: lane {args.lane!r} is not in the current run", file=sys.stderr)
        return EXIT_GATE_REFUSED
    if lane.get("run_id") != state.get("run_id") or not lane.get("dispatch_id"):
        print("dispatch: lane identity does not match the current run", file=sys.stderr)
        return EXIT_GATE_REFUSED

    gate_c = lane.get("gate_c") or {}
    binding = gate_c.get("binding") or {}
    if (
        binding.get("run_id") != state.get("run_id")
        or binding.get("lane") != args.lane
        or binding.get("dispatch_id") != lane.get("dispatch_id")
    ):
        print("dispatch: Gate C binding does not match the current lane", file=sys.stderr)
        return EXIT_GATE_REFUSED

    worktree = str(lane.get("worktree") or "")
    if not worktree:
        print("dispatch: current lane has no claimed worktree", file=sys.stderr)
        return EXIT_GATE_REFUSED
    try:
        current_revision = _git_text(Path(worktree), "rev-parse", "HEAD")
        repo_root = _git_text(Path(args.repo or "."), "rev-parse", "--show-toplevel")
    except brain.StateError as exc:
        print(f"dispatch: cannot verify current cleanup revision ({exc})", file=sys.stderr)
        return EXIT_GATE_REFUSED

    expected_revision = str(binding.get("revision") or "")
    if not expected_revision or current_revision != expected_revision:
        print(
            "dispatch: current Git HEAD no longer matches the accepted Gate C revision",
            file=sys.stderr,
        )
        return EXIT_GATE_REFUSED

    resolved_repo = str(Path(repo_root).resolve())
    resolved_worktree = str(Path(worktree).resolve())
    outcome = str(gate_c.get("outcome") or "delivered")
    if outcome not in {"delivered", "no_change"}:
        print(f"dispatch: unsupported Gate C outcome {outcome!r}", file=sys.stderr)
        return EXIT_GATE_REFUSED
    if outcome == "no_change":
        try:
            dirty = _git_text(Path(worktree), "status", "--porcelain")
        except brain.StateError as exc:
            print(f"dispatch: cannot verify no-change worktree ({exc})", file=sys.stderr)
            return EXIT_GATE_REFUSED
        if dirty:
            print(
                "dispatch: no-change cleanup refused because the worktree is dirty",
                file=sys.stderr,
            )
            return EXIT_GATE_REFUSED

    if binding.get("repo") and binding.get("repo") != resolved_repo:
        print("dispatch: Gate C repository binding does not match the current repo", file=sys.stderr)
        return EXIT_GATE_REFUSED

    authority = _matching_authorization(
        state,
        args.lane,
        action="remove_worktree",
        repo=resolved_repo,
        ref=resolved_worktree,
        consumed=False,
    )
    if authority is None:
        print(
            "dispatch: no unconsumed human authorization matches this worktree removal",
            file=sys.stderr,
        )
        return EXIT_GATE_REFUSED
    try:
        cleanup_steps = _required_closeout_steps(
            str(binding.get("delivery_scope") or ""),
            outcome,
        )
    except brain.StateError as exc:
        print(f"dispatch: {exc}", file=sys.stderr)
        return EXIT_GATE_REFUSED
    evidence_digest = _cleanup_evidence_digest(evidence, cleanup_steps)
    if authority.get("cleanup_evidence_digest") != evidence_digest:
        print(
            "dispatch: cleanup evidence was not part of the explicit human authorization",
            file=sys.stderr,
        )
        return EXIT_GATE_REFUSED
    truth, truth_err = _formal_gate_c_truth(lane, authority)
    if truth_err:
        print(truth_err, file=sys.stderr)
        return EXIT_GATE_REFUSED
    report = gate.evaluate_cleanup_authorization(
        args.lane,
        evidence,
        truthfulness=truth,
        steps=cleanup_steps,
    )
    if not report.allowed:
        if args.json:
            print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
        else:
            print(report.render())
        return EXIT_GATE_REFUSED

    path = state_path(args)

    def persist(current: Dict[str, Any]) -> Dict[str, Any]:
        current_lane = (current.get("lanes") or {}).get(args.lane)
        if not isinstance(current_lane, dict):
            raise brain.StateError("lane disappeared before cleanup authorization commit")
        current_authority = _matching_authorization(
            current,
            args.lane,
            action="remove_worktree",
            repo=resolved_repo,
            ref=resolved_worktree,
            consumed=False,
        )
        if current_authority is None:
            raise brain.StateError("human cleanup authorization became stale before commit")
        current_lane["cleanup_authorization"] = {
            "authorization_id": current_authority.get("authorization_id"),
            "gate_c_report_id": gate_c.get("report_id"),
            "run_id": current.get("run_id"),
            "dispatch_id": current_lane.get("dispatch_id"),
            "worktree": resolved_worktree,
            "revision": expected_revision,
            "outcome": outcome,
            "delivery_scope": str(binding.get("delivery_scope") or ""),
            "cleanup_evidence_digest": evidence_digest,
        }
        _resign_cleanup(current_lane, current_lane["cleanup_authorization"])
        return current

    try:
        brain.mutate(path, persist)
    except brain.StateError as exc:
        print(f"dispatch: {exc}", file=sys.stderr)
        return EXIT_GATE_REFUSED

    if args.json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(report.render())
    return 0


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _worker_quiescent_for_cleanup(lane: Mapping[str, Any]) -> tuple[bool, str]:
    """Require a completed/idle worker, never a lane still actively working."""
    pane_id = str(lane.get("pane_id") or lane.get("pane") or "")
    if herdr.in_herdr() and pane_id:
        try:
            info = herdr.agent_info(pane_id)
        except herdr.HerdrError as exc:
            return False, f"cannot verify worker lifecycle before cleanup ({exc})"
        status = str(info.get("agent_status") or "")
        if status not in {"idle", "done"}:
            return False, f"worker {pane_id} is still {status or 'unknown'}"
        return True, ""

    persisted_status = str(lane.get("status") or "")
    persisted_phase = str(lane.get("phase") or "")
    if persisted_status in {"idle", "done"} or persisted_phase == "done":
        return True, ""
    return False, (
        "worker lifecycle is not quiescent and no authoritative Herdr lifecycle "
        "record is available"
    )


def cmd_cleanup_worktree(args: argparse.Namespace) -> int:
    """Execute the already-authorized worktree removal and consume its authority."""
    state = _state(args.repo)
    lane = (state.get("lanes") or {}).get(args.lane)
    if not isinstance(lane, Mapping):
        print(f"dispatch: lane {args.lane!r} is not in the current run", file=sys.stderr)
        return EXIT_GATE_REFUSED
    cleanup = lane.get("cleanup_authorization")
    if not isinstance(cleanup, Mapping):
        print("dispatch: cleanup was never authorized for this lane", file=sys.stderr)
        return EXIT_GATE_REFUSED
    cleanup_proof_valid = _cleanup_proof_valid(lane, cleanup)

    try:
        repo_root = _git_text(Path(args.repo or "."), "rev-parse", "--show-toplevel")
    except brain.StateError as exc:
        print(f"dispatch: cannot resolve current repo ({exc})", file=sys.stderr)
        return EXIT_GATE_REFUSED
    resolved_repo = str(Path(repo_root).resolve())
    worktree = str(cleanup.get("worktree") or "")
    authority = _matching_authorization(
        state,
        args.lane,
        action="remove_worktree",
        repo=resolved_repo,
        ref=worktree,
        consumed=False,
    )
    if authority is None:
        print(
            "dispatch: no current-session unconsumed human authorization matches this cleanup; "
            "reauthorize remove_worktree after an OMP restart",
            file=sys.stderr,
        )
        return EXIT_GATE_REFUSED

    worktree_path = Path(worktree)
    path = state_path(args)

    # A root OMP restart deliberately rotates the runtime authorization key, so
    # persisted human authority from the old session becomes unusable. If the
    # process crashed after the physical worktree removal but before authority
    # consumption, the old cleanup proof is stale too. Recovery is allowed only
    # for that narrow post-removal state and only after a fresh human authority
    # for the exact same lane worktree has been issued in the new session.
    if not cleanup_proof_valid:
        if worktree_path.exists():
            print(
                "dispatch: cleanup authorization proof is invalid or stale; "
                "rerun authorize-cleanup before removing the worktree",
                file=sys.stderr,
            )
            return EXIT_GATE_REFUSED

        started_by = str(lane.get("cleanup_started_authorization_id") or "")
        started_at = lane.get("cleanup_started_unix_ms")
        old_authorization_id = str(cleanup.get("authorization_id") or "")
        gate_c = lane.get("gate_c") or {}
        binding = gate_c.get("binding") or {}
        lane_worktree = str(Path(str(lane.get("worktree") or "")).resolve())
        structurally_current = bool(
            started_at
            and started_by
            and old_authorization_id
            and started_by == old_authorization_id
            and lane_worktree == worktree
            and cleanup.get("gate_c_report_id") == gate_c.get("report_id")
            and cleanup.get("run_id") == state.get("run_id")
            and cleanup.get("dispatch_id") == lane.get("dispatch_id")
            and cleanup.get("revision") == binding.get("revision")
            and str(cleanup.get("outcome") or "delivered")
            == str(gate_c.get("outcome") or "delivered")
            and str(cleanup.get("delivery_scope") or "")
            == str(binding.get("delivery_scope") or "")
        )
        if not structurally_current:
            print(
                "dispatch: stale cleanup record does not match the current Gate C binding",
                file=sys.stderr,
            )
            return EXIT_GATE_REFUSED

        def rebind_after_restart(current: Dict[str, Any]) -> Dict[str, Any]:
            current_lane = (current.get("lanes") or {}).get(args.lane)
            if not isinstance(current_lane, dict):
                raise brain.StateError("lane disappeared during cleanup recovery")
            current_cleanup = current_lane.get("cleanup_authorization") or {}
            if not isinstance(current_cleanup, dict):
                raise brain.StateError("cleanup authorization disappeared during recovery")
            current_gate_c = current_lane.get("gate_c") or {}
            current_binding = current_gate_c.get("binding") or {}
            current_worktree = str(Path(str(current_lane.get("worktree") or "")).resolve())
            previous_id = str(current_cleanup.get("authorization_id") or "")
            if (
                current_worktree != worktree
                or str(current_lane.get("cleanup_started_authorization_id") or "") != previous_id
                or not current_lane.get("cleanup_started_unix_ms")
                or current_cleanup.get("gate_c_report_id") != current_gate_c.get("report_id")
                or current_cleanup.get("run_id") != current.get("run_id")
                or current_cleanup.get("dispatch_id") != current_lane.get("dispatch_id")
                or current_cleanup.get("revision") != current_binding.get("revision")
                or str(current_cleanup.get("outcome") or "delivered")
                != str(current_gate_c.get("outcome") or "delivered")
                or str(current_cleanup.get("delivery_scope") or "")
                != str(current_binding.get("delivery_scope") or "")
            ):
                raise brain.StateError("stale cleanup record changed during restart recovery")
            fresh_authority = _matching_authorization(
                current,
                args.lane,
                action="remove_worktree",
                repo=resolved_repo,
                ref=worktree,
                consumed=False,
            )
            if fresh_authority is None:
                raise brain.StateError(
                    "fresh human cleanup authorization became stale during recovery"
                )
            current_cleanup["reauthorized_from_authorization_id"] = previous_id
            current_cleanup["authorization_id"] = fresh_authority.get("authorization_id")
            _resign_cleanup(current_lane, current_cleanup)
            return current

        try:
            brain.mutate(path, rebind_after_restart)
        except brain.StateError as exc:
            print(f"dispatch: {exc}", file=sys.stderr)
            return EXIT_GATE_REFUSED

        state = _state(args.repo)
        lane = (state.get("lanes") or {}).get(args.lane) or {}
        cleanup = lane.get("cleanup_authorization") or {}
        authority = _matching_authorization(
            state,
            args.lane,
            action="remove_worktree",
            repo=resolved_repo,
            ref=worktree,
            consumed=False,
        )
        if authority is None or not _cleanup_proof_valid(lane, cleanup):
            print("dispatch: cleanup restart recovery could not be authenticated", file=sys.stderr)
            return EXIT_GATE_REFUSED

    if worktree_path.exists():
        quiescent, quiescent_reason = _worker_quiescent_for_cleanup(lane)
        if not quiescent:
            print(f"dispatch: cleanup refused because {quiescent_reason}", file=sys.stderr)
            return EXIT_GATE_REFUSED
        try:
            current_revision = _git_text(worktree_path, "rev-parse", "HEAD")
            dirty = _git_text(worktree_path, "status", "--porcelain")
            listed = _git_text(Path(resolved_repo), "worktree", "list", "--porcelain")
        except brain.StateError as exc:
            print(f"dispatch: cannot inspect authorized worktree ({exc})", file=sys.stderr)
            return EXIT_GATE_REFUSED
        if current_revision != cleanup.get("revision"):
            print(
                "dispatch: cleanup refused because current HEAD no longer matches "
                "the accepted Gate C revision",
                file=sys.stderr,
            )
            return EXIT_GATE_REFUSED
        if dirty:
            print(
                "dispatch: cleanup refused because the authorized worktree is dirty",
                file=sys.stderr,
            )
            return EXIT_GATE_REFUSED
        marker = f"worktree {worktree}"
        if marker not in listed.splitlines():
            print(
                "dispatch: authorized path is not a worktree owned by the current repository",
                file=sys.stderr,
            )
            return EXIT_GATE_REFUSED

        def mark_started(current: Dict[str, Any]) -> Dict[str, Any]:
            current_lane = (current.get("lanes") or {}).get(args.lane)
            if not isinstance(current_lane, dict):
                raise brain.StateError("lane disappeared before cleanup start")
            current_cleanup = current_lane.get("cleanup_authorization") or {}
            if not isinstance(current_cleanup, dict) or not _cleanup_proof_valid(
                current_lane, current_cleanup
            ):
                raise brain.StateError("cleanup authorization proof became stale before removal start")
            current_authority = _matching_authorization(
                current,
                args.lane,
                action="remove_worktree",
                repo=resolved_repo,
                ref=worktree,
                consumed=False,
            )
            if current_authority is None:
                raise brain.StateError("cleanup authority became stale before removal start")

            executor_pid = int(current_lane.get("cleanup_executor_pid") or 0)
            if executor_pid and executor_pid != os.getpid() and _pid_is_alive(executor_pid):
                raise brain.StateError(
                    f"cleanup is already executing in live pid {executor_pid}"
                )

            previous_authorization_id = str(current_cleanup.get("authorization_id") or "")
            current_authorization_id = str(current_authority.get("authorization_id") or "")
            if previous_authorization_id != current_authorization_id:
                current_cleanup["reauthorized_from_authorization_id"] = previous_authorization_id
                current_cleanup["authorization_id"] = current_authorization_id

            current_lane["cleanup_started_unix_ms"] = brain.now_unix_ms()
            current_lane["cleanup_started_authorization_id"] = current_authorization_id
            current_lane["cleanup_executor_pid"] = os.getpid()
            _resign_cleanup(current_lane, current_cleanup)
            return current

        try:
            brain.mutate(path, mark_started)
        except brain.StateError as exc:
            print(f"dispatch: {exc}", file=sys.stderr)
            return EXIT_GATE_REFUSED

        try:
            subprocess.run(
                ["git", "-C", resolved_repo, "worktree", "remove", worktree],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"dispatch: worktree removal failed ({exc})", file=sys.stderr)
            return EXIT_GATE_REFUSED
    else:
        started_by = str(lane.get("cleanup_started_authorization_id") or "")
        started_at = lane.get("cleanup_started_unix_ms")
        if not started_by or not started_at:
            print(
                "dispatch: authorized worktree disappeared outside the authorized cleanup executor",
                file=sys.stderr,
            )
            return EXIT_GATE_REFUSED

    def consume(current: Dict[str, Any]) -> Dict[str, Any]:
        current_lane = (current.get("lanes") or {}).get(args.lane)
        if not isinstance(current_lane, dict):
            raise brain.StateError("lane disappeared before cleanup consumption")
        current_cleanup = current_lane.get("cleanup_authorization") or {}
        if not isinstance(current_cleanup, dict) or not _cleanup_proof_valid(
            current_lane, current_cleanup
        ):
            raise brain.StateError("cleanup authorization proof became stale before consumption")
        current_authority = _matching_authorization(
            current,
            args.lane,
            action="remove_worktree",
            repo=resolved_repo,
            ref=worktree,
            consumed=False,
        )
        if current_authority is None:
            raise brain.StateError("cleanup authority became stale before consumption")
        started_by = str(current_lane.get("cleanup_started_authorization_id") or "")
        if not started_by or not current_lane.get("cleanup_started_unix_ms"):
            raise brain.StateError("cleanup removal has no matching executor start record")

        current_authorization_id = str(current_authority.get("authorization_id") or "")
        previous_authorization_id = str(current_cleanup.get("authorization_id") or "")
        if current_authorization_id != previous_authorization_id:
            current_cleanup["reauthorized_from_authorization_id"] = previous_authorization_id
            current_cleanup["authorization_id"] = current_authorization_id
            current_lane["cleanup_started_authorization_id"] = current_authorization_id

        now = brain.now_unix_ms()
        current_authority["consumed_unix_ms"] = now
        _resign_authorization(current_authority)
        current_lane["cleanup_removed_unix_ms"] = now
        current_lane.pop("cleanup_executor_pid", None)
        _resign_cleanup(current_lane, current_cleanup)
        return current

    try:
        brain.mutate(path, consume)
    except brain.StateError as exc:
        print(f"dispatch: {exc}", file=sys.stderr)
        return EXIT_GATE_REFUSED

    payload = {
        "lane": args.lane,
        "worktree": worktree,
        "removed": not worktree_path.exists(),
        "authorization_id": authority.get("authorization_id"),
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"dispatch: removed authorized worktree {worktree}")
    return 0


def cmd_finalize_closeout(args: argparse.Namespace) -> int:
    """Release a lane only after its authorized worktree removal was consumed."""
    evidence, err = _closeout_evidence(args.evidence)
    if err:
        print(err, file=sys.stderr)
        return EXIT_GATE_REFUSED

    state = _state(args.repo)
    lane = (state.get("lanes") or {}).get(args.lane)
    if not isinstance(lane, Mapping):
        print(f"dispatch: lane {args.lane!r} is not in the current run", file=sys.stderr)
        return EXIT_GATE_REFUSED
    cleanup = lane.get("cleanup_authorization")
    if not isinstance(cleanup, Mapping):
        print("dispatch: cleanup was never authorized for this lane", file=sys.stderr)
        return EXIT_GATE_REFUSED
    if not _cleanup_proof_valid(lane, cleanup):
        print("dispatch: cleanup authorization proof is invalid or stale", file=sys.stderr)
        return EXIT_GATE_REFUSED

    try:
        repo_root = _git_text(Path(args.repo or "."), "rev-parse", "--show-toplevel")
    except brain.StateError as exc:
        print(f"dispatch: cannot resolve current repo ({exc})", file=sys.stderr)
        return EXIT_GATE_REFUSED
    resolved_repo = str(Path(repo_root).resolve())
    worktree = str(cleanup.get("worktree") or "")
    authority = _matching_authorization(
        state,
        args.lane,
        action="remove_worktree",
        repo=resolved_repo,
        ref=worktree,
        consumed=True,
    )
    if authority is None or authority.get("authorization_id") != cleanup.get("authorization_id"):
        print(
            "dispatch: human worktree-removal authorization has not been consumed",
            file=sys.stderr,
        )
        return EXIT_GATE_REFUSED
    try:
        attested_steps = _required_closeout_steps(
            str(cleanup.get("delivery_scope") or ""),
            str(cleanup.get("outcome") or "delivered"),
        )
    except brain.StateError as exc:
        print(f"dispatch: {exc}", file=sys.stderr)
        return EXIT_GATE_REFUSED
    evidence_digest = _cleanup_evidence_digest(evidence, attested_steps)
    if (
        cleanup.get("cleanup_evidence_digest") != evidence_digest
        or authority.get("cleanup_evidence_digest") != evidence_digest
    ):
        print(
            "dispatch: final closeout evidence does not match the human-attested cleanup evidence",
            file=sys.stderr,
        )
        return EXIT_GATE_REFUSED
    if Path(worktree).exists():
        print("dispatch: authorized worktree still exists; finalization is premature", file=sys.stderr)
        return EXIT_GATE_REFUSED

    truth, truth_err = _formal_gate_c_truth(lane, authority)
    if truth_err:
        print(truth_err, file=sys.stderr)
        return EXIT_GATE_REFUSED
    outcome = str(cleanup.get("outcome") or "delivered")
    gate_c = lane.get("gate_c") or {}
    gate_binding = gate_c.get("binding") or {}
    if (
        outcome != str(gate_c.get("outcome") or "delivered")
        or str(cleanup.get("delivery_scope") or "")
        != str(gate_binding.get("delivery_scope") or "")
    ):
        print("dispatch: cleanup outcome/scope no longer matches Gate C", file=sys.stderr)
        return EXIT_GATE_REFUSED
    final_evidence = dict(evidence)
    final_evidence["worktree_removed"] = {"worktree_absent": True}
    try:
        required_steps = _required_closeout_steps(
            str(cleanup.get("delivery_scope") or ""),
            outcome,
        )
    except brain.StateError as exc:
        print(f"dispatch: {exc}", file=sys.stderr)
        return EXIT_GATE_REFUSED
    final_steps = (*required_steps, "worktree_removed")
    report = gate.evaluate_closeout(
        args.lane,
        final_evidence,
        steps=final_steps,
        truthfulness=truth,
    )
    if not report.allowed:
        if args.json:
            print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
        else:
            print(report.render())
        return EXIT_GATE_REFUSED

    path = state_path(args)

    def finalize(current: Dict[str, Any]) -> Dict[str, Any]:
        current_lane = (current.get("lanes") or {}).get(args.lane)
        if not isinstance(current_lane, dict):
            raise brain.StateError("lane disappeared before finalization")
        current_cleanup = current_lane.get("cleanup_authorization") or {}
        if not isinstance(current_cleanup, dict) or not _cleanup_proof_valid(
            current_lane, current_cleanup
        ):
            raise brain.StateError("cleanup proof became stale before finalization")
        if (
            current.get("run_id") != cleanup.get("run_id")
            or current_lane.get("dispatch_id") != cleanup.get("dispatch_id")
            or current_cleanup.get("authorization_id") != cleanup.get("authorization_id")
        ):
            raise brain.StateError("cleanup identity became stale before finalization")
        if current_lane.get("status") == "released" or current_lane.get("phase") == "closed":
            raise brain.StateError("lane is already finalized")
        current_authority = _matching_authorization(
            current,
            args.lane,
            action="remove_worktree",
            repo=resolved_repo,
            ref=worktree,
            consumed=True,
        )
        if (
            current_authority is None
            or current_authority.get("authorization_id")
            != current_cleanup.get("authorization_id")
        ):
            raise brain.StateError("consumed human authority became stale before finalization")
        if Path(worktree).exists():
            raise brain.StateError("worktree reappeared before finalization")
        current_lane["status"] = "released"
        current_lane["phase"] = "closed"
        current_lane["terminal_outcome"] = outcome
        current_lane["cleanup_finalized_unix_ms"] = brain.now_unix_ms()
        waiting = list((current.get("brain") or {}).get("awaiting_lanes") or [])
        current.setdefault("brain", {})["awaiting_lanes"] = [
            lane_id for lane_id in waiting if lane_id != args.lane
        ]
        active = (current.get("active_panes") or {}).get("lanes")
        if isinstance(active, dict):
            active.pop(args.lane, None)
        return current

    try:
        brain.mutate(path, finalize)
    except brain.StateError as exc:
        print(f"dispatch: {exc}", file=sys.stderr)
        return EXIT_GATE_REFUSED

    if args.json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(report.render())
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

    truthfulness, truth_err = _truthfulness(args)
    if truth_err:
        print(truth_err, file=sys.stderr)
        return 2

    report = gate.evaluate_closeout(
        args.lane,
        evidence,
        truthfulness=truthfulness,
        purpose="diagnostic",
    )
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(report.render())
    return 0 if report.allowed else EXIT_GATE_REFUSED


def _truthfulness(args: argparse.Namespace) -> tuple[Optional[Dict[str, Any]], str]:
    """Load a Gate C report supplied as ``--handoff-report`` into gate facts.

    A truthfulness report is mandatory for this diagnostic path. Omitting it
    is an error: no legacy/diagnostic command may imply closeout authority from
    non-Gate-C evidence alone.
    """
    raw = getattr(args, "handoff_report", None)
    if not raw:
        return None, "dispatch: --handoff-report is required for closeout evaluation"
    # Accept either a path to a Gate C report or the report itself, so a caller
    # can pipe it in the same way every other evidence input is supplied.
    if os.path.exists(raw):
        try:
            raw = Path(os.path.expanduser(raw)).read_text(encoding="utf-8")
        except OSError as exc:
            return None, f"dispatch: cannot read --handoff-report {raw} ({exc})"
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"dispatch: --handoff-report is not valid JSON ({exc})"
    if not isinstance(loaded, dict) or "verdict" not in loaded:
        return None, (
            "dispatch: --handoff-report must be a Gate C report object "
            "carrying a 'verdict' field"
        )
    accepted = bool(loaded.get("accepted"))
    return {
        "handoff_verdict": loaded.get("verdict"),
        "handoff_accepted": accepted,
        "verified": accepted,
    }, ""


def _read_evidence_input(
    inline: Optional[str], path: Optional[str], label: str
) -> tuple[str, str]:
    """Resolve one evidence input from an inline string or a file.

    ``-`` means stdin, which is how a caller pipes a handoff or a live test log
    without staging a temp file. Returns ``(text, error)`` rather than raising,
    so the caller decides the exit code.
    """
    if inline is not None:
        return inline, ""
    if not path:
        return "", ""
    if path == "-":
        return sys.stdin.read(), ""
    resolved = Path(os.path.expanduser(path))
    try:
        return resolved.read_text(encoding="utf-8", errors="replace"), ""
    except OSError as exc:
        return "", f"dispatch: cannot read {label} {resolved} ({exc})"


def _git_text(cwd: Path, *argv: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *argv],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise brain.StateError(f"git {' '.join(argv)} failed in {cwd}: {exc}") from exc
    return result.stdout.strip()


def _required_closeout_steps(scope: str, outcome: str) -> tuple[str, ...]:
    if outcome == "no_change":
        return ()
    if scope == "local":
        return ("docs_aligned",)
    if scope == "repository":
        return ("docs_aligned", "child_pushed", "pr_merged")
    if scope == "submodule":
        return gate.PRE_CLEANUP_STEPS
    raise brain.StateError(f"unsupported Gate C delivery scope {scope!r}")


def _cleanup_evidence_digest(
    evidence: Mapping[str, Mapping[str, Any]],
    steps: Sequence[str],
) -> str:
    projection = {step: dict(evidence.get(step) or {}) for step in steps}
    canonical = json.dumps(projection, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _formal_gate_c_binding(args: argparse.Namespace) -> tuple[Dict[str, Any], str]:
    """Bind a Gate C report to the current authoritative lane and Git revision."""
    if not args.lane:
        return {}, "dispatch verify-handoff: --bind-current requires --lane"
    if not args.handoff or args.handoff == "-":
        return {}, (
            "dispatch verify-handoff: --bind-current requires the current handoff file "
            "via --handoff"
        )

    state = _state(args.repo)
    lane = (state.get("lanes") or {}).get(args.lane)
    if not isinstance(lane, Mapping):
        return {}, f"dispatch verify-handoff: lane {args.lane!r} is not in the current run"

    run_id = str(state.get("run_id") or "")
    lane_run = str(lane.get("run_id") or "")
    dispatch_id = str(lane.get("dispatch_id") or "")
    expected_handoff = str(lane.get("handoff") or "")
    worktree = str(lane.get("worktree") or "")
    delivery_scope = str(lane.get("delivery_scope") or "")
    if lane.get("status") in {"failed", "cancelled", "released"} or lane.get("phase") in {"terminal", "closed"}:
        return {}, "dispatch verify-handoff: terminal/finalized lanes cannot re-enter Gate C"
    if not run_id or lane_run != run_id or not dispatch_id:
        return {}, (
            "dispatch verify-handoff: current lane identity is incomplete or belongs "
            "to another run"
        )

    supplied_handoff = str(Path(os.path.expanduser(args.handoff)).resolve())
    current_handoff = (
        str(Path(os.path.expanduser(expected_handoff)).resolve()) if expected_handoff else ""
    )
    if not current_handoff or supplied_handoff != current_handoff:
        return {}, (
            "dispatch verify-handoff: --handoff does not match the current dispatch handoff "
            f"({current_handoff or 'missing'})"
        )
    if not worktree:
        return {}, "dispatch verify-handoff: current lane has no claimed worktree"
    if delivery_scope not in {"local", "repository", "submodule"}:
        return {}, (
            "dispatch verify-handoff: current lane has no trusted delivery scope; "
            "redispatch from the current bus before Gate C"
        )

    try:
        repo_root = _git_text(Path(args.repo or "."), "rev-parse", "--show-toplevel")
        revision = _git_text(Path(worktree), "rev-parse", "HEAD")
    except brain.StateError as exc:
        return {}, f"dispatch verify-handoff: cannot bind current Git revision ({exc})"

    return {
        "repo": str(Path(repo_root).resolve()),
        "run_id": run_id,
        "lane": args.lane,
        "dispatch_id": dispatch_id,
        "handoff": current_handoff,
        "revision": revision,
        "delivery_scope": delivery_scope,
    }, ""


def _persist_gate_c_report(
    repo: Optional[str],
    lane_id: str,
    *,
    report_id: str,
    binding: Mapping[str, Any],
    outcome: str = "delivered",
) -> None:
    path = brain.state_path(Path(repo) if repo else None)

    def persist(state: Dict[str, Any]) -> Dict[str, Any]:
        lane = (state.get("lanes") or {}).get(lane_id)
        if not isinstance(lane, dict):
            raise brain.StateError(f"lane {lane_id!r} disappeared before Gate C commit")
        if lane.get("status") in {"failed", "cancelled", "released"} or lane.get("phase") in {"terminal", "closed"}:
            raise brain.StateError("terminal/finalized lanes cannot regain Gate C")
        if (
            str(state.get("run_id") or "") != binding.get("run_id")
            or str(lane.get("run_id") or "") != binding.get("run_id")
            or str(lane.get("dispatch_id") or "") != binding.get("dispatch_id")
            or str(Path(str(lane.get("handoff") or "")).resolve()) != binding.get("handoff")
        ):
            raise brain.StateError("Gate C binding became stale before it could be recorded")
        _revoke_lane_closeout_state(state, lane_id)
        lane = state["lanes"][lane_id]
        gate_c = {
            "report_id": report_id,
            "binding": dict(binding),
            "accepted": True,
            "outcome": outcome,
            "verified_unix_ms": brain.now_unix_ms(),
        }
        key = _AUTHORIZATION_RUNTIME_KEY
        if not key:
            raise brain.StateError(
                "binding Gate C requires the active root OMP protected runtime"
            )
        gate_c["gate_c_proof"] = _gate_c_proof(gate_c, key)
        lane["gate_c"] = gate_c
        return state

    brain.mutate(path, persist)


def _capture_trusted_gate_c_evidence(
    args: argparse.Namespace,
    binding: Mapping[str, Any],
) -> tuple[int, str, str, str]:
    """Capture Gate C facts in the protected root runtime, never from worker claims."""
    state = _state(args.repo)
    lane = (state.get("lanes") or {}).get(args.lane)
    if not isinstance(lane, Mapping):
        raise brain.StateError(f"lane {args.lane!r} disappeared before trusted Gate C capture")
    worktree = Path(str(lane.get("worktree") or "")).resolve()
    repo_root = Path(str(binding.get("repo") or "")).resolve()
    if not worktree.exists():
        raise brain.StateError("trusted Gate C capture requires the current lane worktree")

    commands: List[List[str]] = []
    root_python = repo_root / ".venv" / "bin" / "python"
    if (repo_root / "tests").is_dir() and root_python.exists():
        commands.append([
            str(root_python),
            "-m",
            "pytest",
            "tests/",
            "-q",
            "-m",
            "not machine",
        ])
    if (repo_root / "tests" / "dispatch-brain.test.ts").exists():
        commands.append(["bun", "test"])
    if not commands:
        commands.append(["git", "diff", "--check"])

    outputs: List[str] = []
    exit_code = 0
    for command in commands:
        proc = subprocess.run(
            command,
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
        outputs.append(
            f"$ {' '.join(command)}\n{proc.stdout or ''}{proc.stderr or ''}".rstrip()
        )
        if proc.returncode != 0:
            exit_code = proc.returncode
            break

    root_revision = _git_text(repo_root, "rev-parse", "HEAD")
    worker_revision = str(binding.get("revision") or "")
    diff_parts: List[str] = []
    if worker_revision and worker_revision != root_revision:
        committed = subprocess.run(
            ["git", "-C", str(worktree), "diff", "--stat", root_revision, worker_revision],
            capture_output=True,
            text=True,
            check=False,
        )
        if committed.stdout.strip():
            diff_parts.append(committed.stdout.strip())
    for argv in (
        ["git", "-C", str(worktree), "diff", "--stat", "HEAD"],
        ["git", "-C", str(worktree), "diff", "--cached", "--stat", "HEAD"],
    ):
        proc = subprocess.run(argv, capture_output=True, text=True, check=False)
        if proc.stdout.strip():
            diff_parts.append(proc.stdout.strip())

    diff_summary = "\n".join(diff_parts).strip()
    if not diff_summary:
        diff_summary = "0 files changed, 0 insertions(+), 0 deletions(-)"
    test_output = "\n\n".join(part for part in outputs if part)
    handoff_path = Path(str(binding.get("handoff") or ""))
    try:
        handoff_bytes = handoff_path.read_bytes()
    except OSError as exc:
        raise brain.StateError(f"cannot read bound handoff for evidence digest ({exc})") from exc
    handoff_digest = hashlib.sha256(handoff_bytes).hexdigest()
    digest = hashlib.sha256(
        f"{exit_code}\n{test_output}\n{diff_summary}\n{handoff_digest}".encode("utf-8")
    ).hexdigest()
    return exit_code, test_output, diff_summary, digest


def cmd_verify_handoff(args: argparse.Namespace) -> int:
    """Gate C: review a worker's Done claim against its physical evidence.

    Facts are decided in code and semantic judgment is delegated to Jev, so a red
    suite is refused without spending a model call. Exits 2 when the claim is not
    corroborated; the rendered report carries the message to hand back to the
    worker.
    """
    raw_exit = args.exit_code
    if raw_exit is None:
        print(
            "dispatch verify-handoff: pass --exit-code <n> from the test command. "
            "A Done claim without a physical exit code cannot be verified.",
            file=sys.stderr,
        )
        return EXIT_GATE_REFUSED
    try:
        test_exit_code = int(raw_exit)
    except (TypeError, ValueError):
        print(
            f"dispatch verify-handoff: --exit-code must be an integer (got {raw_exit!r})",
            file=sys.stderr,
        )
        return EXIT_GATE_REFUSED

    # Inputs are resolved before any judging, so a typo in a path is reported as
    # a bad path rather than as a failed truthfulness review.
    handoff_text, err = _read_evidence_input(args.handoff_text, args.handoff, "handoff")
    if err:
        print(err, file=sys.stderr)
        return EXIT_GATE_REFUSED
    test_output, err = _read_evidence_input(args.test_log_text, args.test_log, "test log")
    if err:
        print(err, file=sys.stderr)
        return EXIT_GATE_REFUSED
    diff_summary, err = _read_evidence_input(args.diff_text, args.diff, "diff summary")
    if err:
        print(err, file=sys.stderr)
        return EXIT_GATE_REFUSED

    binding: Dict[str, Any] = {}
    if args.bind_current:
        if not _AUTHORIZATION_RUNTIME_KEY:
            print(
                "dispatch verify-handoff: --bind-current requires the active root OMP "
                "protected runtime; direct worker binding is refused",
                file=sys.stderr,
            )
            return EXIT_GATE_REFUSED
        binding, bind_err = _formal_gate_c_binding(args)
        if bind_err:
            print(bind_err, file=sys.stderr)
            return EXIT_GATE_REFUSED
        try:
            (
                test_exit_code,
                test_output,
                diff_summary,
                evidence_digest,
            ) = _capture_trusted_gate_c_evidence(args, binding)
        except (brain.StateError, OSError) as exc:
            print(
                f"dispatch verify-handoff: trusted Gate C evidence capture failed ({exc})",
                file=sys.stderr,
            )
            return EXIT_GATE_REFUSED
        binding["evidence_digest"] = evidence_digest

    report = handoff.verify_handoff(
        handoff_text=handoff_text,
        test_exit_code=test_exit_code,
        test_output=test_output,
        diff_summary=diff_summary,
        expected_files=tuple(args.expect_file or ()),
        # Deterministic heuristics are the default; --online opts into Jev.
        # See the calibration note in handoff_judge: the live layer over-blocks
        # honest work, so an unreviewed default that calls the model would make
        # this gate refuse correct lanes.
        use_jev=args.online,
        allow_no_change=args.outcome == "no_change",
    )

    report_id = ""
    if args.bind_current and report.accepted:
        report_id = f"gate-c-{uuid.uuid4().hex}"
        try:
            _persist_gate_c_report(
                args.repo,
                args.lane,
                report_id=report_id,
                binding=binding,
                outcome=args.outcome,
            )
        except brain.StateError as exc:
            print(f"dispatch verify-handoff: {exc}", file=sys.stderr)
            return EXIT_GATE_REFUSED
    elif args.bind_current:
        path = state_path(args)

        def revoke_rejected(state: Dict[str, Any]) -> Dict[str, Any]:
            lane = (state.get("lanes") or {}).get(args.lane)
            if not isinstance(lane, dict):
                raise brain.StateError(f"lane {args.lane!r} disappeared before Gate C rejection")
            if (
                str(state.get("run_id") or "") != binding.get("run_id")
                or str(lane.get("dispatch_id") or "") != binding.get("dispatch_id")
            ):
                raise brain.StateError("Gate C rejection binding became stale before commit")
            _revoke_lane_closeout_state(state, args.lane)
            return state

        try:
            brain.mutate(path, revoke_rejected)
        except brain.StateError as exc:
            print(f"dispatch verify-handoff: {exc}", file=sys.stderr)
            return EXIT_GATE_REFUSED

    if args.json:
        payload = report.as_dict()
        payload["lane"] = args.lane or ""
        if args.bind_current:
            payload["report_id"] = report_id
            payload["binding"] = binding
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"handoff truth gate: lane={args.lane or '-'}")
        print(report.render())

    if not report.accepted:
        print(
            f"dispatch verify-handoff: closeout is blocked for lane {args.lane or '-'}",
            file=sys.stderr,
        )
    return 0 if report.accepted else EXIT_GATE_REFUSED


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
        run_id=args.run_id or "",
        dispatch_id=args.dispatch_id or "",
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


def cmd_gate_a(args: argparse.Namespace) -> int:
    """Gate A: judge one orchestrator tool call at the PreToolUse boundary.

    Exits 2 on a refusal, the same code every other lifecycle gate uses, so a
    caller can treat "the gate said no" uniformly. The phase again defaults to
    the state file, for the same reason `cmd_guard` does: the gate polices the
    brain as it is, not as the caller believes it to be.
    """
    phase = args.phase
    if not phase:
        state = _state(args.repo)
        phase = str(state.get("orchestrator_phase") or brain.DEFAULT_BRAIN_PHASE)

    report = guard_mod.check_tool_call(
        args.tool,
        target=args.target,
        command=args.command,
        cwd=args.cwd,
        phase=phase,
        awaiting=args.lane or (),
        use_jev=not args.offline,
    )

    if args.json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(report.render(), file=sys.stdout if report.allowed else sys.stderr)
        if not report.allowed and report.corrective_steer:
            print(f"  {report.corrective_steer}", file=sys.stderr)
    return 0 if report.allowed else EXIT_GATE_REFUSED


def _mark_delivery(plan: bus.DispatchPlan, *, status: str, delivered: Optional[bool], error: str = "") -> None:
    """Persist the transport outcome under the shared lock and identity check."""
    try:
        path = brain.state_path(plan.repo)

        def mark(state: Dict[str, Any]) -> Dict[str, Any]:
            lane = state.get("lanes", {}).get(plan.lane)
            if not isinstance(lane, dict):
                raise brain.StateError(f"lane {plan.lane!r} is missing while marking delivery")
            if (
                str(lane.get("run_id") or "") != plan.run_id
                or str(lane.get("dispatch_id") or "") != plan.dispatch_id
            ):
                raise brain.StateError(
                    f"lane {plan.lane!r} delivery identity changed before outcome persistence"
                )
            lane["status"] = status
            lane["delivery_status"] = (
                "delivered" if delivered is True else "rejected" if delivered is False else "unknown"
            )
            lane["delivered"] = delivered
            if error:
                lane["delivery_error"] = error
            else:
                lane.pop("delivery_error", None)
            return state

        brain.mutate(path, mark)
    except (brain.StateError, OSError) as exc:  # pragma: no cover - best effort
        print(f"dispatch: could not persist delivery outcome ({exc})", file=sys.stderr)


def cmd_dispatch(args: argparse.Namespace) -> int:
    """Dispatch a lane in one atomic command.

    Replaces six manual steps, each of which could be skipped: contract lint,
    the claim gate, pane rename, timestamp minting, envelope assembly and the
    brain state flush. Planning happens before any mutation, so a refusal from
    any gate leaves the pane name, the state file and the worker untouched.

    Exits 1 for a malformed contract, 2 for a rule refusal and 3 for a delivery
    failure *after* commit, so an orchestrator can tell "fix your task file"
    from "this lane is unsafe" from "the lane is half-dispatched and needs
    unwinding".
    """
    repo = Path(args.repo) if args.repo else Path.cwd()
    task = Path(os.path.expanduser(args.task)).expanduser().resolve()
    callback_target = (args.callback_target or os.environ.get("HERDR_PANE_ID") or "").strip()

    # A retry after lost confirmation is idempotent: reuse the exact transport
    # identity and handoff rather than minting a second task with a new timestamp.
    retry = None
    try:
        bus.validate_lane_name(args.lane_name)
        lane_id = bus.lane_from_name(args.lane_name)
        current = brain.load(brain.state_path(repo)).get("lanes", {}).get(lane_id)
        if isinstance(current, dict) and current.get("delivery_status") in {"unknown", "rejected"}:
            retry = current
            expected = {
                "name": args.lane_name,
                "pane_id": args.target,
                "callback_target": callback_target,
                "task": str(task),
            }
            mismatch = [k for k, v in expected.items() if str(current.get(k) or "") != str(v)]
            if mismatch:
                print(
                    "dispatch: refusing retry with changed identity fields: " + ", ".join(mismatch),
                    file=sys.stderr,
                )
                return EXIT_GATE_REFUSED
    except bus.DispatchRefused:
        retry = None

    # The bus owns the pane rename so planning stays pure; it resolves the Herdr
    # client itself, so nothing here needs rebinding.
    try:
        plan = bus.DispatchPlan.plan(
            repo=repo,
            task=task,
            lane_name=args.lane_name,
            target=args.target,
            callback_target=callback_target,
            lane=args.lane or "",
            worktree=args.worktree or "",
            branch=args.branch or "",
            highlights=args.highlight or [],
            risks=args.risk or [],
            timestamp=str(retry.get("dispatch_timestamp") or "") if retry else None,
            run_id=str(retry.get("run_id") or "") if retry else "",
            dispatch_id=str(retry.get("dispatch_id") or "") if retry else "",
            signature=str(retry.get("signature") or args.signature or "") if retry else (args.signature or ""),
        )
    except bus.DispatchRefused as exc:
        print(f"dispatch: {exc}", file=sys.stderr)
        return exc.exit_code

    try:
        bus.ensure_handoff_dir()
    except bus.DispatchRefused as exc:
        print(f"dispatch: {exc}", file=sys.stderr)
        return exc.exit_code

    plan.commit()

    # Delivery last: request and completion are different protocols. The worker
    # receives a [DISPATCH] request that contains an executable notify callback;
    # [NOTIFY] is reserved for the return leg.
    report = promptproto.validate_task_request(plan.request)
    if not report.ok:
        # Unreachable in practice: planning asserts compliance. Left in place
        # because a silent skip here is exactly the omission this command exists
        # to prevent.
        print(f"dispatch: refusing to deliver: {report.render()}", file=sys.stderr)
        return EXIT_DELIVERY_FAILED

    try:
        herdr.run_herdr(["agent", "prompt", plan.target, plan.request])
    except herdr.HerdrError as exc:
        # Distinct from a gate refusal, and the distinction is the whole point:
        # the plan has already committed, so the lane is recorded and holds a
        # claim on its worktree.
        #
        # Re-running the same command after an unknown outcome is idempotent:
        # the lane reuses its stored run/dispatch identity, timestamp and
        # handoff. The record is therefore marked unknown rather than inventing
        # certainty about whether the worker received the request.
        detail = str(exc)
        pre_send_codes = ("agent_blocked", "agent_not_ready", "agent_not_found", "pane_not_found")
        if any(code in detail for code in pre_send_codes):
            _mark_delivery(
                plan,
                status=DELIVERY_REJECTED_STATUS,
                delivered=False,
                error="Herdr rejected the prompt before accepting input: " + detail,
            )
            qualifier = "rejected before input was accepted"
        else:
            _mark_delivery(
                plan,
                status=DELIVERY_UNKNOWN_STATUS,
                delivered=None,
                error="prompt submission lost confirmation: " + detail,
            )
            qualifier = "confirmation was lost after submission may have occurred"
        print(
            f"dispatch: delivery not confirmed after commit ({exc})\n"
            f"  lane {plan.lane} ({plan.lane_name}) status: {qualifier}.\n"
            f"  dispatch_id={plan.dispatch_id}; handoff={plan.handoff}.\n"
            "  Re-run the same dispatch command to reuse this exact identity; "
            "do not create a new lane or timestamp.",
            file=sys.stderr,
        )
        return EXIT_DELIVERY_FAILED

    _mark_delivery(plan, status="working", delivered=True)
    print(bus.receipt(plan))
    return 0


def _watchdog_skip_reason(
    lane: Mapping[str, Any], inactivity_seconds: int, now_ms: int, current_run_id: str
) -> str:
    if not lane:
        return "lane is not recorded in the current run"
    lane_run_id = str(lane.get("run_id") or "")
    if current_run_id and lane_run_id != current_run_id:
        return "lane does not belong to the current run"
    status = str(lane.get("status") or "")
    phase = str(lane.get("phase") or "")
    if status in {"done", "closed", "failed", "cancelled", "released"} or phase in {
        "done",
        "terminal",
        "closed",
    }:
        return "terminal lane"
    if status not in {"working", "running"}:
        return f"lane is not active (status={status or 'unknown'})"
    if watchdog.is_lease_active(lane, now_ms=now_ms):
        return "watchdog lease is still active"
    last_heartbeat = lane.get("last_heartbeat")
    if not isinstance(last_heartbeat, (int, float)):
        return "lane silence is unknown (no heartbeat timestamp)"
    if now_ms - int(last_heartbeat) < max(0, inactivity_seconds) * 1000:
        return "lane is not silent for the configured inactivity window"
    return ""


def cmd_watchdog(args: argparse.Namespace) -> int:
    """Gate D: Zero-Token Semantic Watchdog check (Issue #134).

    Evaluates whether a quiet child lane is running heavy computation (compilation/test)
    or is stalled/deadlocked. If legitimate, extends lease by 10m (zero false alarms).
    If stalled, nudges or alerts.
    """
    path = state_path(args)
    state = brain.load(path)
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

        lane_record = state.get("lanes", {}).get(lane_id, {})
        now_ms = int(time.time() * 1000)
        skip_reason = _watchdog_skip_reason(
            lane_record,
            args.inactivity_threshold,
            now_ms,
            str(state.get("run_id") or ""),
        )
        if skip_reason:
            results.append(
                {
                    "lane": lane_id,
                    "pane_id": pane_id or "",
                    "verdict": watchdog.WatchdogVerdict.INCONCLUSIVE.value,
                    "reason": skip_reason,
                    "skipped": True,
                }
            )
            continue

        consecutive = int(lane_record.get("consecutive_extensions") or 0)
        prev_seq = lane_record.get("last_seen_seq")

        buffer_text = ""
        process_name = ""
        current_seq: Optional[int] = getattr(args, "seq", None)

        if getattr(args, "buffer", ""):
            buffer_text = getattr(args, "buffer", "")
            process_name = getattr(args, "process", "")
        elif pane_id and herdr.in_herdr():
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
                agent_status = str(info.get("agent_status") or info.get("status") or "").lower()
                if agent_status not in {"working", "running"}:
                    results.append(
                        {
                            "lane": lane_id,
                            "pane_id": pane_id or "",
                            "verdict": watchdog.WatchdogVerdict.INCONCLUSIVE.value,
                            "reason": f"Herdr agent is not active (status={agent_status or 'unknown'})",
                            "skipped": True,
                        }
                    )
                    continue
                process_name = info.get("process_name") or info.get("command") or ""
                if current_seq is None and isinstance(info.get("state_change_seq"), int):
                    current_seq = info.get("state_change_seq")
            except herdr.HerdrError:
                results.append(
                    {
                        "lane": lane_id,
                        "pane_id": pane_id or "",
                        "verdict": watchdog.WatchdogVerdict.INCONCLUSIVE.value,
                        "reason": "Herdr lifecycle observation is unknown",
                        "skipped": True,
                    }
                )
                continue
        else:
            results.append(
                {
                    "lane": lane_id,
                    "pane_id": pane_id or "",
                    "verdict": watchdog.WatchdogVerdict.INCONCLUSIVE.value,
                    "reason": "supported Herdr lifecycle observation is unavailable",
                    "skipped": True,
                }
            )
            continue

        # Progress self-healing: if sequence advanced, reset consecutive counter before evaluation
        if current_seq is not None and prev_seq is not None and current_seq > prev_seq:
            consecutive = 0

        heartbeat_age = (
            now_ms - int(lane_record["last_heartbeat"])
            if isinstance(lane_record.get("last_heartbeat"), (int, float))
            else None
        )
        judgment = watchdog.evaluate_watchdog_state(
            buffer_tail=buffer_text,
            process_name=process_name,
            consecutive_extensions=consecutive,
            online=bool(getattr(args, "online", False)),
            facts={
                "lane": lane_id,
                "status": lane_record.get("status"),
                "phase": lane_record.get("phase"),
                "state_change_seq": current_seq,
                "last_heartbeat_age_ms": heartbeat_age,
            },
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
            updated_state = watchdog.apply_lease_extension(
                state_path(args),
                lane_id,
                judgment.verdict,
                extension_seconds=judgment.lease_extension_seconds,
                current_seq=current_seq,
            )
            updated_lane = updated_state.get("lanes", {}).get(lane_id, {})
            res["lease_extended_seconds"] = judgment.lease_extension_seconds
            res["consecutive_extensions"] = updated_lane.get("consecutive_extensions", consecutive + 1)
        elif judgment.verdict == watchdog.WatchdogVerdict.NUDGE:
            if current_seq is not None:
                watchdog.apply_lease_extension(
                    state_path(args),
                    lane_id,
                    judgment.verdict,
                    current_seq=current_seq,
                )
            # A diagnostic must never blindly press Enter: it could approve a
            # modal or mutate worker state. Surface the recommendation instead.
            res["operator_action"] = "review_and_nudge"
        elif judgment.verdict == watchdog.WatchdogVerdict.ABORT:
            res["operator_action"] = "review_and_cancel"
            res["operator_command"] = (
                f"dispatch-plugin record-outcome --lane {lane_id} --outcome cancelled "
                "--reason 'watchdog abort accepted by operator'"
            )

        results.append(res)

    if args.json:
        print(json.dumps({"results": results}, indent=2, ensure_ascii=False))
    else:
        for r in results:
            print(f"[{r['verdict']}] Lane {r['lane']} (pane {r['pane_id']}): {r['reason']}")
            if "lease_extended_seconds" in r:
                cons = r.get("consecutive_extensions", 1)
                print(f"  -> Watchdog lease extended by {r['lease_extended_seconds']}s (consecutive={cons})")

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

    status = sub.add_parser("status", help="show brain phase, lanes, or truthful capability state")
    status.add_argument("--json", action="store_true")
    status.add_argument(
        "--capabilities",
        action="store_true",
        help="report implemented versus policy-only dispatch capabilities",
    )
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

    terminal = sub.add_parser(
        "record-outcome",
        help="record a failed/cancelled lane terminal state without releasing its claim",
    )
    terminal.add_argument("--lane", required=True)
    terminal.add_argument("--outcome", choices=("failed", "cancelled"), required=True)
    terminal.add_argument("--reason", required=True)
    terminal.add_argument("--json", action="store_true")
    terminal.set_defaults(func=cmd_record_outcome)

    cleanup = sub.add_parser(
        "authorize-cleanup",
        help="prove Gate C + human authority + pre-removal closeout facts",
    )
    cleanup.add_argument("--lane", required=True)
    cleanup.add_argument("--evidence", default="", help="JSON object of closeout step facts")
    cleanup.add_argument("--json", action="store_true")
    cleanup.set_defaults(func=cmd_authorize_cleanup)

    cleanup_exec = sub.add_parser(
        "cleanup-worktree",
        help="consume the current human cleanup authority and remove the exact owned worktree",
    )
    cleanup_exec.add_argument("--lane", required=True)
    cleanup_exec.add_argument("--json", action="store_true")
    cleanup_exec.set_defaults(func=cmd_cleanup_worktree)

    finalize = sub.add_parser(
        "finalize-closeout",
        help="verify authorized worktree removal, release the lane claim, and allow pane close",
    )
    finalize.add_argument("--lane", required=True)
    finalize.add_argument("--evidence", default="", help="JSON object of closeout step facts")
    finalize.add_argument("--json", action="store_true")
    finalize.set_defaults(func=cmd_finalize_closeout)

    closeout = sub.add_parser(
        "closeout", help="evaluate the Closeout Lifecycle Gate before cleanup/pane close"
    )
    closeout.add_argument("--lane", default="")
    closeout.add_argument(
        "--evidence", default="", help="JSON object of closeout step facts"
    )
    closeout.add_argument(
        "--handoff-report",
        default="",
        help="Gate C report JSON; a non-ACCEPTED verdict blocks closeout",
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
    notify.add_argument("--run-id", default="", help="stable run identity for this report")
    notify.add_argument("--dispatch-id", default="", help="stable dispatch identity for this report")
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

    # Gate A: PreToolUse reflex gate (Issue #133). Takes a tool name plus its
    # target, which is why it is not a manifest action — a manifest command has
    # no way to supply the arguments being judged.
    gate_a = sub.add_parser(
        "gate",
        help="Gate A: intercept one orchestrator tool call before it runs",
    )
    gate_a.add_argument("--tool", required=True, help="the tool name being called")
    gate_a.add_argument("--target", default="", help="the file path the tool names")
    gate_a.add_argument("--command", default="", help="the shell command the tool runs")
    gate_a.add_argument("--cwd", default="", help="the working directory the call runs in")
    gate_a.add_argument(
        "--phase",
        default="",
        help="brain phase (default: whatever the state file records)",
    )
    gate_a.add_argument(
        "--lane",
        action="append",
        default=[],
        help="a lane the orchestrator is awaiting (repeatable)",
    )
    gate_a.add_argument(
        "--offline",
        action="store_true",
        help="skip the semantic layer and decide from the mechanical rules only",
    )
    gate_a.add_argument("--json", action="store_true")
    gate_a.set_defaults(func=cmd_gate_a)

    dispatch = sub.add_parser(
        "dispatch",
        help="dispatch a lane atomically: lint, claim, rename, timestamp, state flush, deliver",
        description=(
            "Minimal call:\n"
            "  dispatch --task TASK.md --lane-name 1-3-dispatch --target w3:p9\n\n"
            "Everything else is derived: the lane id from the lane name, the "
            "worktree and branch from the target pane, and the report bullets "
            "from the task contract. A derivation that fails exits 2 rather "
            "than dispatching a lane that claims nothing."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    dispatch.add_argument("--task", required=True, help="task contract file (7-section + #125)")
    dispatch.add_argument(
        "--lane-name",
        required=True,
        help=f"pane label and single source of the lane id, must match "
        f"{bus.LANE_NAME_PATTERN} (e.g. 1-3-dispatch)",
    )
    dispatch.add_argument("--target", required=True, help="worker pane, e.g. w3:p9")
    dispatch.add_argument(
        "--callback-target",
        default="",
        help="parent/orchestrator pane for the worker report; defaults to HERDR_PANE_ID",
    )
    dispatch.add_argument(
        "--signature", default="", help="[NOTIFY] signature, defaults to <lane-name>_<target>"
    )
    dispatch.add_argument(
        "--lane",
        default="",
        help="lane id; deprecated. Derived from --lane-name, and a value that "
        "disagrees is reported and discarded",
    )
    dispatch.add_argument(
        "--worktree", default="", help="worktree to claim; derived from the pane's cwd when omitted"
    )
    dispatch.add_argument(
        "--branch", default="", help="branch to claim; derived from the pane's git HEAD when omitted"
    )
    dispatch.add_argument(
        "--highlight",
        action="append",
        default=[],
        help="override a report bullet; repeatable. Omitted means parse the task contract",
    )
    dispatch.add_argument(
        "--risk", action="append", default=[], help="override a risk bullet; repeatable"
    )
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
    watchdog_p.add_argument(
        "--inactivity-threshold",
        type=int,
        default=watchdog.DEFAULT_BASE_INSPECTION_SECONDS,
        help="inactivity threshold in seconds before semantic inspection (default: 180s / 3m)",
    )
    watchdog_p.add_argument("--seq", type=int, default=None, help="override current state_change_seq")
    watchdog_p.add_argument(
        "--online",
        action="store_true",
        help="explicitly opt in to sanitized external semantic classification",
    )
    watchdog_p.add_argument("--json", action="store_true")
    watchdog_p.set_defaults(func=cmd_watchdog)

    verify = sub.add_parser(
        "verify-handoff",
        help="Gate C: review a Done claim against its test exit code and git diff",
    )
    verify.add_argument("--lane", default="", help="lane label for the report")
    handoff_source = verify.add_mutually_exclusive_group()
    handoff_source.add_argument("--handoff", default=None, help="handoff file ('-' for stdin)")
    handoff_source.add_argument("--handoff-text", default=None, help="the handoff itself")
    log_source = verify.add_mutually_exclusive_group()
    log_source.add_argument("--test-log", default=None, help="captured test output file")
    log_source.add_argument("--test-log-text", default=None, help="captured test output")
    diff_source = verify.add_mutually_exclusive_group()
    diff_source.add_argument("--diff", default=None, help="git diff summary file ('-' for stdin)")
    diff_source.add_argument("--diff-text", default=None, help="git diff summary")
    verify.add_argument(
        "--exit-code",
        default=None,
        help="exit code of the test command; a non-zero value blocks in code",
    )
    verify.add_argument(
        "--expect-file",
        action="append",
        default=[],
        help="file the handoff claims to change; repeatable",
    )
    verify.add_argument(
        "--bind-current",
        action="store_true",
        help=(
            "bind an accepted report to the current repo/run/lane/dispatch, "
            "handoff path and worker Git revision, then persist that report identity"
        ),
    )
    verify.add_argument(
        "--outcome",
        choices=("delivered", "no_change"),
        default="delivered",
        help=(
            "physical result shape: delivered requires a real diff; no_change "
            "requires green tests and zero diff"
        ),
    )
    verify.add_argument(
        "--online",
        action="store_true",
        help=(
            "consult TypeSafe Jev for the semantic verdict. OFF by default: "
            "the model over-blocks honest handoffs (measured p=0.47-0.58 "
            "against a 0.35 block line on jev-1.13.0), so the default path is "
            "the deterministic heuristic"
        ),
    )
    verify.add_argument("--json", action="store_true")
    verify.set_defaults(func=cmd_verify_handoff)

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