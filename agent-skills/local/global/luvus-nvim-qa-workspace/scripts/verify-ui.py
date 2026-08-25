#!/usr/bin/env python3
"""verify-ui.py: Playwriter ARIA snapshot verification with deterministic lifecycle.

Usage:
    verify-ui.py [url] [--browser headless|chromium]

Defaults to http://localhost:5173 (Vite dev server).
"""
import subprocess
import re
import json
import sys
from contextlib import contextmanager


@contextmanager
def playwriter_session(browser: str = "headless"):
    """With-bound Playwriter session; guarantees deletion on exit/error."""
    out = subprocess.check_output(
        ["playwriter", "session", "new", "--browser", browser], text=True
    )
    match = re.search(r"Session (\d+)", out)
    if not match:
        raise RuntimeError(f"Failed to create session: {out}")
    session_id = match.group(1)
    try:
        yield session_id
    finally:
        subprocess.run(
            ["playwriter", "session", "delete", session_id],
            check=False, stdout=subprocess.DEVNULL,
        )


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173"
    browser = sys.argv[sys.argv.index("--browser") + 1] if "--browser" in sys.argv else "headless"

    with playwriter_session(browser) as sid:
        cmd = f"""
await page.goto("{url}", {{ timeout: 10000 }});
console.log(JSON.stringify({{
  tree: await snapshot({{ page }}),
  logs: await getLatestLogs({{ page, sinceLastCall: true }}),
}}));
"""
        res = subprocess.check_output(["playwriter", "-s", sid, "-e", cmd], text=True)
        # Print only last non-empty line (JSON payload)
        lines = [l for l in res.strip().split("\n") if l.strip()]
        print(lines[-1])


if __name__ == "__main__":
    main()
