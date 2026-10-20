#!/usr/bin/env python3
"""verify-ui.py: agent-browser snapshot + console/error verification.

Usage:
    verify-ui.py [url] [--profile Default] [--session herdr-qa]

Defaults to http://localhost:5173 (Vite dev server) in an isolated agent-browser
session named "herdr-qa". The session is closed on exit or error.

Inside OMP, `browser.open({ name: "qa", url })` + `tab.observe()` is the
in-process alternative. For cross-origin iframe JavaScript, use OMP
`tab.run` with `page.frames()` — agent-browser `eval` stays in the main frame.
"""
from __future__ import annotations

import json
import subprocess
import sys
from contextlib import contextmanager

DEFAULT_URL = "http://localhost:5173"
DEFAULT_SESSION = "herdr-qa"
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _run(args: list[str], *, check: bool = True) -> str:
    proc = subprocess.run(args, text=True, capture_output=True, check=False)
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


@contextmanager
def agent_browser_session(profile: str | None, session_name: str):
    """Yield the base command for a named session; always close it afterwards."""
    base_cmd = ["agent-browser", "--session", session_name]
    if profile:
        base_cmd.extend(["--profile", profile, "--executable-path", CHROME_PATH])
    try:
        yield base_cmd
    finally:
        _ = subprocess.run(
            ["agent-browser", "--session", session_name, "close"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main() -> int:
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    url = positional[0] if positional else DEFAULT_URL
    profile = sys.argv[sys.argv.index("--profile") + 1] if "--profile" in sys.argv else None
    session_name = (
        sys.argv[sys.argv.index("--session") + 1] if "--session" in sys.argv else DEFAULT_SESSION
    )

    with agent_browser_session(profile, session_name) as base_cmd:
        _ = _run([*base_cmd, "open", url])
        snapshot = _run([*base_cmd, "snapshot", "-i"]).strip()
        console = _run([*base_cmd, "console"], check=False).strip()
        errors = _run([*base_cmd, "errors"], check=False).strip()

    print(json.dumps({"url": url, "snapshot": snapshot, "console": console, "errors": errors}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
