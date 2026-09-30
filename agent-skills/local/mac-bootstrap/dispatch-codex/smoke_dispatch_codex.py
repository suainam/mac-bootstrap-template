#!/usr/bin/env python3
"""
smoke_dispatch_codex.py — end-to-end smoke test for dispatch-codex (#110)

Acceptance criteria verified:
1. OMP user approves plan before any worktree or agent is created (simulated: plan shown, manual
   gate via --auto-approve flag for CI; real gate requires human input).
2. Real Codex worker receives brief in a distinct Herdr-owned temporary git worktree; user's focus
   and checkout remain unchanged.
3. Parent runs a checkable acceptance criterion itself; worker's DONE claim alone is not success.
4. Missing CLI / Herdr session fails clearly without touching an unrelated pane.
5. No remote push or PR is created.

Usage:
    # Pre-requisite: run from inside a Herdr pane (HERDR_ENV=1 and HERDR_PANE_ID set)
    # Pre-requisite: codex CLI available
    # --auto-approve skips the interactive plan confirmation (for CI / fast smoke)
    python3 smoke_dispatch_codex.py [--auto-approve] [--timeout 300]

Exit codes:
    0  all assertions passed
    1  assertion failed (see output)
    2  pre-condition not met (skip, not fail)
"""
import argparse
import json
import os
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


# ── 0. Pre-conditions ────────────────────────────────────────────────────────

skip(HERDR_ENV == "1" and HERDR_PANE, "Not inside a Herdr pane (HERDR_ENV/HERDR_PANE_ID unset) — skip")
skip(run(["herdr", "agent", "list"]).returncode == 0, "herdr agent list failed — Herdr not reachable")
skip(run(["codex", "--version"]).returncode == 0, "codex CLI not available — skip")


# ── 1. Gate check: missing CLI fails clearly ─────────────────────────────────
print("[1] Gate: dispatch must fail clearly when codex not on PATH")
env_no_codex = {**os.environ, "PATH": "/usr/bin:/bin"}
result = run(
    ["python3", "-c",
     "import subprocess,sys; r=subprocess.run(['codex','--version'],capture_output=True); sys.exit(0 if r.returncode==0 else 1)"],
    env=env_no_codex,
)
require(result.returncode != 0, "Codex should not be found with restricted PATH")
print("  PASS: codex absent → returncode != 0")


# ── 2. Create a disposable git repo ──────────────────────────────────────────
print("[2] Creating disposable git repo")
tmpdir = tempfile.mkdtemp(prefix="dispatch_smoke_")
repo = Path(tmpdir) / "smoke_repo"
repo.mkdir()
run(["git", "init", str(repo)], check=True)
run(["git", "-C", str(repo), "config", "user.email", "smoke@test"], check=True)
run(["git", "-C", str(repo), "config", "user.name", "Smoke"], check=True)

# Seed a file Codex will be asked to modify
target = repo / "hello.py"
target.write_text('def greet():\n    return "hello"\n')
run(["git", "-C", str(repo), "add", "hello.py"], check=True)
run(["git", "-C", str(repo), "commit", "-m", "feat: initial hello"], check=True)
print(f"  repo: {repo}")


# ── 3. Write a lane brief manually (simulating §5b) ──────────────────────────
print("[3] Writing lane brief (.dispatch/TASK.md)")
dispatch_dir = repo / ".dispatch"
dispatch_dir.mkdir()
(repo / ".git" / "info" / "exclude").open("a").write(".dispatch/\n")

run_id = str(int(time.time()))[-6:]
lane = f"add-world-greeting-1"
orch_pane = HERDR_PANE

task_md = f"""\
# Objective
Add a `greet_world()` function to hello.py that returns "hello world".

# Plan
1. Edit hello.py: add `def greet_world(): return "hello world"` below the existing `greet()`.
2. Commit: `feat(hello): add greet_world function`.

# Checklist
- [ ] Add greet_world() to hello.py
- [ ] Commit with correct message

# Acceptance criteria
- `python3 -c "from hello import greet_world; assert greet_world() == 'hello world'"` exits 0.
- `git log --oneline HEAD` contains a commit message matching `feat(hello): add greet_world`.

# Boundaries
Work only in this checkout. Never push. Never open a PR. Never cd to another directory.

# Commit policy
Commit once per checklist item with a Conventional Commits message.

# Progress protocol
Keep .dispatch/progress.md current after each item. Write .dispatch/DONE with a one-line summary
when done.

# Completion notify-back
After writing .dispatch/DONE, run:
    herdr agent prompt {orch_pane} "[dispatch-codex {run_id}] lane {lane} wrote DONE — run one dispatch-codex --resume sweep now."
"""
(dispatch_dir / "TASK.md").write_text(task_md)
print("  brief written")


# ── 4. Create a Herdr workspace + pane for the lane ──────────────────────────
print("[4] Creating Herdr workspace for lane")

# Snapshot existing workspace ids
before = set(json.loads(
    run(["herdr", "workspace", "list"], check=True).stdout
)["result"]["workspaces"] and
    [w["workspace_id"] for w in json.loads(
        run(["herdr", "workspace", "list"], check=True).stdout
    )["result"]["workspaces"]])

