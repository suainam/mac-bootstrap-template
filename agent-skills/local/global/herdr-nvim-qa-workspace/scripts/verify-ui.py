#!/usr/bin/env python3
"""verify-ui.py: jev-browser-use ARIA snapshot verification with deterministic lifecycle.

Usage:
    verify-ui.py [url] [--connect http://127.0.0.1:9222]

Defaults to http://localhost:5173 (Vite dev server) in headless mode.
Inside OMP, `browser.open({ name: "qa", url })` + `tab.observe()` can also be used as an in-process fallback.
"""
from __future__ import annotations

import subprocess
import sys
from contextlib import contextmanager


@contextmanager
def jev_browser_session(connect_url: str | None = None):
    """With-bound jev-browser-use session; guarantees daemon cleanup when headless."""
    base_cmd = ["jev-browser-use"]
    if connect_url:
        base_cmd.extend(["--connect", connect_url])
    else:
        base_cmd.append("--headless")
    try:
        yield base_cmd
    finally:
        if not connect_url:
            subprocess.run(
                ["jev-browser-use", "stop"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


def main():
    url = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "http://localhost:5173"
    connect_url = (
        sys.argv[sys.argv.index("--connect") + 1]
        if "--connect" in sys.argv
        else None
    )

    with jev_browser_session(connect_url) as base_cmd:
        cmd = f"""
const p = await browser.getPage("herdr-qa");
const logs = [];
p.on("console", m => {{
  if (m.type() === "error" || m.type() === "warning") logs.push(m.text());
}});
p.on("pageerror", e => logs.push(String(e)));
await p.goto("{url}", {{ timeout: 10000 }});
const tree = await p.snapshot({{ interactive: true }});
console.log(JSON.stringify({{ tree, logs }}));
"""
        res = subprocess.check_output([*base_cmd, "-e", cmd], text=True)
        lines = [line for line in res.strip().split("\n") if line.strip()]
        print(lines[-1])


if __name__ == "__main__":
    main()
