"""Orchestrator Brain Loop state store — TB-01.

Single source of truth for both layers of a dispatch run:

- **Phase 0** — the orchestrator brain loop: the orchestrator's own meta-tasks
  (``orchestrator_phase``), its resolved coordinate, and why it is parked.
- **Phase 1** — sub-worker execution: the per-lane business tasks.

Why the two layers share one file
--------------------------------
Keeping them apart is what produced the orchestration antipatterns this module
exists to remove. If only worker tasks are recorded, the orchestrator has no
representation of "what am I doing right now", so a todo reminder looks like a
demand for *new work* instead of a reminder about a task that is deliberately
parked. The result is false busywork (burning tokens probing state), child-work
takeover (the orchestrator edits worker-owned code), and degraded relay behaviour
(mechanically restating a single worker's report). See the engineering plan,
section 3.5.

Design constraints
------------------
- Schema 2 is an **expand** of the existing schema 1: every schema 1 field stays
  readable and writable so older tooling keeps working.
- An invalid ``orchestrator_phase`` is *rejected*, never silently normalised.
  A brain state that quietly falls back to a default is worse than no brain
  state, because it looks authoritative while being wrong.
- ``yield_and_guard`` may only be left via an explicit wake signal
  (``[NOTIFY]`` or a stall alarm). A todo reminder is not a wake signal.
- ``human_gate`` is never crossed by an automatic path.
- Writes are atomic and field-partitioned, so the short-lived Herdr plugin
  process and the long-lived omp extension can both write without clobbering
  each other's fields.

Deliberate non-goals (Occam)
---------------------------
No daemon, no scheduler, no IPC server. This module is a plain library and CLI.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import glob
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

SCHEMA_VERSION = 2
SUPPORTED_SCHEMAS = (1, 2)

STATE_DIR_NAME = "dispatch"
STATE_FILE_NAME = "ORCHESTRATOR_STATE.json"
LOCK_FILE_NAME = ".ORCHESTRATOR_STATE.lock"
DEFAULT_LOCK_STALE_SECONDS = 30

# Phase 0 — the orchestrator brain loop.
BRAIN_PHASES: tuple[str, ...] = (
    "contract",
    "topology",
    "yield_and_guard",
    "synthesis",
    "decision",
    "human_gate",
    "closed",
)

# The only legal forward path. ``closed`` is terminal.
BRAIN_TRANSITIONS: Dict[str, tuple[str, ...]] = {
    "contract": ("topology",),
    "topology": ("yield_and_guard",),
    # Leaving yield_and_guard is gated on an explicit wake signal, not on a
    # todo reminder. See `advance` below.
    "yield_and_guard": ("synthesis", "decision"),
    "synthesis": ("decision", "human_gate"),
    "decision": ("human_gate", "topology"),
    # human_gate may only advance on explicit human authorisation.
    "human_gate": ("closed", "synthesis"),
    "closed": (),
}

DEFAULT_BRAIN_PHASE = "contract"

# Only these reasons may move the brain out of yield_and_guard.
WAKE_SIGNALS: frozenset[str] = frozenset({"notify", "stall_alarm", "human"})

# Fields each writer owns. Enforced so the two processes never race on the
# same key: the plugin process owns lane presentation, the extension owns
# everything else.
WRITER_PLUGIN_OWNED = frozenset(
    {
        "tokens",
        "status",
        "pane_id",
        "agent_name",
        "watchdog_verdict",
        "watchdog_evaluated_at_unix_ms",
        "watchdog_lease_until_unix_ms",
    }
)
WRITER_EXTENSION_OWNED = frozenset({"phase", "handoff", "notified_at"})
WRITER_BRAIN_OWNED = frozenset(
    {
        "orchestrator_phase",
        "blocked_reason",
        "brain",
        "active_panes",
    }
)

TOP_LEVEL_KEYS: tuple[str, ...] = (
    "schema",
    "task_id",
    "run_id",
    "phase",
    "review_round",
    "max_review_rounds",
    "lanes",
    "known_facts",
    "awaiting_human_gate",
    "extra_data",
    "orchestrator",
    "orchestrator_phase",
    "blocked_reason",
    "brain",
    "active_panes",
    "updated_unix_ms",
)


class StateError(RuntimeError):
    """Base class for state-store failures."""


class BrainPhaseError(StateError):
    """An invalid or illegal orchestrator brain transition was requested."""


class LockTimeout(StateError):
    """The state lock could not be acquired before the deadline."""


def default_state(task_id: str = "") -> Dict[str, Any]:
    """Return a fresh schema 2 state document.

    Schema 1 keys are present so existing readers keep working; schema 2 adds
    the brain loop.
    """
    now = now_unix_ms()
    return {
        "schema": SCHEMA_VERSION,
        "task_id": task_id,
        "run_id": "",
        "phase": "init",
        "review_round": 0,
        "max_review_rounds": 1,
        "lanes": {},
        "known_facts": {},
        "awaiting_human_gate": False,
        "extra_data": {},
        "orchestrator": {},
        "orchestrator_phase": DEFAULT_BRAIN_PHASE,
        "blocked_reason": "",
        "brain": {
            "entered_phase_unix_ms": now,
            "awaiting_lanes": [],
            "notifications_seen": 0,
        },
        "active_panes": {"orchestrator": "", "lanes": {}},
        "updated_unix_ms": now,
    }


def now_unix_ms() -> int:
    return int(time.time() * 1000)


# --------------------------------------------------------------------------
# Path resolution
# --------------------------------------------------------------------------


def git_common_dir(cwd: Optional[Path] = None) -> Optional[Path]:
    """Return the repository's shared git common dir.

    Anchoring on the common dir (rather than the working tree) is what keeps a
    linked worktree and its main checkout from splitting into two brains.
    """
    target = Path(cwd) if cwd else Path.cwd()
    try:
        result = subprocess.run(
            [
                "git",
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            cwd=str(target),
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = result.stdout.strip()
    if not out:
        return None
    return Path(out)


def state_path(cwd: Optional[Path] = None) -> Path:
    """Resolve the single state file path for ``cwd``'s repository."""
    common = git_common_dir(cwd)
    if common is not None:
        return common / STATE_DIR_NAME / STATE_FILE_NAME
    return Path(cwd or Path.cwd()) / ".dispatch" / STATE_FILE_NAME


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------


