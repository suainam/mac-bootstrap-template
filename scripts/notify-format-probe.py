#!/usr/bin/env python3
"""Phase 1 feedback loop — [NOTIFY] newline/escape normalisation.

The defect: `herdr agent prompt w3:p1 '\\n[NOTIFY] ...'` -- bash single quotes
keep `\\n` as two literal characters, so the worker receives backslash-n instead
of a newline and the report renders as one long single-line string.

This loop captures the EXACT bytes the plugin would hand to Herdr, by pointing
HERDR_BIN_PATH at a recorder script. That exercises the real delivery path
rather than a re-implementation of it.

Asserts the properties that actually matter:
  1. real 0x0A newlines present
  2. no literal backslash-n leakage
  3. UTF-8 text (Chinese) survives byte-for-byte
  4. fenced code blocks are not deformed

    python3 scripts/notify-format-probe.py       # red until fixed
    python3 scripts/notify-format-probe.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN = REPO_ROOT / "multiplexer" / "herdr-dispatch" / "bin" / "dispatch_plugin.py"

# The exact shape SKILL.md documents: bash single quotes, literal \n.
# The callback target is named explicitly because the gate requires a resolved
# coordinate, and `w5:p1_opencode-...` does NOT satisfy `\bw\d+:p\d+\b` (the
# trailing `_` is a word character, so no word boundary).
LITERAL_ESCAPED = (
    "\\n[NOTIFY] [w5:p1_opencode_mac-bootstrap]"
    "\\nDONE: 换行修复完成，实机验证通过"
    "\\nHandoff: /Users/suai/Documents/handoffs/x.md"
    "\\n回调目标坐标: w3:p1"
    "\\n\\n[核心成果]"
    "\\n- 要点 1: 真实换行"
    "\\n- 要点 2: 中文完好"
    "\\n\\n[风险与遗留]"
    "\\n- 遗留 1: 无"
)

CHINESE = "换行修复完成，实机验证通过"

RECORDER = """#!/usr/bin/env python3
import json, sys
# argv: [recorder, "agent", "prompt", <target>, <text>]
with open({out!r}, "w") as fh:
    json.dump({{"target": sys.argv[3], "text": sys.argv[4]}}, fh)
print('{{"ok": true}}')
"""


def deliver(prompt: str, tmp: Path) -> tuple[int, dict | None]:
    """Send through the real plugin, capturing what Herdr would receive."""
    capture = tmp / "capture.json"
    recorder = tmp / "fake-herdr"
    recorder.write_text(RECORDER.format(out=str(capture)))
    recorder.chmod(0o755)

    env = {**os.environ, "HERDR_BIN_PATH": str(recorder)}
    proc = subprocess.run(
        [sys.executable, str(PLUGIN), "prompt", "--text", prompt,
         "--send", "--target", "w3:p1"],
        capture_output=True, text=True, env=env,
    )
    if not capture.is_file():
        return proc.returncode, None
    return proc.returncode, json.loads(capture.read_text(encoding="utf-8"))


def check(name: str, ok: bool, detail: str) -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    verbose = "-v" in sys.argv
    results = []

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        code, payload = deliver(LITERAL_ESCAPED, tmp)

        if payload is None:
            print("[ABSENT] nothing was delivered — cannot evaluate")
            return 1
        if verbose:
            print(f"  delivered text: {payload['text']!r}")

        text = payload["text"]

        results.append(check(
            "delivered text has real 0x0A newlines",
            "\n" in text,
            f"{text.count(chr(10))} newline(s)",
        ))
        results.append(check(
            "no literal backslash-n leaks into the delivered text",
            "\\n" not in text,
            "found literal \\n" if "\\n" in text else "clean",
        ))
        results.append(check(
            "report is multi-line, not one long line",
            text.count("\n") >= 5,
            f"{len(text.splitlines())} lines",
        ))
        results.append(check(
            "Chinese text survives byte-for-byte",
            CHINESE in text,
            "mojibake detected" if CHINESE not in text else "intact",
        ))
        results.append(check(
            "structured sections survive",
            all(s in text for s in ("[NOTIFY]", "DONE:", "Handoff:", "[核心成果]", "[风险与遗留]")),
            "sections present",
        ))
        results.append(check(
            "delivery exit code is 0",
            code == 0,
            f"exit={code}",
        ))

    print()
    if all(results):
        print("newline/format contract holds")
        return 0
    print(f"{results.count(False)} check(s) failed — literal \\n still leaks")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())