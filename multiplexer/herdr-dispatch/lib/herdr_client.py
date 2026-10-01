"""Herdr client for dispatch lanes — TB-03.

Everything this module sends to Herdr goes through the documented CLI or the
documented socket API. Two rules shape it:

**Never report agent lifecycle state.** Herdr's own ``herdr:omp`` integration
owns that, and a second writer does not fail loudly — Herdr accepts-and-ignores
the older sequence, or a pane flips back to ``idle`` while a retry hold is
active. This module therefore reports *presentation* metadata only
(``pane.report_metadata``) and reads lifecycle state (``agent_status``,
``state_change_seq``) for display.

**Go through the injected binary.** Herdr's socket is a Unix socket on POSIX and
a named pipe on Windows. ``HERDR_BIN_PATH`` abstracts that, so the same code
works on both. The one exception is the Agents view projection, which has no
CLI wrapper at all; that goes through a small raw-socket client.

No repository paths are hardcoded. The repo is discovered from the environment
or the caller's cwd, so this module is reusable in any project.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

DEFAULT_TIMEOUT = 20

# Presentation tokens. Keys must be 1-32 chars of [A-Za-z0-9_-] per Herdr.
TOKEN_WAVE = "wave"
TOKEN_LANE = "lane"
TOKEN_ROLE = "role"
TOKEN_KIND = "kind"
TOKEN_BRAIN = "brain"
# Live stage from the worker's most recent [HEARTBEAT], compacted for the
# sidebar so a human can see the work is moving without asking.
TOKEN_DSTATE = "dstate"
TOKEN_MAX_LEN = 32
TOKEN_VALUE_MAX = 80

# Statuses Herdr renders differently in the sidebar; worth surfacing first.
ATTENTION_STATUSES = ("blocked", "done")


class HerdrError(RuntimeError):
    """A Herdr CLI or socket call failed."""


@dataclass(frozen=True)
class Lane:
    """One dispatch lane as the plugin sees it.

    Read from the shared state file; the plugin never invents lane identity.
    """

    lane_id: str
    pane_id: str
    wave: str = ""
    role: str = ""
    kind: str = ""
    brain_phase: str = ""

    @property
    def label(self) -> str:
        return self.lane_id


def herdr_binary() -> str:
    """The Herdr binary to invoke.

    Prefers the path Herdr injects, because it resolves to the *running*
    server's binary rather than whatever happens to be first on PATH.
    """
    return os.environ.get("HERDR_BIN_PATH") or "herdr"


def socket_path() -> Optional[str]:
    return os.environ.get("HERDR_SOCKET_PATH") or None


def in_herdr() -> bool:
    """True when running inside a Herdr-managed pane."""
    return os.environ.get("HERDR_ENV") == "1" and bool(socket_path())


def sanitize_token(key: str) -> str:
    """Coerce a token key into Herdr's allowed shape."""
    cleaned = "".join(ch if (ch.isalnum() or ch in "_-") else "-" for ch in key)
    cleaned = cleaned.strip("-")[:TOKEN_MAX_LEN]
    return cleaned


def truncate_token_value(value: Any) -> str:
    """Herdr normalises and caps token values; do it ourselves predictably."""
    text = "" if value is None else str(value)
    # Replace rather than delete: dropping control characters outright glues
    # the surrounding words together ("a\nb" -> "ab").
    text = "".join(ch if ch.isprintable() else " " for ch in text)
    text = " ".join(text.split())
    return text[:TOKEN_VALUE_MAX]


def compact_stage(stage: str) -> str:
    """Compact a worker stage into a sidebar-sized label.

    Mirrors the extension's ``displayStage`` so both sides agree on what a human
    reads: ``Stage 4 Deploying on hk216`` becomes ``s4@hk216``.
    """
    text = (stage or "").strip()
    if not text:
        return ""
    match = re.match(r"stage\s*(\d+)", text, re.IGNORECASE)
    prefix = f"s{match.group(1)}" if match else "s"
    target = re.search(
        r"([A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*@[A-Za-z0-9._-]+)"
        r"|\bof\s+([A-Za-z0-9._-]{2,})"
        r"|\bon\s+([A-Za-z0-9._-]{2,})"
        r"|\bto\s+([A-Za-z0-9._-]{2,})"
        r"|\bin\s+([A-Za-z0-9._-]{2,})",
        text,
        re.IGNORECASE,
    )
    if target:
        chosen = next((g for g in target.groups() if g), None)
        return truncate_token_value(f"{prefix}@{chosen}")
    words = re.sub(r"^stage\s*\d+\s*", "", text, flags=re.IGNORECASE).split()
    return truncate_token_value(f"{prefix}{words[0]}" if words else prefix)


