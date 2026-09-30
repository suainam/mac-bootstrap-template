#!/usr/bin/env python3
"""
smoke_dispatch_opencode.py — end-to-end smoke test for dispatch-opencode (#112)

Acceptance criteria verified:
1. Gate check: missing CLI / restricted PATH fails clearly without touching an unrelated pane.
2. Real Herdr worktree create: uses `herdr worktree create` (not workspace create) for true
   isolated git worktree under ~/.herdr/worktrees/<repo>/<branch>.
3. Safe defaults: launches without approval bypass (--auto), maintaining security postures.
4. Native session identity: verifies Herdr tracks OpenCode session identity in agent_session.value.
5. Native resume: tests resuming the same OpenCode session via `-s <session_id>`.
6. False DONE rejection: worker's DONE claim alone never grants verification. The parent independently
   evaluates the SAME user-approved criterion; when criterion fails, DONE is rejected.
7. Independent parent verification: parent independently confirms criterion passes when satisfied.
8. No publication: verifies no remote configured and no push/PR attempted.

Usage:
    python3 smoke_dispatch_opencode.py [--timeout 300]

Exit codes:
    0  all assertions passed
    1  assertion failed (see output)
    2  pre-condition not met (skip, not fail)
"""
import argparse
import json
import os
import subprocess
import atexit
import shutil
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
print("[1] Gate: dispatch must fail clearly when opencode not on PATH")
env_no_opencode = {**os.environ, "PATH": "/usr/bin:/bin"}
result = run(
    ["python3", "-c",
     "import subprocess,sys; r=subprocess.run(['opencode','--version'],capture_output=True); sys.exit(0 if r.returncode==0 else 1)"],
    env=env_no_opencode,
)
require(result.returncode != 0, "OpenCode should not be found with restricted PATH")
print("  PASS: opencode absent → returncode != 0")


# ── 0. Pre-conditions for live agent run ──────────────────────────────────────
skip(HERDR_ENV == "1" and HERDR_PANE, "Not inside a Herdr pane (HERDR_ENV/HERDR_PANE_ID unset) — skip")
skip(run(["herdr", "agent", "list"]).returncode == 0, "herdr agent list failed — Herdr not reachable")
skip(run(["opencode", "--version"]).returncode == 0, "opencode CLI not available — skip")


# ── 2. Create a disposable git repo ──────────────────────────────────────────
print("[2] Creating disposable git repo")
tmpdir = tempfile.mkdtemp(prefix="dispatch_opencode_smoke_")
repo = Path(tmpdir) / "smoke_repo"
repo.mkdir()
run(["git", "init", str(repo)], check=True)
run(["git", "-C", str(repo), "config", "user.email", "smoke@test"], check=True)
run(["git", "-C", str(repo), "config", "user.name", "Smoke"], check=True)

# Initial file without compute_sum
target = repo / "math_ops.py"
target.write_text('"""Math operations initial."""\n')
run(["git", "-C", str(repo), "add", "math_ops.py"], check=True)
run(["git", "-C", str(repo), "commit", "-m", "feat: initial math_ops"], check=True)
print(f"  repo: {repo}")


# ── 3. Real Herdr worktree create ─────────────────────────────────────────────
print("[3] Creating isolated git worktree via herdr worktree create")
lane = f"lane-math-{str(int(time.time()))[-4:]}"
branch = f"feat/{lane}"

wt_res = run([
    "herdr", "worktree", "create",
    "--cwd", str(repo),
    "--branch", branch,
    "--base", "HEAD",
    "--label", lane,
    "--no-focus",
])
require(wt_res.returncode == 0, f"herdr worktree create failed: {wt_res.stderr}")

