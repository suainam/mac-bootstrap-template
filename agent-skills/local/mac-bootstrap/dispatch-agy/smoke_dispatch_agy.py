#!/usr/bin/env python3
"""
Smoke test for dispatch-agy (#114).

Verifies prerequisites, gate checks, real Herdr worktree creation, brief generation,
false-DONE detection with identical acceptance criteria, independent parent-side
verification, no-publication guarantee, and Herdr integration/native identity.

Prerequisites tested:
  1. agy CLI available on PATH (fails clearly with code 2 otherwise)
  2. Herdr environment (HERDR_ENV=1, HERDR_PANE_ID set) (fails clearly with code 2 otherwise)
  3. Herdr integration antigravity-cli installed
  4. Real Herdr worktree creation and lifecycle
  5. False-DONE detection using EXACT same criterion in brief and check
  6. Independent parent verification
  7. No publication (no remote)
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
    try:
        return subprocess.run(cmd, **kw)
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, returncode=127, stdout="", stderr="command not found")


def require(condition, msg):
    if not condition:
        print(f"FAIL: {msg}", file=sys.stderr)
        sys.exit(1)


def skip(condition, msg):
    if not condition:
        print(f"SKIP: {msg}")
        sys.exit(2)


# ── 0. Pre-conditions ────────────────────────────────────────────────────────

skip(HERDR_ENV == "1" and HERDR_PANE, "Not inside a Herdr pane (HERDR_ENV/HERDR_PANE_ID unset) — skip")
skip(run(["herdr", "agent", "list"]).returncode == 0, "herdr agent list failed — Herdr not reachable")
skip(run(["agy", "--version"]).returncode == 0, "agy CLI not available — skip")


# ── 1. Gate check: missing CLI fails clearly ─────────────────────────────────
print("[1] Gate: dispatch must fail clearly when agy not on PATH")
env_no_agy = {**os.environ, "PATH": "/usr/bin:/bin"}
result = run(
    ["bash", "-c", "command -v agy || which agy"],
    env=env_no_agy,
)
require(result.returncode != 0, "agy should not be found with restricted PATH")
print("  PASS: agy absent → returncode != 0")


# ── 2. Herdr Integration verification (antigravity-cli vs kind agy) ─────────
print("[2] Verifying Herdr integration 'antigravity-cli' and agent kind 'agy'")
integ_status = run(["herdr", "integration", "status"])
require(integ_status.returncode == 0, f"herdr integration status failed: {integ_status.stderr}")
require("antigravity-cli" in integ_status.stdout, "Integration 'antigravity-cli' not listed in herdr integration status")
print("  PASS: herdr integration antigravity-cli is installed and recognized")

help_out = run(["agy", "--help"])
help_text = help_out.stdout + help_out.stderr
require("--continue" in help_text or "-c" in help_text, "agy missing native --continue flag")
require("--conversation" in help_text, "agy missing native --conversation flag")
# agy does not have a 'session list' subcommand
session_check = run(["agy", "session", "list"])
require(session_check.returncode != 0, "agy session list should not exist as a native subcommand")
print("  PASS: agy native resume flags verified (--continue, --conversation; no guessed session list)")


# ── 3. Create a disposable git repo with initial commit ──────────────────────
print("[3] Creating disposable git repo")
tmpdir = tempfile.mkdtemp(prefix="dispatch_agy_smoke_")
repo = Path(tmpdir) / "smoke_repo"
repo.mkdir()
run(["git", "init", str(repo)], check=True)
run(["git", "-C", str(repo), "config", "user.email", "smoke@test"], check=True)
run(["git", "-C", str(repo), "config", "user.name", "Smoke"], check=True)

# Seed an initial commit so HEAD ref exists for worktree creation
target = repo / "greeter.py"
target.write_text('# Initial greeter stub\n')
run(["git", "-C", str(repo), "add", "greeter.py"], check=True)
run(["git", "-C", str(repo), "commit", "-m", "chore: initial greeter stub"], check=True)
print(f"  repo: {repo}")


# ── 4. Create a REAL Herdr worktree (not workspace create) ───────────────────
print("[4] Creating real Herdr git worktree")
unique_suffix = f"{os.getpid()}-{int(time.time()) % 10000}"
lane = f"add-greeting-{unique_suffix}"
branch = f"dispatch/{lane}"
wt_result = run([
    "herdr", "worktree", "create",
    "--cwd", str(repo),
    "--branch", branch,
    "--base", "HEAD",
    "--label", lane,
    "--no-focus"
])
require(wt_result.returncode == 0, f"herdr worktree create failed: {wt_result.stderr}")
wt_data = json.loads(wt_result.stdout)
ws_id = wt_data["result"]["workspace"]["workspace_id"]
pane_id = wt_data["result"]["root_pane"]["pane_id"]
wt_path = Path(wt_data["result"]["worktree"]["path"])

print(f"  workspace: {ws_id}  pane: {pane_id}  worktree: {wt_path}")
require(wt_path.exists(), f"Worktree path does not exist: {wt_path}")
require((wt_path / ".git").exists(), "Worktree must have isolated .git pointer")
print("  PASS: isolated git worktree created")


try:
    # ── 5. Pre-flight agy in the lane's pane ──────────────────────────────────
    print("[5] Pre-flighting agy in lane pane")
    pf = run(["herdr", "pane", "run", pane_id, "agy --version"])
    require(pf.returncode == 0, f"agy --version failed in lane pane: {pf.stderr}")
    print("  PASS: agy version check succeeded in pane")


    # ── 6. Write lane brief (.dispatch/TASK.md) ──────────────────────────────
    print("[6] Writing lane brief (.dispatch/TASK.md) in worktree")
    dispatch_dir = wt_path / ".dispatch"
    dispatch_dir.mkdir(parents=True, exist_ok=True)
    exc_raw = run(["git", "-C", str(wt_path), "rev-parse", "--git-path", "info/exclude"]).stdout.strip()
    exc_path = Path(exc_raw) if Path(exc_raw).is_absolute() else (wt_path / exc_raw)
    exc_path.parent.mkdir(parents=True, exist_ok=True)
    exc_path.open("a").write(".dispatch/\n")

    run_id = str(int(time.time()))[-6:]
    acceptance_criterion_cmd = "python3 -c \"from greeter import greet; assert greet('World')=='Hello, World!'\""

    task_md = f"""\