def build_lane_tokens(lane: Mapping[str, Any], brain_phase: str = "") -> Dict[str, str]:
    """Build the presentation token map for one lane.

    Presentation only. Lifecycle state is deliberately absent: Herdr already
    renders status from the integration that owns it.
    """
    tokens: Dict[str, Any] = {
        TOKEN_LANE: lane.get("lane") or lane.get("lane_id") or "",
        TOKEN_WAVE: lane.get("wave", ""),
        TOKEN_ROLE: lane.get("role", ""),
        TOKEN_KIND: lane.get("kind", ""),
        TOKEN_BRAIN: brain_phase,
        # Heartbeat stage, when the lane has sent one.
        TOKEN_DSTATE: compact_stage(lane.get("current_stage") or ""),
    }
    out: Dict[str, str] = {}
    for key, value in tokens.items():
        if value in ("", None):
            continue
        safe_key = sanitize_token(key)
        safe_value = truncate_token_value(value)
        if safe_key and safe_value:
            out[safe_key] = safe_value
    return out


# --------------------------------------------------------------------------
# CLI transport
# --------------------------------------------------------------------------


def run_herdr(args: Sequence[str], *, timeout: int = DEFAULT_TIMEOUT) -> Any:
    """Invoke the Herdr CLI and decode its JSON response.

    Herdr exits 1 with a JSON error on stderr for server errors and 2 for CLI
    syntax errors, so both are surfaced rather than swallowed.
    """
    cmd = [herdr_binary(), *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise HerdrError(f"herdr binary not found: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise HerdrError(f"herdr {' '.join(args)} timed out after {timeout}s") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise HerdrError(f"herdr {' '.join(args)} failed ({proc.returncode}): {detail}")

    out = proc.stdout.strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        # Human-readable output (e.g. plugin list without --json).
        return {"text": out}


# --------------------------------------------------------------------------
# Read paths
# --------------------------------------------------------------------------


def agent_info(target: str) -> Dict[str, Any]:
    """Read one agent's public record."""
    result = run_herdr(["agent", "get", target])
    if isinstance(result, Mapping):
        agent = result.get("result", {}).get("agent", {})
        if isinstance(agent, Mapping):
            return dict(agent)
    return {}


def agent_list() -> List[Dict[str, Any]]:
    result = run_herdr(["agent", "list"])
    if isinstance(result, Mapping):
        agents = result.get("result", {}).get("agents", [])
        if isinstance(agents, list):
            return [dict(a) for a in agents if isinstance(a, Mapping)]
    return []


def attention_panes() -> List[Dict[str, Any]]:
    """Agents needing a human, soonest transition first.

    Used by the board so a blocked lane is impossible to miss.
    """
    agents = [
        a
        for a in agent_list()
        if a.get("agent_status") in ATTENTION_STATUSES
    ]
    agents.sort(key=lambda a: (-int(a.get("state_change_seq") or 0)))
    return agents


# --------------------------------------------------------------------------
# Write path — presentation only
# --------------------------------------------------------------------------


def report_lane_metadata(
    pane_id: str,
    lane: Mapping[str, Any],
    *,
    brain_phase: str = "",
    source: str = "plugin:herdr-dispatch",
    ttl_ms: Optional[int] = None,
) -> Dict[str, str]:
    """Publish a lane's presentation tokens for one pane.

    Uses ``pane.report_metadata`` (display-only) and never ``pane.report_agent``
    (lifecycle). That split is the single-writer invariant; the repository gate
    ``dispatch-single-writer-gate.py`` fails the build if it is crossed.

    Metadata is display-only: valid metadata may override the pane title,
    displayed agent name, visible state labels and named tokens, while working,
    blocked, idle, waits, notifications and rollups still come from the
    authoritative lifecycle state.
    """
    if not pane_id:
        raise HerdrError("pane_id is required to report lane metadata")

    tokens = build_lane_tokens(lane, brain_phase)
    args = ["pane", "report-metadata", pane_id, "--source", source]
    title = truncate_token_value(lane.get("lane") or lane.get("lane_id") or pane_id)
    if title:
        args += ["--title", title]
    if lane.get("role"):
        args += [
            "--display-agent",
            truncate_token_value(f"{lane.get('kind') or 'agent'}: {lane.get('role')}"),
        ]
    for key, value in tokens.items():
        args += ["--token", f"{key}={value}"]
    if ttl_ms is not None:
        if not 1 <= ttl_ms <= 86_400_000:
            raise HerdrError(f"ttl_ms out of range: {ttl_ms}")
        args += ["--ttl-ms", str(ttl_ms)]

    run_herdr(args)
    return tokens


def notify(title: str, body: str = "") -> bool:
    """Raise a toast. Best-effort: notification is a nicety, not a mechanism."""
    args = ["notification", "show", title]
    if body:
        args += ["--body", body]
    try:
        result = run_herdr(args)
    except HerdrError:
        return False
    if isinstance(result, Mapping):
        return bool(result.get("result", {}).get("shown"))
    return False


# --------------------------------------------------------------------------
# Raw socket (only for APIs with no CLI wrapper)
# --------------------------------------------------------------------------


class SocketClient:
    """Minimal newline-delimited JSON client for the Herdr socket.

    Deliberately narrow. Herdr's own guidance is that a plugin should call the
    CLI through ``HERDR_BIN_PATH`` because that stays portable across Unix
    sockets and Windows named pipes; this exists only for the Agents view
    projection, which ships no CLI wrapper at all. Every other call in this
    module goes through :func:`run_herdr`.
    """

    def __init__(self, path: Optional[str] = None, *, timeout: int = 10):
        target = path or socket_path()
        if not target:
            raise HerdrError("HERDR_SOCKET_PATH is not set")
        self._endpoint = (
            f"\\\\.\\pipe\\{target}" if os.name == "nt" and not target.startswith("\\\\")
            else target
        )
        self._timeout = timeout

    def request(self, method: str, params: Mapping[str, Any]) -> Dict[str, Any]:
        import socket as _socket

        line = json.dumps({"id": f"dispatch:{method}", "method": method, "params": params})
        try:
            with _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM) as sock:
                sock.settimeout(self._timeout)
                sock.connect(self._endpoint)
                sock.sendall((line + "\n").encode("utf-8"))
                chunks = []
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    if b"\n" in chunk:
                        break
        except OSError as exc:
            raise HerdrError(f"socket request {method} failed: {exc}") from exc

        payload = b"".join(chunks).split(b"\n", 1)[0]
        if not payload:
            raise HerdrError(f"socket request {method} returned no response")
        decoded = json.loads(payload.decode("utf-8"))
        if "error" in decoded:
            raise HerdrError(f"{method} rejected: {decoded['error']}")
        return decoded.get("result", {})


def set_agent_view(
    *,
    plugin_id: str,
    label: str = "dispatch-lanes",
    lane_token: str = TOKEN_LANE,
    enabled: bool = True,
) -> Dict[str, Any]:
    """Install or clear a declarative Agents view projection.

    This is opt-in and off by default. Setting a projection *replaces* the
    server's ``ui.agent_panel_sort`` policy while it is active, so silently
    enabling it would quietly change how every pane in the session is ordered.
    Callers must therefore opt in explicitly.

    Herdr rejects a plugin-owned projection when that plugin is missing or
    disabled, which is the behaviour we want: disabling the plugin retires the
    projection rather than leaving it stranded.
    """
    if not enabled:
        return SocketClient().request(
            "agent.view.clear", {"source": f"plugin:{plugin_id}"}
        )

    return SocketClient().request(
        "agent.view.set",
        {
            "source": f"plugin:{plugin_id}",
            "label": label,
            "filter": {
                "op": "any",
                "filters": [
                    {"op": "exists", "field": {"token": lane_token}},
                    {"op": "in", "field": "status", "values": list(ATTENTION_STATUSES)},
                ],
            },
            "sort": [
                {"field": {"token": TOKEN_WAVE}, "order": "asc"},
                {"field": {"token": lane_token}, "order": "asc"},
                {"field": "state_change_seq", "order": "desc"},
            ],
        },
    )


# --------------------------------------------------------------------------
# Plugin manifest helpers
# --------------------------------------------------------------------------


def plugin_root() -> Path:
    """Directory this plugin runs from.

    ``HERDR_PLUGIN_ROOT`` is authoritative. It is deliberately not a repository
    path: GitHub-installed plugin roots are managed checkouts, so nothing
    durable may be written there and no repo path may be assumed.
    """
    env_root = os.environ.get("HERDR_PLUGIN_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parent.parent


def plugin_config_dir() -> Path:
    env_dir = os.environ.get("HERDR_PLUGIN_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    return plugin_root() / ".config"


def plugin_state_dir() -> Path:
    """Where the plugin keeps its own runtime state.

    Herdr owns no plugin storage API in v1, so this stays plugin-owned. Nothing
    durable goes in ``plugin_root``: a managed checkout may be replaced.
    """
    env_dir = os.environ.get("HERDR_PLUGIN_STATE_DIR")
    if env_dir:
        path = Path(env_dir)
    else:
        # Herdr normally injects the state dir. Without it, stay outside the
        # plugin root anyway: a GitHub-installed root is a managed checkout
        # that can be replaced wholesale.
        state_home = os.environ.get("XDG_STATE_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "state"
        )
        path = Path(state_home) / "herdr-dispatch"
    path.mkdir(parents=True, exist_ok=True)
    return path


def view_enabled_by_default() -> bool:
    """The Agents view projection is opt-in.

    Returning False here is deliberate: enabling it by default would replace
    the user's ``ui.agent_panel_sort`` policy without asking.
    """
    raw = os.environ.get("HERDR_DISPATCH_AGENT_VIEW", "").strip().lower()
    return raw in ("1", "true", "yes", "on")