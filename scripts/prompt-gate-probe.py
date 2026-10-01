#!/usr/bin/env python3
"""Phase 1 feedback loop — prompt protocol gate.

Drives the exact symptom from the incident: an orchestrator sends a
non-compliant prompt through `herdr agent prompt` and nothing blocks it.

The loop asserts the *user's* symptom (a bare prompt must be refused), not
merely that a command runs. Run it red before the fix, green after.

    python3 scripts/prompt-gate-probe.py            # all cases
    python3 scripts/prompt-gate-probe.py -v         # show the messages
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN = REPO_ROOT / "multiplexer" / "herdr-dispatch" / "bin" / "dispatch_plugin.py"

# (name, prompt, expect_exit) — expect 0 = compliant/pass, 2 = refused.
#
# `bare_prompt` is the literal shape the orchestrator used: unstructured natural
# language, no evaluated coordinate, no [NOTIFY] callback contract.
# `placeholder_prompt` is the documented misroute from orchestrator lesson 3:
# a raw `<orch-pane>` placeholder that never got evaluated to a real pane id.
CASES: tuple[tuple[str, str, int], ...] = (
    (
        "bare_prompt",
        "看一下这个仓库的情况，然后把问题修掉。",
        2,
    ),
    (
        "placeholder_prompt",
        "Read .dispatch/TASK.md and report back.\n"
        "herdr agent prompt <orch-pane> '\\n[NOTIFY]\\nDONE: work'",
        2,
    ),
    (
        "notify_without_coordinate",
        "Read .dispatch/TASK.md.\n"
        "When complete run:\n"
        "herdr agent prompt ${ORCH_PANE} '\\n[NOTIFY]\\nDONE: fixed it'",
        2,
    ),
    (
        "compliant_prompt",
        "Read .dispatch/TASK.md and implement the fix.\n"
        "When complete, write the handoff and run:\n"
        "herdr agent prompt w3:p1 "
        "'\\n[NOTIFY] [w5:p1_opencode_mac-bootstrap]\\n"
        "DONE: 1-Lane-1-Worktree isolation landed\\n"
        "Handoff: ~/Documents/handoffs/x-20261001_000000.md'",
        0,
    ),
)


def run_case(name: str, prompt: str) -> tuple[int | None, str]:
    """Return (exit_code, output), or (None, reason) when the gate is absent.

    A missing `prompt` subcommand makes argparse exit 2 for *every* input,
    including compliant ones. Counting that as a correct refusal would make the
    loop report green for the wrong reason, so it is reported as a hard error
    instead: an absent gate is not a passing gate.
    """
    proc = subprocess.run(
        [sys.executable, str(PLUGIN), "prompt", "--stdin"],
        input=prompt,
        capture_output=True,
        text=True,
    )
    output = (proc.stderr or proc.stdout or "").strip()
    if "invalid choice" in output or output.startswith("usage:"):
        return None, output
    return proc.returncode, output


def main() -> int:
    verbose = "-v" in sys.argv
    failures = 0
    absent = False
    for name, prompt, expected in CASES:
        code, output = run_case(name, prompt)
        if code is None:
            absent = True
            print(f"[ABSENT] {name}: no prompt gate — {output.splitlines()[-1][:100]}")
            continue
        ok = code == expected
        if not ok:
            failures += 1
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}: exit={code} expected={expected}")
        if verbose or not ok:
            for line in output.splitlines()[:6]:
                print(f"         {line}")

    print()
    if absent:
        print("gate ABSENT: nothing enforces the prompt contract")
        return 1
    if failures:
        print(f"{failures} case(s) wrong — the gate does not enforce the contract yet")
    else:
        print("all cases behave as specified")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())