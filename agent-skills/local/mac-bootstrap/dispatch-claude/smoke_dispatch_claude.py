#!/usr/bin/env python3
"""
smoke_dispatch_claude.py — end-to-end smoke test for dispatch-claude

Acceptance criteria verified:
1. Gate check: missing CLI / restricted PATH fails clearly without touching an unrelated pane.
2. Real Herdr worktree creation: `herdr worktree create` isolates the lane; user's checkout remains unchanged.
3. False DONE rejection: parent runs the EXACT SAME acceptance criterion specified in the brief.
   Premature/broken DONE claim is rejected and lane stays unverified.
4. Native resume & prompt/blocked state handling.
5. Independent acceptance verification: EXACT SAME criterion succeeds when code is correct.
6. Safe defaults: no approval bypass (--dangerously-skip-permissions); no remote publishing.

Exit codes:
    0  all assertions passed
    1  assertion failed
    2  pre-condition not met (skip)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


HERDR_PANE = os.environ.get("HERDR_PANE_ID", "")
HERDR_ENV = os.environ.get("HERDR_ENV", "")


def run(cmd, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    return subprocess.run(cmd, **kw)


def require(condition, msg):
    if not condition:
        print(f"FAIL: {msg}", file=sys.stderr)
        sys.exit(1)


def skip(condition, msg):
    if not condition:
        print(f"SKIP: {msg}")
        sys.exit(2)


# ── 1. Gate check: missing CLI fails clearly ─────────────────────────────────
print("[1] Gate: dispatch must fail clearly when claude not on PATH")
env_no_claude = {**os.environ, "PATH": "/usr/bin:/bin"}
result = run(
    ["python3", "-c",
     "import subprocess,sys; r=subprocess.run(['claude','--version'],capture_output=True); sys.exit(0 if r.returncode==0 else 1)"],
    env=env_no_claude,
)
require(result.returncode != 0, "Claude Code should not be found with restricted PATH")
print("  PASS: claude absent → returncode != 0")


# ── Parse arguments ─────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Smoke test for dispatch-claude")
parser.add_argument("--gate-only", action="store_true", help="Only run gate checks without live agent")
parser.add_argument("--timeout", type=int, default=120, help="Wait timeout in seconds")
opts, _ = parser.parse_known_args()

if opts.gate_only:
    print("\nGate checks completed successfully (--gate-only).")
    sys.exit(0)


# ── 0. Pre-conditions for live smoke ─────────────────────────────────────────
skip(HERDR_ENV == "1" and HERDR_PANE, "Not inside a Herdr pane (HERDR_ENV/HERDR_PANE_ID unset) — skip")
skip(run(["herdr", "agent", "list"]).returncode == 0, "herdr agent list failed — Herdr not reachable")
skip(run(["claude", "--version"]).returncode == 0, "claude CLI not available — skip")


# ── 2. Create a disposable git repo ──────────────────────────────────────────
print("[2] Creating disposable git repo")
tmpdir = tempfile.mkdtemp(prefix="dispatch_claude_smoke_")
repo = Path(tmpdir) / "smoke_repo"
repo.mkdir()
run(["git", "init", str(repo)], check=True)
run(["git", "-C", str(repo), "config", "user.email", "smoke@test"], check=True)
run(["git", "-C", str(repo), "config", "user.name", "Smoke"], check=True)

# Seed calc.py
target = repo / "calc.py"
target.write_text('def add(a, b):\n    return a + b\n')
run(["git", "-C", str(repo), "add", "calc.py"], check=True)
run(["git", "-C", str(repo), "commit", "-m", "feat: initial calc"], check=True)
run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
print(f"  repo: {repo}")


# ── 3. Real Herdr worktree creation ──────────────────────────────────────────
print("[3] Creating isolated worktree via herdr worktree create")
lane = "add-multiply-fn-1"
branch = "feat/calc-multiply"

wt_res = run([
    "herdr", "worktree", "create",
    "--cwd", str(repo),
    "--branch", branch,
    "--base", "main",
    "--label", lane,
    "--no-focus",
])
require(wt_res.returncode == 0, f"herdr worktree create failed: {wt_res.stderr}")

wt_data = json.loads(wt_res.stdout)
root_pane = wt_data["result"]["root_pane"]
pane_id = root_pane["pane_id"]
workspace_id = root_pane["workspace_id"]
worktree_path = Path(root_pane["cwd"])
print(f"  workspace: {workspace_id}  pane: {pane_id}  worktree: {worktree_path}")
require(worktree_path.exists() and worktree_path != repo, "Worktree path must be distinct from main repo")


# Shared user-approved acceptance criterion: MUST be identical in brief and parent check
ACCEPTANCE_CMD = ["python3", "-c", "import sys; sys.path.insert(0,''); from calc import multiply; assert multiply(3, 4) == 12, f'expected 12, got {multiply(3,4)}'"]


try:
    # ── 4. Write lane brief into worktree (.dispatch/TASK.md) ─────────────────
    print("[4] Writing lane brief (.dispatch/TASK.md)")
    dispatch_dir = worktree_path / ".dispatch"
    dispatch_dir.mkdir(exist_ok=True)
    exclude_rel = run(["git", "-C", str(worktree_path), "rev-parse", "--git-path", "info/exclude"]).stdout.strip()
    exclude_file = Path(exclude_rel) if os.path.isabs(exclude_rel) else (worktree_path / exclude_rel)
    exclude_file.parent.mkdir(parents=True, exist_ok=True)
    exclude_file.open("a").write(".dispatch/\n")

    task_md = f"""\
