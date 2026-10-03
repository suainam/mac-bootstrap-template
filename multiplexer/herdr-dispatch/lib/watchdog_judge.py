"""Gate D: Zero-Token Semantic Watchdog (Issue #134).

Evaluates whether a quiet child lane (state_change_seq stalled >= 10 min)
is executing a legitimate long-running computation (e.g. cargo build, pytest,
npm install, downloads) or is truly stalled/deadlocked (e.g. interactive prompt
wait, infinite loop, deadlock).

Principles:
- Zero-token non-autoregressive classification: Calls TypeSafe Jev System One
  endpoint for typed Noul probabilities, burning 0 conversational tokens.
- Strict tail buffer truncation: Sends at most 15 lines of sanitized terminal
  buffer, strictly preventing full-context flooding.
- Autonomous lease extension: When P(legitimate) > 0.70, extends the watchdog
  lease by 10 minutes (600s), eliminating false-alarm interruptions to humans.
- Soft nudge / abort dispatch: When P(stalled) > 0.65, triggers prompt nudge or abort.
- Zero external dependencies: Pure Python standard library (urllib.request + json).
- Resilient offline fallback: Built-in heuristics for network errors or unconfigured keys.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

# ANSI escape sequence remover
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

# Default endpoints and models
DEFAULT_TYPESAFE_API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_JEV_MODEL = "jev-latest"
DEFAULT_BASE_INSPECTION_SECONDS = 180  # 3 minutes base inactivity inspection
LEASE_STEP_SECONDS: Sequence[int] = (180, 300, 600)  # 3m -> 5m -> 10m (cap)
DEFAULT_JITTER_SECONDS = 15
DEFAULT_LEASE_EXTENSION_SECONDS = 180  # Default 1st step base (3 minutes)
MAX_ONLINE_BUFFER_BYTES = 2048

# Thresholds per Issue #134 specification
THRESHOLD_LEGITIMATE_LONG_RUNNING = 0.70
THRESHOLD_STALLED_OR_DEADLOCKED = 0.65

# Heuristic patterns for offline / fallback evaluation
LEGITIMATE_PATTERNS = re.compile(
    r"(?i)\b("
    r"cargo\s+(?:build|check|test|run|clippy)|"
    r"pytest\b|"
    r"npm\s+(?:install|run|test|build|ci)|"
    r"yarn\s+(?:install|build|test)|"
    r"pnpm\s+(?:install|build|test)|"
    r"pip\s+install|"
    r"uv\s+(?:sync|run|pip)|"
    r"make\b|"
    r"cmake\b|"
    r"docker\s+(?:build|pull|run)|"
    r"compiling\s+|"
    r"building\s+\[|"
    r"running\s+tests|"
    r"downloading\s+|"
    r"downloaded\s+|"
    r"extracting\s+|"
    r"passed\b|"
    r"test\s+.*passed"
    r")"
)

INTERACTIVE_PROMPT_PATTERNS = re.compile(
    r"(?i)("
    r"❯\s*$|"
    r"\$\s*$|"
    r"\[[yY]/[nN]\]|"
    r"\([yY]/[nN]\)|"
    r"password:|"
    r"do you want to continue\?|"
    r"press\s+enter|"
    r"select\s+an\s+option|"
    r"which\s+(?:one|team|file)\b|"
    r"are you sure\?"
    r")"
)

SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])['\"]?"
    r"((?:[A-Za-z0-9]+[_-])*(?:"
    r"api[_-]?key|access[_-]?token|access[_-]?key(?:[_-]?id)?|"
    r"secret(?:[_-]?access)?[_-]?key|token|password|secret|authorization"
    r")(?:[_-][A-Za-z0-9]+)*)['\"]?"
    r"\s*[:=]\s*['\"]?(?:bearer\s+)?[^'\"\s,}\]]+['\"]?"
)
BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
KNOWN_TOKEN_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]{8,}|"
    r"xox[baprs]-[A-Za-z0-9_-]{8,}|glpat-[A-Za-z0-9_-]{8,}|AKIA[0-9A-Z]{16})\b"
)

DEADLOCK_PATTERNS = re.compile(
    r"(?i)\b("
    r"deadlock|"
    r"mutex\s+deadlock|"
    r"socket\s+hung|"
    r"connection\s+timed\s+out|"
    r"frozen|"
    r"sigkill|"
    r"sigsegv|"
    r"segmentation\s+fault"
    r")"
)


class WatchdogVerdict(str, Enum):
    EXTEND_LEASE = "EXTEND_LEASE"
    NUDGE = "NUDGE"
    ABORT = "ABORT"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class WatchdogJudgment:
    verdict: WatchdogVerdict
    p_legitimate: float
    p_stalled: float
    reason: str
    lease_extension_seconds: int = DEFAULT_LEASE_EXTENSION_SECONDS
    nudge_command: Optional[str] = None
    model: str = DEFAULT_JEV_MODEL


def extract_tail_buffer(text: str, max_lines: int = 15) -> str:
    """Extract at most `max_lines` tail lines from terminal buffer and clean ANSI codes."""
    if not text:
        return ""

    cleaned = ANSI_ESCAPE_RE.sub("", text)
    lines = [line.strip() for line in cleaned.splitlines()]
    non_empty = [line for line in lines if line]

    if not non_empty:
        return ""

    tail = non_empty[-max_lines:]
    return "\n".join(tail)


def sanitize_online_buffer(text: str, max_bytes: int = MAX_ONLINE_BUFFER_BYTES) -> str:
    """Redact common secret shapes and cap the external payload by UTF-8 bytes."""
    tail = extract_tail_buffer(text, max_lines=15)
    redacted = SECRET_ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", tail)
    redacted = BEARER_TOKEN_RE.sub("Bearer [REDACTED]", redacted)
    redacted = KNOWN_TOKEN_RE.sub("[REDACTED]", redacted)
    encoded = redacted.encode("utf-8")
    if len(encoded) <= max_bytes:
        return redacted
    return encoded[-max_bytes:].decode("utf-8", errors="ignore")


def compute_stepped_lease_seconds(
    consecutive_extensions: int,
    jitter_range: int = DEFAULT_JITTER_SECONDS,
    rng: Optional[random.Random] = None,
) -> int:
    """Compute lease extension duration using stepped backoff and random jitter.

    Steps:
    - 1st extension (consecutive=0): 180s (3m)
    - 2nd extension (consecutive=1): 300s (5m)
    - 3rd+ extension (consecutive>=2): 600s (10m ceiling)

    Jitter:
    - Adds uniform random integer in [-jitter_range, +jitter_range] (default ±15s).
    - Result clamped to at least 60s for safety.
    """
    count = max(0, int(consecutive_extensions))
    idx = min(count, len(LEASE_STEP_SECONDS) - 1)
    base = LEASE_STEP_SECONDS[idx]

    if jitter_range > 0:
        rand_func = rng.randint if rng is not None else random.randint
        delta = rand_func(-jitter_range, jitter_range)
    else:
        delta = 0

    return max(60, base + delta)


def _heuristic_judgment(
    buffer_tail: str,
    process_name: str,
    consecutive_extensions: int = 0,
    jitter_range: int = DEFAULT_JITTER_SECONDS,
    rng: Optional[random.Random] = None,
) -> WatchdogJudgment:
    """Offline heuristic judgment based on common compiler/toolchain signatures."""
    combined = f"{process_name}\n{buffer_tail}"

    has_legitimate = bool(LEGITIMATE_PATTERNS.search(combined))
    has_deadlock = bool(DEADLOCK_PATTERNS.search(combined))
    has_prompt = bool(INTERACTIVE_PROMPT_PATTERNS.search(combined))

    if has_deadlock:
        return WatchdogJudgment(
            verdict=WatchdogVerdict.ABORT,
            p_legitimate=0.01,
            p_stalled=0.92,
            reason="Heuristic: Fatal deadlock or crash trace detected in tail buffer",
            lease_extension_seconds=0,
            model="heuristic-fallback",
        )

    if has_legitimate and not has_prompt:
        ext_sec = compute_stepped_lease_seconds(
            consecutive_extensions, jitter_range=jitter_range, rng=rng
        )
        return WatchdogJudgment(
            verdict=WatchdogVerdict.EXTEND_LEASE,
            p_legitimate=0.88,
            p_stalled=0.05,
            reason="Heuristic: Legitimate compilation/test activity detected in tail buffer",
            lease_extension_seconds=ext_sec,
            model="heuristic-fallback",
        )

    if has_prompt:
        return WatchdogJudgment(
            verdict=WatchdogVerdict.NUDGE,
            p_legitimate=0.05,
            p_stalled=0.85,
            reason="Heuristic: Interactive prompt hang detected; soft nudge recommended",
            lease_extension_seconds=0,
            nudge_command="\n",
            model="heuristic-fallback",
        )

    return WatchdogJudgment(
        verdict=WatchdogVerdict.INCONCLUSIVE,
        p_legitimate=0.40,
        p_stalled=0.40,
        reason="Heuristic: Inconclusive buffer state without active compiler or prompt markers",
        lease_extension_seconds=0,
        model="heuristic-fallback",
    )


def evaluate_watchdog_state(
    buffer_tail: str,
    process_name: str = "",
    key: Optional[str] = None,
    timeout: float = 5.0,
    api_url: Optional[str] = None,
    model: Optional[str] = None,
    consecutive_extensions: int = 0,
    jitter_range: int = DEFAULT_JITTER_SECONDS,
    rng: Optional[random.Random] = None,
    online: bool = False,
    facts: Optional[Mapping[str, Any]] = None,
) -> WatchdogJudgment:
    """Evaluate lane state offline by default; external classification is explicit opt-in."""
    clean_tail = extract_tail_buffer(buffer_tail, max_lines=15)
    if not online:
        return _heuristic_judgment(
            clean_tail,
            process_name,
            consecutive_extensions=consecutive_extensions,
            jitter_range=jitter_range,
            rng=rng,
        )

    resolved_key = key or os.environ.get("TYPESAFE_API_KEY", "").strip()

    if not resolved_key and key is None:
        omp_env = Path.home() / ".omp" / "agent" / ".env"
        if omp_env.is_file():
            try:
                for line in omp_env.read_text(encoding="utf-8").splitlines():
                    if line.startswith("TYPESAFE_API_KEY="):
                        resolved_key = line.split("=", 1)[1].strip()
                        break
            except OSError:
                pass

    if not resolved_key:
        return _heuristic_judgment(
            clean_tail,
            process_name,
            consecutive_extensions=consecutive_extensions,
            jitter_range=jitter_range,
            rng=rng,
        )

    endpoint = api_url or os.environ.get("TYPESAFE_API_URL") or DEFAULT_TYPESAFE_API_URL
    target_model = model or os.environ.get("TYPESAFE_MODEL") or DEFAULT_JEV_MODEL

    allowed_fact_keys = (
        "lane",
        "status",
        "phase",
        "state_change_seq",
        "last_heartbeat_age_ms",
    )
    safe_facts = {
        key: facts[key]
        for key in allowed_fact_keys
        if isinstance(facts, Mapping) and key in facts
    }
    process_token = (process_name or "").strip().split(maxsplit=1)[0]
    safe_process_name = os.path.basename(process_token)[:64]
    state_payload = {
        "facts": safe_facts,
        "process_name": safe_process_name,
        "tail_buffer": sanitize_online_buffer(clean_tail),
    }

    questions_payload = {
        "is_legitimate_long_running": {
            "type": "noul",
            "instructions": (
                "Is the child agent executing a legitimate long-running computational task "
                "such as compilation, test suite execution, dependency installation, package building, or file download?"
            ),
            "criteria": {
                "true": "Active legitimate work in progress like cargo build, pytest, compilation, package installation, downloading, building assets",
                "false": "Not actively executing long computation; idle, prompt, waiting for user input, or hung/deadlocked",
            },
        },
        "is_stalled_or_deadlocked": {
            "type": "noul",
            "instructions": (
                "Is the child agent stalled, deadlocked, hanging on an interactive user input prompt, or frozen with no progress?"
            ),
            "criteria": {
                "true": "Deadlocked, hanging at an interactive prompt (e.g. '❯ ', '[y/N]', 'Password:', 'Select an option'), stuck in infinite loop, or frozen",
                "false": "Actively making progress or running background computation",
            },
        },
    }

    req_body = {
        "state": state_payload,
        "model": target_model,
        "questions": questions_payload,
    }

    data = json.dumps(req_body).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "Authorization": f"Bearer {resolved_key}",
            "Content-Type": "application/json",
            "User-Agent": "mac-bootstrap-watchdog/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_data = resp.read().decode("utf-8")
            parsed = json.loads(resp_data)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError):
        # Graceful fallback on network or API failure
        return _heuristic_judgment(
            clean_tail,
            process_name,
            consecutive_extensions=consecutive_extensions,
            jitter_range=jitter_range,
            rng=rng,
        )

    answers = parsed.get("answers", {})
    p_legit = float(answers.get("is_legitimate_long_running", {}).get("noul", 0.0))
    p_stalled = float(answers.get("is_stalled_or_deadlocked", {}).get("noul", 0.0))
    actual_model = parsed.get("model", target_model)

    if p_legit > THRESHOLD_LEGITIMATE_LONG_RUNNING:
        ext_sec = compute_stepped_lease_seconds(
            consecutive_extensions, jitter_range=jitter_range, rng=rng
        )
        return WatchdogJudgment(
            verdict=WatchdogVerdict.EXTEND_LEASE,
            p_legitimate=p_legit,
            p_stalled=p_stalled,
            reason=f"TypeSafe Jev: Legitimate long-running work confirmed (P={p_legit:.2f} > {THRESHOLD_LEGITIMATE_LONG_RUNNING})",
            lease_extension_seconds=ext_sec,
            model=actual_model,
        )

    if p_stalled > THRESHOLD_STALLED_OR_DEADLOCKED:
        has_prompt = bool(INTERACTIVE_PROMPT_PATTERNS.search(clean_tail))
        has_deadlock = bool(DEADLOCK_PATTERNS.search(clean_tail))

        if has_deadlock and not has_prompt:
            return WatchdogJudgment(
                verdict=WatchdogVerdict.ABORT,
                p_legitimate=p_legit,
                p_stalled=p_stalled,
                reason=f"TypeSafe Jev: Deadlock confirmed (P={p_stalled:.2f} > {THRESHOLD_STALLED_OR_DEADLOCKED})",
                lease_extension_seconds=0,
                model=actual_model,
            )

        return WatchdogJudgment(
            verdict=WatchdogVerdict.NUDGE,
            p_legitimate=p_legit,
            p_stalled=p_stalled,
            reason=f"TypeSafe Jev: Stall/prompt hang confirmed (P={p_stalled:.2f} > {THRESHOLD_STALLED_OR_DEADLOCKED}); nudge recommended",
            lease_extension_seconds=0,
            nudge_command="\n",
            model=actual_model,
        )

    return WatchdogJudgment(
        verdict=WatchdogVerdict.INCONCLUSIVE,
        p_legitimate=p_legit,
        p_stalled=p_stalled,
        reason=f"TypeSafe Jev: Inconclusive state (P_legit={p_legit:.2f}, P_stalled={p_stalled:.2f})",
        lease_extension_seconds=0,
        model=actual_model,
    )


def is_lease_active(lane: Mapping[str, Any], now_ms: Optional[int] = None) -> bool:
    """Check if a lane's watchdog lease is currently active."""
    current_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    lease_until = lane.get("watchdog_lease_until_unix_ms")
    return isinstance(lease_until, (int, float)) and lease_until > current_ms