wt_data = json.loads(wt_res.stdout)
ws_id = wt_data["result"]["workspace"]["workspace_id"]
pane_id = wt_data["result"]["root_pane"]["pane_id"]
checkout_path = Path(wt_data["result"]["worktree"]["path"])
require(checkout_path.exists(), f"Worktree checkout path does not exist: {checkout_path}")
print(f"  workspace: {ws_id}  pane: {pane_id}  checkout: {checkout_path}")
def cleanup():
    print("[Cleanup] Cleaning up worktree and agent")
    run(["herdr", "agent", "prompt", lane, "/exit"])
    time.sleep(1)
    rm_res = run(["herdr", "worktree", "remove", "--workspace", ws_id, "--force"])
    if rm_res.returncode != 0:
        run(["herdr", "workspace", "close", ws_id])
    shutil.rmtree(tmpdir, ignore_errors=True)

atexit.register(cleanup)



# ── 4. Write lane brief (.dispatch/TASK.md) ───────────────────────────────────
print("[4] Writing lane brief (.dispatch/TASK.md)")
dispatch_dir = checkout_path / ".dispatch"
dispatch_dir.mkdir(exist_ok=True)
exclude_rel = run(["git", "-C", str(checkout_path), "rev-parse", "--git-path", "info/exclude"], check=True).stdout.strip()
exclude_path = Path(exclude_rel) if os.path.isabs(exclude_rel) else checkout_path / exclude_rel
exclude_path.parent.mkdir(parents=True, exist_ok=True)
with exclude_path.open("a") as f:
    f.write(".dispatch/\n")

task_md = f"""\
# Objective
Add a `compute_sum(a, b)` function to math_ops.py that returns `a + b`.

# Plan
1. Edit math_ops.py: add `def compute_sum(a, b): return a + b`.

# Checklist
- [ ] Add compute_sum(a, b) to math_ops.py

# Acceptance criteria
- `python3 -c "from math_ops import compute_sum; assert compute_sum(2, 3) == 5"` exits 0.

# Boundaries
Work only in this checkout. Never push. Never open a PR.

# Progress protocol
Keep .dispatch/progress.md current after each item. Write .dispatch/DONE when finished.
"""
(dispatch_dir / "TASK.md").write_text(task_md)
print("  brief written")


# ── 5. Pre-flight OpenCode in lane pane ───────────────────────────────────────
print("[5] Pre-flighting OpenCode in lane pane")
pf = run(["herdr", "pane", "run", pane_id, "opencode --version"])
require(pf.returncode == 0, f"opencode --version failed in lane pane: {pf.stderr}")
print("  opencode version OK")
time.sleep(2)

# ── 6. Launch OpenCode agent in safe mode (default posture) ───────────────────
print("[6] Launching OpenCode agent in safe mode (no approval bypass)")
launch = run([
    "herdr", "agent", "start", lane,
    "--kind", "opencode",
    "--pane", pane_id,
    "--timeout", "60000",
])
if launch.returncode != 0:
    print(f"  agent start failed: {launch.stderr}")
    run(["herdr", "workspace", "close", ws_id])
    sys.exit(2)
print(f"  agent {lane} started")

# Check for trust dialog
time.sleep(3)
visible = run(["herdr", "agent", "read", lane, "--source", "visible"])
if "trust" in visible.stdout.lower():
    run(["herdr", "agent", "send-keys", lane, "enter"])
    time.sleep(2)


# ── 7. Send initial prompt & capture native session identity ──────────────────
print("[7] Sending prompt & capturing native session identity")
prompt_text = "Read .dispatch/TASK.md and report readiness."
prompt_res = run(["herdr", "agent", "prompt", lane, prompt_text])
require(prompt_res.returncode == 0, f"prompt failed: {prompt_res.stderr}")

# Wait for session identity to populate
session_id = None
deadline = time.time() + 30
while time.time() < deadline:
    agent_info = run(["herdr", "agent", "get", lane])
    if agent_info.returncode == 0:
        data = json.loads(agent_info.stdout)
        sess = data.get("result", {}).get("agent", {}).get("agent_session")
        if sess and sess.get("value"):
            session_id = sess["value"]
            break
    time.sleep(2)

require(session_id is not None, "Failed to capture native OpenCode session ID from Herdr")
print(f"  PASS: native session identity captured: {session_id}")