def normalise(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Coerce a loaded document into schema 2 without losing schema 1 fields.

    An unknown future schema is refused rather than guessed at, and an invalid
    brain phase is refused rather than defaulted — see the module docstring.
    """
    if not isinstance(raw, Mapping):
        raise StateError("state document must be a JSON object")

    schema = raw.get("schema", 1)
    if not isinstance(schema, int) or schema not in SUPPORTED_SCHEMAS:
        raise StateError(f"unsupported state schema: {schema!r}")

    state = default_state()
    for key in TOP_LEVEL_KEYS:
        if key in raw:
            state[key] = raw[key]

    state["schema"] = SCHEMA_VERSION

    phase = state.get("orchestrator_phase")
    if phase not in BRAIN_PHASES:
        raise BrainPhaseError(
            f"invalid orchestrator_phase {phase!r}; "
            f"expected one of {', '.join(BRAIN_PHASES)}"
        )

    brain = state.get("brain")
    if not isinstance(brain, Mapping):
        brain = {}
    state["brain"] = {
        "entered_phase_unix_ms": _safe_int(brain.get("entered_phase_unix_ms"), 0),
        "awaiting_lanes": list(brain.get("awaiting_lanes") or []),
        "notifications_seen": _safe_int(brain.get("notifications_seen"), 0),
    }

    panes = state.get("active_panes")
    if not isinstance(panes, Mapping):
        panes = {}
    lane_panes = panes.get("lanes")
    state["active_panes"] = {
        "orchestrator": _safe_str(panes.get("orchestrator")),
        "lanes": dict(lane_panes) if isinstance(lane_panes, Mapping) else {},
    }

    if not isinstance(state.get("lanes"), dict):
        state["lanes"] = {}
    return state


def _safe_int(value: Any, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return fallback


def _safe_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


# --------------------------------------------------------------------------
# Atomic, partitioned writes
# --------------------------------------------------------------------------


@contextlib.contextmanager
def state_lock(
    path: Path,
    *,
    timeout: float = 5.0,
    stale_after: float = DEFAULT_LOCK_STALE_SECONDS,
):
    """Hold an advisory lock so the plugin and the extension can both write.

    The lock file is taken with ``O_CREAT | O_EXCL``. A lock left behind by a
    killed process is taken over once it ages past ``stale_after`` instead of
    wedging the run forever.
    """
    lock_path = path.parent / LOCK_FILE_NAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    fd: Optional[int] = None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, f"{os.getpid()} {now_unix_ms()}\n".encode())
            break
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
            if _lock_is_stale(lock_path, stale_after):
                with contextlib.suppress(OSError):
                    lock_path.unlink()
                continue
            if time.monotonic() >= deadline:
                raise LockTimeout(
                    f"could not acquire {lock_path} within {timeout}s"
                ) from exc
            time.sleep(0.02)
    try:
        yield
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(OSError):
            lock_path.unlink()


def _lock_is_stale(lock_path: Path, stale_after: float) -> bool:
    try:
        age = time.time() - lock_path.stat().st_mtime
    except OSError:
        return True
    return age > stale_after


def load(path: Path) -> Dict[str, Any]:
    """Read the state document, returning defaults when it does not exist."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default_state()
    except json.JSONDecodeError as exc:
        raise StateError(f"{path} is not valid JSON: {exc}") from exc
    return normalise(raw)


def _write_atomic(path: Path, state: Mapping[str, Any]) -> None:
    """Serialise and replace ``path`` in one step.

    Callers are responsible for holding the lock. Splitting this out keeps the
    public ``save``/``update`` entrypoints from taking the lock twice, which
    would self-deadlock: the lock is ``O_EXCL`` and not re-entrant.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state)
    payload["schema"] = SCHEMA_VERSION
    payload["updated_unix_ms"] = now_unix_ms()
    ordered = {key: payload.get(key) for key in TOP_LEVEL_KEYS}
    ordered["updated_unix_ms"] = payload["updated_unix_ms"]
    text = json.dumps(ordered, indent=2, sort_keys=False, ensure_ascii=False)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".ORCHESTRATOR_STATE.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def save(path: Path, state: Mapping[str, Any], *, timeout: float = 5.0) -> None:
    """Write the document atomically under the lock.

    ``tmp + rename`` means a reader either sees the whole previous document or
    the whole new one — never a half-written brain state.
    """
    with state_lock(path, timeout=timeout):
        _write_atomic(path, state)


def update(
    path: Path,
    mutations: Mapping[str, Any],
    *,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """Read-modify-write under a single lock hold.

    Mutations are shallow key assignments at the document root; nested lane
    updates go through :func:`update_lane`.
    """
    with state_lock(path, timeout=timeout):
        state = load(path)
        state.update(mutations)
        _write_atomic(path, state)
        return state


def update_lane(
    path: Path,
    lane_id: str,
    fields: Mapping[str, Any],
    *,
    writer: str = "extension",
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """Merge ``fields`` into one lane, enforcing the field-ownership split.

    Without this the short-lived plugin process and the long-lived extension
    would each read-modify-write the whole document and silently drop each
    other's fields.
    """
    allowed = WRITER_PLUGIN_OWNED if writer == "plugin" else WRITER_EXTENSION_OWNED
    rejected = sorted(set(fields) - allowed)
    if rejected:
        raise StateError(
            f"writer {writer!r} may not write lane field(s): {', '.join(rejected)}"
        )
    with state_lock(path, timeout=timeout):
        state = load(path)
        lanes = state.setdefault("lanes", {})
        lane = lanes.get(lane_id)
        if not isinstance(lane, dict):
            lane = {"lane": lane_id}
        lane.update(fields)
        lanes[lane_id] = lane
        _write_atomic(path, state)
        return state


# --------------------------------------------------------------------------
# Brain loop
# --------------------------------------------------------------------------


def is_parked(state: Mapping[str, Any]) -> bool:
    """True when the orchestrator is deliberately waiting on its workers.

    While parked, a todo reminder must *not* be read as "go do something".
    """
    return _safe_str(state.get("orchestrator_phase")) == "yield_and_guard"


def advance(
    state: Dict[str, Any],
    target: str,
    *,
    reason: str = "",
    wake_signal: Optional[str] = None,
) -> Dict[str, Any]:
    """Move the orchestrator brain to ``target``, or refuse.

    Two guards make this more than a field assignment:

    - leaving ``yield_and_guard`` requires a real wake signal, so a todo
      reminder can never rouse the orchestrator (the false-busywork loop);
    - ``human_gate`` can only be crossed by explicit human authorisation, so no
      automatic path can publish.
    """
    current = _safe_str(state.get("orchestrator_phase"))
    if target not in BRAIN_PHASES:
        raise BrainPhaseError(
            f"unknown orchestrator phase {target!r}; "
            f"expected one of {', '.join(BRAIN_PHASES)}"
        )
    if current == target:
        return state
    if target not in BRAIN_TRANSITIONS.get(current, ()):
        raise BrainPhaseError(
            f"illegal transition {current} -> {target}; "
            f"allowed: {', '.join(BRAIN_TRANSITIONS.get(current, ())) or 'none'}"
        )
    if current == "yield_and_guard" and (wake_signal or "") not in WAKE_SIGNALS:
        raise BrainPhaseError(
            "yield_and_guard may only be left via an explicit wake signal "
            f"({', '.join(sorted(WAKE_SIGNALS))}); a todo reminder is not one"
        )
    if current == "human_gate" and (wake_signal or "") != "human":
        raise BrainPhaseError(
            "human_gate may only be crossed by explicit human authorisation"
        )

    state["orchestrator_phase"] = target
    state["brain"] = {
        "entered_phase_unix_ms": now_unix_ms(),
        "awaiting_lanes": list((state.get("brain") or {}).get("awaiting_lanes") or []),
        "notifications_seen": _safe_int(
            (state.get("brain") or {}).get("notifications_seen"), 0
        ),
    }
    state["blocked_reason"] = reason if target == "yield_and_guard" else ""
    return state


def park(
    state: Dict[str, Any],
    awaiting_lanes: Sequence[str],
    *,
    orchestrator_pane: str = "",
) -> Dict[str, Any]:
    """Enter the guarded park: record what we are waiting on, and why.

    Recording the wait is what stops the orchestrator from improvising work
    while its workers run.
    """
    lanes = list(awaiting_lanes)
    panes = state.get("active_panes")
    if not isinstance(panes, Mapping):
        panes = {}
    lane_panes = panes.get("lanes")
    lane_map = dict(lane_panes) if isinstance(lane_panes, Mapping) else {}
    if orchestrator_pane:
        lane_map["__orchestrator__"] = {"pane": orchestrator_pane, "role": "orchestrator"}
    state["active_panes"] = {
        "orchestrator": orchestrator_pane or _safe_str(panes.get("orchestrator")),
        "lanes": lane_map,
    }
    advance(
        state,
        "yield_and_guard",
        reason=(
            f"Awaiting worker IPC [NOTIFY] on {orchestrator_pane}"
            if orchestrator_pane
            else "Awaiting worker IPC [NOTIFY]"
        ),
    )
    # Merge rather than replace: dispatching a second wave must not drop the
    # lanes already being waited on, or those workers become invisible and the
    # park outlives its own wait.
    waiting = list(state["brain"].get("awaiting_lanes") or [])
    for lane_id in lanes:
        if lane_id not in waiting:
            waiting.append(lane_id)
    state["brain"]["awaiting_lanes"] = waiting
    return state


def wake(state: Dict[str, Any], *, signal: str = "notify", lane: str = "") -> Dict[str, Any]:
    """Handle a wake signal: leave the park and advance to synthesis.

    Arrival of ``[NOTIFY]`` is the *only* routine driver out of the park. This
    is the step that stops the orchestrator being a relay: it re-enters the
    synthesis state to reconcile facts across lanes rather than restating one.
    """
    if signal not in WAKE_SIGNALS:
        raise BrainPhaseError(f"unknown wake signal {signal!r}")
    if lane:
        waiting = list(state["brain"].get("awaiting_lanes") or [])
        if lane in waiting:
            waiting.remove(lane)
        state["brain"]["awaiting_lanes"] = waiting
    if signal == "notify":
        state["brain"]["notifications_seen"] = _safe_int(
            state["brain"].get("notifications_seen"), 0
        ) + 1
    if is_parked(state):
        advance(state, "synthesis", reason="", wake_signal=signal)
    return state


# --------------------------------------------------------------------------
# Migration
# --------------------------------------------------------------------------


LEGACY_STATE_GLOBS: tuple[str, ...] = (
    "~/.omp/dispatch-omp/*/state.json",
    "~/.omp/dispatch-fleet/*/state.json",
)


def legacy_sources(cwd: Optional[Path] = None) -> List[Path]:
    """Discover legacy home-directory state files that predate the anchor.

    Uses ``glob.glob`` rather than ``Path.glob`` because these patterns contain
    a wildcard path *segment*; ``Path.glob`` only treats its own argument as a
    pattern and would look for a directory literally named ``*``.
    """
    found: List[Path] = []
    for pattern in LEGACY_STATE_GLOBS:
        expanded = os.path.expanduser(pattern)
        found.extend(Path(match) for match in glob.glob(expanded))
    return sorted({p for p in found if p.is_file()})


def migration_plan(cwd: Optional[Path] = None) -> Dict[str, Any]:
    """Describe what a migration would read, without touching anything."""
    target = state_path(cwd)
    sources: List[Dict[str, Any]] = []
    for path in legacy_sources(cwd):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            sources.append({"path": str(path), "readable": False, "error": str(exc)})
            continue
        lanes = payload.get("lanes")
        lane_count = len(lanes) if isinstance(lanes, (dict, list)) else 0
        sources.append(
            {
                "path": str(path),
                "readable": True,
                "schema": payload.get("schema"),
                "lane_count": lane_count,
            }
        )
    return {
        "target": str(target),
        "target_exists": target.exists(),
        "sources": sources,
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dispatch-brain",
        description="Orchestrator Brain Loop state store (TB-01)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="print the current state document")
    show.add_argument("--repo", default=None)
    show.add_argument("--brain", action="store_true", help="print Phase 0 only")

    park_parser = sub.add_parser("park", help="enter yield_and_guard")
    park_parser.add_argument("--repo", default=None)
    park_parser.add_argument("--pane", default="")
    park_parser.add_argument("--lane", action="append", default=[])

    wake_parser = sub.add_parser("wake", help="leave the park on a wake signal")
    wake_parser.add_argument("--repo", default=None)
    wake_parser.add_argument("--lane", default="")
    wake_parser.add_argument(
        "--signal", default="notify", choices=sorted(WAKE_SIGNALS)
    )

    advance_parser = sub.add_parser("advance", help="move the brain to a phase")
    advance_parser.add_argument("--repo", default=None)
    advance_parser.add_argument("--to", required=True, choices=list(BRAIN_PHASES))
    advance_parser.add_argument("--reason", default="")
    advance_parser.add_argument("--wake-signal", default=None)

    path_parser = sub.add_parser("path", help="print the resolved state path")
    path_parser.add_argument("--repo", default=None)

    migrate = sub.add_parser("migrate", help="migrate legacy state into the anchor")
    migrate.add_argument("--repo", default=None)
    migrate.add_argument("--dry-run", action="store_true")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    cwd = Path(args.repo) if getattr(args, "repo", None) else None
    target = state_path(cwd)

    try:
        if args.command == "path":
            print(target)
            return 0

        if args.command == "show":
            state = load(target)
            if args.brain:
                print(
                    json.dumps(
                        {
                            "orchestrator_phase": state["orchestrator_phase"],
                            "blocked_reason": state["blocked_reason"],
                            "brain": state["brain"],
                            "active_panes": state["active_panes"],
                            "parked": is_parked(state),
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            else:
                print(json.dumps(state, indent=2, ensure_ascii=False))
            return 0

        if args.command == "park":
            state = load(target)
            park(state, args.lane, orchestrator_pane=args.pane)
            save(target, state)
            print(state["orchestrator_phase"])
            return 0

        if args.command == "wake":
            state = load(target)
            wake(state, signal=args.signal, lane=args.lane)
            save(target, state)
            print(state["orchestrator_phase"])
            return 0

        if args.command == "advance":
            state = load(target)
            advance(
                state,
                args.to,
                reason=args.reason,
                wake_signal=args.wake_signal,
            )
            save(target, state)
            print(state["orchestrator_phase"])
            return 0

        if args.command == "migrate":
            plan = migration_plan(cwd)
            if args.dry_run:
                print(json.dumps(plan, indent=2, ensure_ascii=False))
                return 0
            if not plan["sources"]:
                print("no legacy state to migrate")
                return 0
            state = load(target)
            migrated = 0
            for source in plan["sources"]:
                if not source.get("readable"):
                    continue
                payload = json.loads(Path(source["path"]).read_text(encoding="utf-8"))
                lanes = payload.get("lanes")
                if isinstance(lanes, dict):
                    for lane_id, lane in lanes.items():
                        if not isinstance(lane, dict):
                            continue
                        entry = state["lanes"].setdefault(lane_id, {"lane": lane_id})
                        for key in ("pane", "pane_id", "status", "phase", "role"):
                            if key in lane and lane[key] is not None:
                                entry[key] = lane[key]
                    migrated += 1
            save(target, state)
            print(f"migrated {migrated} legacy run(s) into {target}")
            return 0

    except (StateError, LockTimeout) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())