def apply_lease_extension(
    state_path: Path,
    lane_id: str,
    verdict: WatchdogVerdict,
    extension_seconds: Optional[int] = None,
    current_seq: Optional[int] = None,
    now_ms: Optional[int] = None,
    jitter_range: int = DEFAULT_JITTER_SECONDS,
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    """Persist watchdog evaluation verdict and lease extension into state file.

    Handles stepped backoff tracking and forward progress reset:
    - If current_seq > last_seen_seq, forward progress occurred: reset consecutive_extensions = 0.
    - If verdict is EXTEND_LEASE, computes stepped lease seconds (if extension_seconds is None)
      and increments consecutive_extensions += 1.
    - Persists last_seen_seq if current_seq is provided.
    """
    import orchestrator_state as brain

    current_ms = now_ms if now_ms is not None else int(time.time() * 1000)

    try:
        current_state = brain.load(state_path)
        lane = current_state.get("lanes", {}).get(lane_id, {})
        if not isinstance(lane, Mapping):
            lane = {}
    except (brain.StateError, OSError):
        lane = {}

    prev_seq = lane.get("last_seen_seq")
    consecutive = int(lane.get("consecutive_extensions") or 0)

    # Forward progress self-healing: if state_change_seq advanced, reset consecutive counter
    if current_seq is not None and prev_seq is not None and current_seq > prev_seq:
        consecutive = 0

    fields: Dict[str, Any] = {
        "watchdog_verdict": verdict.value if isinstance(verdict, WatchdogVerdict) else str(verdict),
        "watchdog_evaluated_at_unix_ms": current_ms,
    }

    if current_seq is not None:
        fields["last_seen_seq"] = current_seq

    if verdict == WatchdogVerdict.EXTEND_LEASE:
        if extension_seconds is None:
            actual_seconds = compute_stepped_lease_seconds(
                consecutive, jitter_range=jitter_range, rng=rng
            )
        else:
            actual_seconds = extension_seconds

        fields["watchdog_lease_until_unix_ms"] = current_ms + (actual_seconds * 1000)
        fields["consecutive_extensions"] = consecutive + 1
    else:
        if current_seq is not None and prev_seq is not None and current_seq > prev_seq:
            fields["consecutive_extensions"] = 0

    return brain.update_lane(state_path, lane_id, fields, writer="plugin")