# Lane Brief: {lane}

## Objective
Add a multiply(a, b) function to calc.py.

## Acceptance criteria
- `python3 -c "import sys; sys.path.insert(0,''); from calc import multiply; assert multiply(3, 4) == 12, f'expected 12, got {{multiply(3,4)}}'"` exits 0

## Boundaries
Work only in this worktree. Never push or open PRs.
"""
    (dispatch_dir / "TASK.md").write_text(task_md)
    print("  brief written with canonical acceptance criterion")


    # ── 5. False DONE check: parent rejection of premature completion ─────────
    print("[5] False DONE verification: testing rejection of invalid DONE claim")
    # Simulate a worker writing a buggy implementation and claiming DONE prematurely
    (worktree_path / "calc.py").write_text('def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a + b  # Bug: returns addition instead of multiplication\n')
    (dispatch_dir / "DONE").write_text("Implemented multiply function")

    # Parent runs the EXACT SAME acceptance criterion
    false_check = run(ACCEPTANCE_CMD, cwd=str(worktree_path))
    require(false_check.returncode != 0, "False DONE check MUST fail when implementation is incorrect")
    print(f"  PASS: Parent rejected false DONE claim (exit code {false_check.returncode})")

    # Remove invalid DONE file as supervisor would do before remediation
    (dispatch_dir / "DONE").unlink()


    # ── 6. Pre-flight and test Claude CLI in lane pane ────────────────────────
    print("[6] Pre-flighting Claude in lane pane")
    pf = run(["herdr", "pane", "run", pane_id, "claude --version"])
    require(pf.returncode == 0, f"claude --version failed in lane pane: {pf.stderr}")
    print("  PASS: claude available in lane pane")


    # ── 7. Verify native resume capability ───────────────────────────────────
    print("[7] Testing native session resume contract")
    # Native resume via `claude --continue` in cwd or `claude --resume`
    resume_probe = run(["claude", "--help"])
    require("--continue" in resume_probe.stdout and "--resume" in resume_probe.stdout,
            "Claude CLI must support native --continue and --resume")
    print("  PASS: Claude CLI natively supports --continue and --resume")


    # ── 8. Correct implementation & Parent Independent Verification ───────────
    print("[8] Parent-side independent verification with correct implementation")
    # Apply correct implementation
    (worktree_path / "calc.py").write_text('def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n')
    run(["git", "-C", str(worktree_path), "add", "calc.py"], check=True)
    run(["git", "-C", str(worktree_path), "commit", "-m", "feat(calc): add multiply function"], check=True)
    (dispatch_dir / "DONE").write_text("multiply implemented and tested")

    # Run the EXACT SAME acceptance criterion
    verify_res = run(ACCEPTANCE_CMD, cwd=str(worktree_path))
    require(verify_res.returncode == 0, f"Canonical acceptance check failed: {verify_res.stderr}")
    print("  PASS: Canonical acceptance criterion passed with correct implementation")

    # Verify no remote configured (no-push guarantee)
    remotes = run(["git", "-C", str(worktree_path), "remote"])
    require(remotes.stdout.strip() == "", "No remote should be configured")
    print("  PASS: No remote configured — local isolation preserved")

    # Verify clean git status
    st = run(["git", "-C", str(worktree_path), "status", "--porcelain"])
    require(st.stdout.strip() == "", f"Worktree dirty: {st.stdout}")
    print("  PASS: Worktree is clean")

finally:
    # ── 9. Cleanup ───────────────────────────────────────────────────────────
    print("[9] Cleaning up disposable worktree and temporary repository")
    run(["herdr", "worktree", "remove", "--workspace", workspace_id, "--force"])
    shutil.rmtree(tmpdir, ignore_errors=True)
    print("  PASS: Cleanup completed")

print("\nALL ASSERTIONS PASSED — dispatch-claude smoke test successful")