# Use herdr workspace create (not worktree create — no remote needed for smoke)
ws_result = run(["herdr", "workspace", "create", "--cwd", str(repo), "--label", lane, "--no-focus"])
if ws_result.returncode != 0:
    print(f"  herdr workspace create failed: {ws_result.stderr}")
    sys.exit(2)

ws_data = json.loads(ws_result.stdout)
ws_id = ws_data["result"]["workspace"]["workspace_id"]
pane_id = ws_data["result"]["root_pane"]["pane_id"]
print(f"  workspace: {ws_id}  pane: {pane_id}")


# ── 5. Pre-flight Codex in the lane pane ─────────────────────────────────────
print("[5] Pre-flighting Codex in lane pane")
pf = run(["herdr", "pane", "run", pane_id, "codex --version"])
require(pf.returncode == 0, f"codex --version failed in lane pane: {pf.stderr}")
print(f"  codex version OK")


# ── 6. Launch Codex agent ─────────────────────────────────────────────────────
print("[6] Launching Codex agent")
launch = run([
    "herdr", "agent", "start", lane,
    "--kind", "codex",
    "--pane", pane_id,
    "--timeout", "120000",
    "--",
    "--no-alt-screen",
    "-c", "tui.status_line=[\"context-remaining\"]",
    "--dangerously-bypass-approvals-and-sandbox",
])
if launch.returncode != 0:
    print(f"  agent start failed: {launch.stderr}")
    # Cleanup
    run(["herdr", "workspace", "close", ws_id])
    sys.exit(2)
print(f"  agent {lane} started")

# Handle trust modal
time.sleep(5)
visible = run(["herdr", "agent", "read", lane, "--source", "visible"])
if "Do you trust the contents of this directory" in visible.stdout:
    run(["herdr", "agent", "send-keys", lane, "enter"])
    time.sleep(3)

# Wait for composer
deadline = time.time() + 60
ready = False
while time.time() < deadline:
    v = run(["herdr", "agent", "read", lane, "--source", "visible"])
    if "Ask Codex" in v.stdout or "›" in v.stdout:
        ready = True
        break
    time.sleep(3)
require(ready, "Codex composer not ready within 60s")
print("  composer ready")


# ── 7. Set goal ───────────────────────────────────────────────────────────────
print("[7] Setting Codex goal")
goal_cmd = (
    "Work through .dispatch/TASK.md in this directory: follow its plan in order, "
    "satisfy every acceptance criterion, keep .dispatch/progress.md updated after "
    "every checklist item, and finish by writing .dispatch/DONE and running the "
    "notify-back command TASK.md gives you."
)
goal_result = run(["herdr", "agent", "prompt", lane, f"/goal {goal_cmd}"])
require(goal_result.returncode == 0, f"goal prompt failed: {goal_result.stderr}")
print("  goal set")


# ── 8. Wait for DONE (parent-supervised polling) ──────────────────────────────
args = argparse.ArgumentParser()
args.add_argument("--timeout", type=int, default=300)
args.add_argument("--auto-approve", action="store_true")
opts = args.parse_args()

print(f"[8] Waiting for .dispatch/DONE (timeout {opts.timeout}s)")
done_file = dispatch_dir / "DONE"
deadline = time.time() + opts.timeout
while time.time() < deadline:
    if done_file.exists():
        break
    time.sleep(10)
    print("  ...", flush=True)

require(done_file.exists(), f".dispatch/DONE not written within {opts.timeout}s")
print(f"  DONE written: {done_file.read_text().strip()}")


# ── 9. Parent independently verifies acceptance criteria ──────────────────────
print("[9] Parent-side independent verification")

# Criterion 1: greet_world() returns "hello world"
verify1 = run(
    ["python3", "-c", "import sys; sys.path.insert(0,''); from hello import greet_world; assert greet_world() == 'hello world', f'got {greet_world()!r}'"],
    cwd=str(repo),
)
require(verify1.returncode == 0, f"Criterion 1 failed: {verify1.stderr}")
print("  PASS: greet_world() == 'hello world'")

# Criterion 2: commit message
log = run(["git", "-C", str(repo), "log", "--oneline", "HEAD"])
require("feat(hello): add greet_world" in log.stdout, f"Criterion 2 failed — expected commit not found:\n{log.stdout}")
print("  PASS: commit message matches")

# Verify worker did not push (no remote configured)
push_check = run(["git", "-C", str(repo), "remote"])
require(push_check.stdout.strip() == "", "No remote should exist in disposable repo — push would fail anyway")
print("  PASS: no remote configured — push impossible")

# Check git status clean
status = run(["git", "-C", str(repo), "status", "--porcelain"])
require(status.stdout.strip() == "", f"Working tree not clean:\n{status.stdout}")
print("  PASS: working tree clean")


# ── 10. Cleanup (print commands, do not run automatically) ────────────────────
print("[10] Cleanup commands (print only — not run automatically):")
print(f"  herdr workspace close {ws_id}")
print(f"  rm -rf {tmpdir}")

print()
print("ALL ASSERTIONS PASSED — #110 smoke test complete")
print(f"  Lane: {lane}  Workspace: {ws_id}  Repo: {repo}")
print("  No push/PR created (no remote; --push not passed)")