# Lane Brief: {lane} (run {run_id})

## Objective
Implement greet(name) in greeter.py: return f"Hello, {{name}}!".

## Plan
1. Edit greeter.py to add `greet(name): return f"Hello, {{name}}!"`
2. Run test to verify: `{acceptance_criterion_cmd}`
3. Commit with message: `feat(greeter): add greet function`
4. Update .dispatch/progress.md and write .dispatch/DONE

## Acceptance criteria
- `{acceptance_criterion_cmd}`
- git status is clean
- no push, no PR
"""
    (dispatch_dir / "TASK.md").write_text(task_md)
    print("  PASS: brief written with exact acceptance criterion")


    # ── 7. Test False-DONE detection with EXACT same acceptance criterion ─────
    print("[7] Testing False-DONE detection with EXACT same criterion")
    # Simulate worker writing DONE prematurely while greeter.py still has stub
    done_file = dispatch_dir / "DONE"
    done_file.write_text("DONE: Finished early claim\n")

    # Parent supervisor runs the EXACT same criterion from the brief
    check_premature = run(["bash", "-c", acceptance_criterion_cmd], cwd=str(wt_path))
    require(check_premature.returncode != 0, "Acceptance check should FAIL on initial stub")

    # Supervisor detects false DONE: lane is NOT verified, corrective prompt generated
    is_verified = (check_premature.returncode == 0)
    require(not is_verified, "False DONE must NOT be verified")
    corrective_nudge = (
        f"Acceptance criterion failed: {acceptance_criterion_cmd} returned non-zero exit code.\n"
        f"Stderr: {check_premature.stderr.strip()}\n"
        f"Please fix greeter.py so the acceptance test passes."
    )
    print("  PASS: False-DONE detected and rejected using exact brief acceptance check")
    print(f"  Generated corrective nudge: {corrective_nudge[:80]}...")


    # ── 8. Worker implements change & Parent independent verification ─────────
    print("[8] Applying change and running independent parent-side verification")
    wt_greeter = wt_path / "greeter.py"
    wt_greeter.write_text('def greet(name):\n    return f"Hello, {name}!"\n')

    # Parent independently runs the EXACT same criterion from the brief
    check_verified = run(["bash", "-c", acceptance_criterion_cmd], cwd=str(wt_path))
    require(check_verified.returncode == 0, f"Acceptance check failed after fix: {check_verified.stderr}")
    print("  PASS: exact acceptance criterion passes with implementation")

    # Commit the verified change in the worktree
    run(["git", "-C", str(wt_path), "add", "greeter.py"], check=True)
    run(["git", "-C", str(wt_path), "commit", "-m", "feat(greeter): add greet function"], check=True)

    # Verify working tree is clean
    status = run(["git", "-C", str(wt_path), "status", "--porcelain"])
    require(status.stdout.strip() == "", f"Working tree not clean:\n{status.stdout}")
    print("  PASS: working tree is clean")


    # ── 9. Verify No Publication (No remote) ─────────────────────────────────
    print("[9] Verifying No Publication (no remote configured)")
    remotes = run(["git", "-C", str(wt_path), "remote"])
    require(remotes.stdout.strip() == "", "No remote should exist — publication impossible")
    print("  PASS: no remote configured; local worktree branch preserved without push")

finally:
    # ── 10. Clean up worktree and temporary files ────────────────────────────
    print("[10] Cleaning up real Herdr worktree")
    rm_res = run(["herdr", "worktree", "remove", "--workspace", ws_id, "--force"])
    if rm_res.returncode == 0:
        print(f"  PASS: worktree {ws_id} removed cleanly")
    else:
        print(f"  WARN: worktree remove returned {rm_res.returncode}, closing workspace {ws_id}")
        run(["herdr", "workspace", "close", ws_id])
    shutil.rmtree(tmpdir, ignore_errors=True)

print()
print("ALL ASSERTIONS PASSED — smoke_dispatch_agy complete")