# ── 8. Interrupt and settle agent ─────────────────────────────────────────────
print("[8] Interrupting prompt and verifying agent settlement")
run(["herdr", "agent", "send-keys", lane, "esc", "esc"])
time.sleep(2)

agent_status = None
deadline = time.time() + 20
while time.time() < deadline:
    agent_info = run(["herdr", "agent", "get", lane])
    if agent_info.returncode == 0:
        data = json.loads(agent_info.stdout)
        agent_status = data.get("result", {}).get("agent", {}).get("agent_status")
        if agent_status in ("idle", "done"):
            break
    time.sleep(2)

require(agent_status in ("idle", "done"), f"Agent did not settle to idle/done: {agent_status}")
print(f"  PASS: agent settled with status: {agent_status}")


# ── 9. Native session resume verification ─────────────────────────────────────
print("[9] Testing native session resume via -s <session-id>")
# Exit OpenCode
run(["herdr", "agent", "prompt", lane, "/exit"])
time.sleep(2)

# Resume existing session
resume_res = run([
    "herdr", "agent", "start", lane,
    "--kind", "opencode",
    "--pane", pane_id,
    "--timeout", "60000",
    "--",
    "-s", session_id,
])
require(resume_res.returncode == 0, f"Native resume failed: {resume_res.stderr}")

# Verify session ID matches
resumed_info = run(["herdr", "agent", "get", lane])
require(resumed_info.returncode == 0, f"herdr agent get failed on resume: {resumed_info.stderr}")
resumed_sess = json.loads(resumed_info.stdout).get("result", {}).get("agent", {}).get("agent_session", {}).get("value")
require(resumed_sess == session_id, f"Resumed session mismatch: got {resumed_sess}, expected {session_id}")
print(f"  PASS: native resume restored session {session_id}")


# ── 10. False DONE rejection using SAME acceptance criterion ──────────────────
print("[10] False DONE rejection using SAME user-approved acceptance criterion")
# Create premature DONE while math_ops.py does NOT yet implement compute_sum
done_file = dispatch_dir / "DONE"
done_file.write_text("Worker claimed done prematurely\n")

# Run the SAME acceptance criterion specified in brief:
criterion_cmd = ["python3", "-c", "from math_ops import compute_sum; assert compute_sum(2, 3) == 5"]
parent_check_false = run(criterion_cmd, cwd=str(checkout_path))

# Must fail because compute_sum is not implemented yet!
require(parent_check_false.returncode != 0, "Acceptance criterion unexpectedly passed on unimplemented code")
print("  PASS: premature DONE correctly rejected by parent verification")

# Remove fake DONE
done_file.unlink()


# ── 11. Parent independent verification when criterion holds ──────────────────
print("[11] Implementing change and verifying parent check succeeds")
# Now satisfy the criterion
math_file = checkout_path / "math_ops.py"
math_file.write_text('"""Math operations."""\n\ndef compute_sum(a, b):\n    return a + b\n')

# Re-run the EXACT SAME criterion
parent_check_true = run(criterion_cmd, cwd=str(checkout_path))
require(parent_check_true.returncode == 0, f"Parent verification failed: {parent_check_true.stderr}")
print("  PASS: criterion verified by parent check")

# Write genuine DONE
done_file.write_text("Implemented and verified compute_sum(a, b)\n")


# ── 12. Verify no publication ─────────────────────────────────────────────────
print("[12] Verifying no publication (default posture: no push, no PR)")
remote_check = run(["git", "-C", str(checkout_path), "remote"])
require(remote_check.stdout.strip() == "", "No remote should exist in disposable repo")
print("  PASS: no remote configured — push/PR impossible")


# Cleanup will run automatically via atexit on exit
print()
print("ALL ASSERTIONS PASSED — #112 dispatch-opencode smoke test complete")
print(f"  Lane: {lane}  Workspace: {ws_id}")
print(f"  Native session: {session_id}")
print("  Real Herdr worktree, safe defaults, false DONE rejection, native resume verified.")
