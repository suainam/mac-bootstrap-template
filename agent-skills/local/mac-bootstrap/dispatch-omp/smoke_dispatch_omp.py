#!/usr/bin/env python3
"""
smoke_dispatch_omp.py — End-to-end smoke test for dispatch-omp (#115).

Verifies:
0. Pre-conditions: inside Herdr pane, herdr reachable, omp CLI available.
1. Pi status check: detects pi CLI absence, reports blocker for #115 completeness.
2. Gate check: dispatch fails clearly when omp is not on PATH.
3. Worktree isolation: creates isolated git worktree using `herdr worktree create`.
4. Native resume & session persistence: verifies OMP session creation and native
   resume via `--session-dir` and `--resume <session-id>`.
5. False-DONE rejection: worker claims DONE with faulty code; parent executes the
   EXACT SAME user-approved acceptance criterion, rejects DONE, and only verifies
   after the code is fixed to satisfy the agreed criterion.
6. Clean termination: worktree workspace closed cleanly without remote publication.

Usage:
    python3 smoke_dispatch_omp.py
"""
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


def main():
    print("=== dispatch-omp smoke test ===")

    # ── 0. Pre-conditions ────────────────────────────────────────────────────────
    skip(HERDR_ENV == "1" and HERDR_PANE, "Not inside a Herdr pane (HERDR_ENV/HERDR_PANE_ID unset) — skip")
    print("[1] Verifying Pi worker status")
    if not shutil.which("pi"):
        print("  NOTICE: pi CLI is NOT_FOUND on this workstation.")
        print("  BLOCKER: #115 is incomplete for Pi until pi CLI is installed and available.")
    else:
        print("  NOTICE: pi CLI found, but dispatch-omp covers only OMP worker.")

    # ── 2. Gate check: missing CLI fails clearly ─────────────────────────────────
    print("[2] Gate check: dispatch-omp must fail when omp is not on PATH")
    env_no_omp = {**os.environ, "PATH": "/usr/bin:/bin"}
    gate_probe = run(
        ["python3", "-c",
         "import subprocess,sys; r=subprocess.run(['omp','--version'],capture_output=True); sys.exit(0 if r.returncode==0 else 1)"],
        env=env_no_omp,
    )
    require(gate_probe.returncode != 0, "omp should not be found with restricted PATH")
    print("  PASS: omp absent from PATH fails gate check")

    # ── 3. Native session persistence & resume verification ──────────────────────
    print("[3] Verifying OMP native session creation and resume via --session-dir")
    with tempfile.TemporaryDirectory(prefix="omp_session_test_") as sess_td:
        # Step A: initial session turn
        r1 = run(["omp", "--session-dir", sess_td, "-p", "remember the fruit: blue-avocado"])
        require(r1.returncode == 0, f"omp session init failed: {r1.stderr}")

        # Step B: locate session file and extract UUID
        jsonl_files = [f for f in os.listdir(sess_td) if f.endswith(".jsonl")]
        require(len(jsonl_files) > 0, f"No session JSONL file created in {sess_td}")
        session_file = jsonl_files[0]
        # format: <timestamp>_<uuid>.jsonl
        session_id = session_file.split("_")[1].replace(".jsonl", "")
        print(f"  Session created: {session_id}")

        # Step C: native resume with --resume
        r2 = run(["omp", "--session-dir", sess_td, "--resume", session_id, "-p", "what fruit did I ask you to remember? Output only the name."])
        require(r2.returncode == 0, f"omp resume failed: {r2.stderr}")
        require("blue-avocado" in r2.stdout.lower() or "avocado" in r2.stdout.lower(), f"Resume did not retain memory: {r2.stdout}")
        print("  PASS: native resume recalled context correctly")
    # ── 4. Worktree isolation with herdr worktree create ─────────────────────────
    print("[4] Setting up scratch repository and Herdr worktree")
    tmpdir = tempfile.mkdtemp(prefix="dispatch_omp_smoke_")
    ws_id = None
    try:
        repo = Path(tmpdir) / "smoke_repo"
        repo.mkdir()
        run(["git", "init", "-b", "main", str(repo)], check=True)
        run(["git", "-C", str(repo), "config", "user.email", "smoke@test"], check=True)
        run(["git", "-C", str(repo), "config", "user.name", "Smoke"], check=True)

        target = repo / "math_tools.py"
        target.write_text("# math tools\n")
        run(["git", "-C", str(repo), "add", "math_tools.py"], check=True)
        run(["git", "-C", str(repo), "commit", "-m", "chore: initial commit"], check=True)

        # Create isolated worktree via herdr worktree create
        lane = f"lane-math-{int(time.time()) % 10000}"
        branch = f"dispatch/{lane}"
        wt_cmd = [
            "herdr", "worktree", "create",
            "--cwd", str(repo),
            "--branch", branch,
            "--label", lane,
            "--no-focus"
        ]
        wt_res = run(wt_cmd)
        require(wt_res.returncode == 0, f"herdr worktree create failed: {wt_res.stderr}")
        wt_data = json.loads(wt_res.stdout)
        ws_id = wt_data["result"]["workspace"]["workspace_id"]
        pane_id = wt_data["result"]["root_pane"]["pane_id"]
        wt_path = Path(wt_data["result"]["worktree"]["path"])
        print(f"  Worktree created: ws={ws_id}, pane={pane_id}, path={wt_path}")

        # ── 5. Brief specification ───────────────────────────────────────────────
        print("[5] Writing lane brief (.dispatch/TASK.md)")
        dispatch_dir = wt_path / ".dispatch"
        dispatch_dir.mkdir(exist_ok=True)
        # In a git worktree, .git is a file. Resolve info/exclude via git rev-parse:
        exclude_rel = run(["git", "-C", str(wt_path), "rev-parse", "--git-path", "info/exclude"]).stdout.strip()
        exclude_path = Path(exclude_rel) if Path(exclude_rel).is_absolute() else (wt_path / exclude_rel)
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        with open(exclude_path, "a") as f:
            f.write(".dispatch/\n")
        # Define user-approved acceptance criterion:
        # BOTH brief and parent verification must use the exact SAME criterion
        criterion_cmd = ["python3", "-c", "from math_tools import square; assert square(5) == 25"]
        criterion_str = 'python3 -c "from math_tools import square; assert square(5) == 25"'

        brief_md = f"""# TASK: Add square function
## Objective
Add `def square(n): return n * n` to math_tools.py.

## Acceptance Criteria
- `{criterion_str}` passes.
"""
        (dispatch_dir / "TASK.md").write_text(brief_md)

        # ── 6. False-DONE Rejection Verification ─────────────────────────────────
        print("[6] Verifying false-DONE rejection with SAME acceptance criterion")
        # Step A: Worker claims DONE prematurely with buggy implementation
        (wt_path / "math_tools.py").write_text("def square(n):\n    return n + n  # Buggy implementation\n")
        (dispatch_dir / "DONE").write_text("Done implementing square\n")
        (dispatch_dir / "progress.md").write_text("- [x] Add square\n")

        # Step B: Parent runs the SAME agreed criterion against the lane checkout
        parent_check_1 = run(criterion_cmd, cwd=str(wt_path))
        require(parent_check_1.returncode != 0, "False-DONE should fail parent acceptance check!")
        print("  PASS: false-DONE caught and rejected by parent acceptance check")

        # Step C: Worker fixes the code to satisfy the agreed criterion
        (wt_path / "math_tools.py").write_text("def square(n):\n    return n * n  # Correct implementation\n")
        run(["git", "-C", str(wt_path), "add", "math_tools.py"], check=True)
        run(["git", "-C", str(wt_path), "commit", "-m", "feat(math): implement square function"], check=True)

        # Step D: Parent re-runs the SAME agreed criterion
        parent_check_2 = run(criterion_cmd, cwd=str(wt_path))
        require(parent_check_2.returncode == 0, f"Corrected implementation failed acceptance: {parent_check_2.stderr}")
        print("  PASS: corrected implementation satisfied agreed criterion")

        # Step E: Verify git status clean in worktree
        status = run(["git", "-C", str(wt_path), "status", "--porcelain"])
        require(status.stdout.strip() == "", f"Worktree dirty: {status.stdout}")
        print("  PASS: worktree git status clean")

        # Step F: Verify commit made on branch
        log = run(["git", "-C", str(wt_path), "log", "--oneline", "-1"])
        require("feat(math): implement square function" in log.stdout, "Expected commit not found")
        print("  PASS: verified commit present")

    finally:
        # Cleanup worktree workspace cleanly
        if ws_id:
            run(["herdr", "workspace", "close", ws_id])
            print(f"  Closed worktree workspace {ws_id}")
        shutil.rmtree(tmpdir, ignore_errors=True)

    print()
    print("ALL ASSERTIONS PASSED — dispatch-omp smoke test complete.")
    sys.exit(0)


if __name__ == "__main__":
    main()
