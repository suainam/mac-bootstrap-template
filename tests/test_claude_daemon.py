"""Tests for claude-daemon-tmux.sh keepalive script.

Coverage:
- Syntax validity (bash -n)
- Lock file: prevents duplicate runs
- Lock file: cleans up stale entries
- Timeout: SIGTERM fires at deadline
- Timeout: SIGKILL fires if SIGTERM ignored
- Process-group kill: child processes die with parent
- Exit-code propagation: non-zero exits are recorded
- Log format: timestamps, elapsed time, exit status present
- Env override: CLAUDE_TIMEOUT respected
- Env override: CLAUDE_PROJECT_DIR respected
- Idempotent lock cleanup on EXIT trap
"""

import os
import re
import subprocess
import tempfile
import textwrap
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "claude-daemon-tmux.sh"


# ── helpers ────────────────────────────────────────────────────────────────────

def run_script(env: dict | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run the daemon script with a fake `claude` on PATH."""
    merged = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env=merged,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def fake_claude_bin(tmp_path: Path, *, exit_code: int = 0, sleep_secs: float = 0, ignore_term: bool = False) -> Path:
    """Write a tiny fake `claude` executable into tmp_path/bin/ and return its directory."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    body_lines = []
    if ignore_term:
        body_lines.append("trap '' TERM")   # ignore SIGTERM
    if sleep_secs:
        body_lines.append(f"sleep {sleep_secs}")
    body_lines.append(f"exit {exit_code}")
    script = bin_dir / "claude"
    script.write_text("#!/usr/bin/env bash\n" + "\n".join(body_lines) + "\n")
    script.chmod(0o755)
    return bin_dir


def log_path(log_dir: Path) -> Path:
    return log_dir / "tmux.log"


def read_log(log_dir: Path) -> str:
    p = log_path(log_dir)
    return p.read_text() if p.exists() else ""


def base_env(tmp_path: Path, bin_dir: Path, **extra) -> dict:
    """Minimal environment: fake bin injected via CLAUDE_BIN_EXTRA_PATH, isolated log/lock dirs."""
    log_dir = tmp_path / "Library" / "Logs" / "claude-daemon"
    log_dir.mkdir(parents=True, exist_ok=True)
    return {
        # Injected before script's own PATH export (see CLAUDE_BIN_EXTRA_PATH in script)
        "CLAUDE_BIN_EXTRA_PATH": str(bin_dir),
        "HOME": str(tmp_path),
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "CLAUDE_TIMEOUT": "5",  # fast default for tests
        **extra,
    }


# ── 1. Static / syntax ─────────────────────────────────────────────────────────

class TestSyntax:
    def test_bash_syntax_valid(self):
        """bash -n must pass with no errors."""
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"Syntax error:\n{result.stderr}"

    def test_script_is_executable_or_readable(self):
        assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
        assert os.access(SCRIPT, os.R_OK)

    def test_shebang_is_bash(self):
        first_line = SCRIPT.read_text().splitlines()[0]
        assert "bash" in first_line, f"Unexpected shebang: {first_line}"


# ── 2. Happy path ──────────────────────────────────────────────────────────────

class TestHappyPath:
    def test_exits_zero_on_success(self, tmp_path):
        bin_dir = fake_claude_bin(tmp_path, exit_code=0)
        result = run_script(base_env(tmp_path, bin_dir))
        assert result.returncode == 0

    def test_log_created(self, tmp_path):
        bin_dir = fake_claude_bin(tmp_path, exit_code=0)
        run_script(base_env(tmp_path, bin_dir))
        log = read_log(tmp_path / "Library" / "Logs" / "claude-daemon")
        assert log, "Log file should not be empty"

    def test_log_contains_start_banner(self, tmp_path):
        bin_dir = fake_claude_bin(tmp_path, exit_code=0)
        run_script(base_env(tmp_path, bin_dir))
        log = read_log(tmp_path / "Library" / "Logs" / "claude-daemon")
        assert "tmux daemon starting" in log

    def test_log_contains_finished_banner(self, tmp_path):
        bin_dir = fake_claude_bin(tmp_path, exit_code=0)
        run_script(base_env(tmp_path, bin_dir))
        log = read_log(tmp_path / "Library" / "Logs" / "claude-daemon")
        assert "claude keepalive finished" in log

    def test_log_has_timestamp_format(self, tmp_path):
        bin_dir = fake_claude_bin(tmp_path, exit_code=0)
        run_script(base_env(tmp_path, bin_dir))
        log = read_log(tmp_path / "Library" / "Logs" / "claude-daemon")
        assert re.search(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]", log)

    def test_log_reports_elapsed_seconds(self, tmp_path):
        bin_dir = fake_claude_bin(tmp_path, exit_code=0)
        run_script(base_env(tmp_path, bin_dir))
        log = read_log(tmp_path / "Library" / "Logs" / "claude-daemon")
        assert re.search(r"\d+s, exit 0", log), f"No elapsed/exit in log:\n{log}"

    def test_log_reports_exit_zero(self, tmp_path):
        bin_dir = fake_claude_bin(tmp_path, exit_code=0)
        run_script(base_env(tmp_path, bin_dir))
        log = read_log(tmp_path / "Library" / "Logs" / "claude-daemon")
        assert "exit 0" in log

    def test_log_reports_timeout_setting(self, tmp_path):
        bin_dir = fake_claude_bin(tmp_path, exit_code=0)
        env = base_env(tmp_path, bin_dir, CLAUDE_TIMEOUT="7")
        run_script(env)
        log = read_log(tmp_path / "Library" / "Logs" / "claude-daemon")
        assert "timeout: 7s" in log


# ── 3. Non-zero exit ───────────────────────────────────────────────────────────

class TestNonZeroExit:
    def test_nonzero_claude_logged(self, tmp_path):
        """A failing claude should still log finished with non-zero exit."""
        bin_dir = fake_claude_bin(tmp_path, exit_code=1)
        run_script(base_env(tmp_path, bin_dir))
        log = read_log(tmp_path / "Library" / "Logs" / "claude-daemon")
        # Script exits 0 (we don't propagate claude failure) but logs exit code
        assert re.search(r"exit [1-9]", log), f"Expected non-zero exit in log:\n{log}"

    def test_script_exits_zero_even_when_claude_fails(self, tmp_path):
        """Daemon script itself should not fail just because claude -p returned non-zero."""
        bin_dir = fake_claude_bin(tmp_path, exit_code=42)
        result = run_script(base_env(tmp_path, bin_dir))
        # launchd should not restart unnecessarily; non-zero would trigger KeepAlive
        assert result.returncode == 0


# ── 4. Lock file ───────────────────────────────────────────────────────────────

class TestLockFile:
    def test_lock_file_removed_after_run(self, tmp_path):
        bin_dir = fake_claude_bin(tmp_path, exit_code=0)
        run_script(base_env(tmp_path, bin_dir))
        lock = tmp_path / "tmp" / "claude-daemon.lock"
        # The lock should be cleaned up by the EXIT trap
        # (Note: /tmp is absolute; our fake HOME won't intercept it, so just check process exited cleanly)
        # We verify indirectly: a second run must also succeed (lock not stuck)
        result2 = run_script(base_env(tmp_path, bin_dir))
        assert result2.returncode == 0, "Second run failed — stale lock not cleaned"

    def test_stale_lock_is_cleared(self, tmp_path):
        """A lock file pointing to a dead PID should be silently removed."""
        # Write a lock with a PID that no longer exists (use PID 1 as sentinel; 
        # we just need one that won't be ours and is safe to probe)
        dead_pid = 999999  # extremely unlikely to be running
        lock_path = Path("/tmp/claude-daemon.lock")
        lock_path.write_text(str(dead_pid))
        try:
            bin_dir = fake_claude_bin(tmp_path, exit_code=0)
            result = run_script(base_env(tmp_path, bin_dir))
            assert result.returncode == 0
            log = read_log(tmp_path / "Library" / "Logs" / "claude-daemon")
            assert "stale" in log.lower() or "WARN" in log, \
                f"Expected stale lock warning in log:\n{log}"
        finally:
            lock_path.unlink(missing_ok=True)

    def test_duplicate_run_is_skipped(self, tmp_path):
        """If a live PID is in the lock, script should exit 0 without running claude."""
        # Plant our own PID as the "running" instance
        lock_path = Path("/tmp/claude-daemon.lock")
        lock_path.write_text(str(os.getpid()))
        try:
            bin_dir = fake_claude_bin(tmp_path, exit_code=0)
            result = run_script(base_env(tmp_path, bin_dir))
            assert result.returncode == 0
            log = read_log(tmp_path / "Library" / "Logs" / "claude-daemon")
            assert "SKIP" in log, f"Expected SKIP in log:\n{log}"
            # claude keepalive should NOT have been sent
            assert "Sending keepalive" not in log
        finally:
            lock_path.unlink(missing_ok=True)


# ── 5. Timeout mechanism ───────────────────────────────────────────────────────

class TestTimeout:
    def test_sigterm_fires_before_deadline(self, tmp_path):
        """A claude that sleeps forever should be killed within timeout + grace."""
        bin_dir = fake_claude_bin(tmp_path, sleep_secs=120)
        timeout_secs = 3
        env = base_env(tmp_path, bin_dir, CLAUDE_TIMEOUT=str(timeout_secs))

        start = time.monotonic()
        result = run_script(env, timeout=timeout_secs + 15)
        elapsed = time.monotonic() - start

        # Script must complete well before the fake claude's 120s sleep
        assert elapsed < timeout_secs + 12, \
            f"Script took {elapsed:.1f}s — timeout not enforced"

    def test_timeout_logged(self, tmp_path):
        """TIMEOUT message must appear in log when deadline exceeded."""
        bin_dir = fake_claude_bin(tmp_path, sleep_secs=120)
        env = base_env(tmp_path, bin_dir, CLAUDE_TIMEOUT="3")
        run_script(env, timeout=20)
        log = read_log(tmp_path / "Library" / "Logs" / "claude-daemon")
        assert "TIMEOUT" in log, f"Expected TIMEOUT in log:\n{log}"

    def test_sigkill_fires_when_sigterm_ignored(self, tmp_path):
        """A claude that ignores SIGTERM must still be killed via SIGKILL within grace."""
        bin_dir = fake_claude_bin(tmp_path, sleep_secs=120, ignore_term=True)
        timeout_secs = 3
        env = base_env(tmp_path, bin_dir, CLAUDE_TIMEOUT=str(timeout_secs))

        start = time.monotonic()
        result = run_script(env, timeout=timeout_secs + 15)
        elapsed = time.monotonic() - start

        # SIGKILL grace is 5 s, so total ≤ timeout + 5 + buffer
        assert elapsed < timeout_secs + 10, \
            f"Script took {elapsed:.1f}s — SIGKILL not enforced"

    def test_sigkill_logged(self, tmp_path):
        bin_dir = fake_claude_bin(tmp_path, sleep_secs=120, ignore_term=True)
        env = base_env(tmp_path, bin_dir, CLAUDE_TIMEOUT="3")
        run_script(env, timeout=25)
        log = read_log(tmp_path / "Library" / "Logs" / "claude-daemon")
        assert "SIGKILL" in log, f"Expected SIGKILL in log:\n{log}"

    def test_fast_claude_not_killed(self, tmp_path):
        """A claude that finishes quickly must not trigger timeout."""
        bin_dir = fake_claude_bin(tmp_path, exit_code=0, sleep_secs=0)
        env = base_env(tmp_path, bin_dir, CLAUDE_TIMEOUT="10")
        run_script(env)
        log = read_log(tmp_path / "Library" / "Logs" / "claude-daemon")
        assert "TIMEOUT" not in log, f"Unexpected TIMEOUT in log:\n{log}"
        assert "SIGKILL" not in log


# ── 6. Process-group kill ──────────────────────────────────────────────────────

class TestProcessGroupKill:
    def test_child_processes_die_with_claude(self, tmp_path):
        """Claude's child processes (spawned by the fake) must not outlive the timeout."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        # Fake claude that spawns a grandchild sleep
        sentinel = tmp_path / "grandchild.pid"
        script = bin_dir / "claude"
        script.write_text(textwrap.dedent(f"""\
            #!/usr/bin/env bash
            sleep 120 &
            echo $! > {sentinel}
            wait
        """))
        script.chmod(0o755)

        env = base_env(tmp_path, bin_dir, CLAUDE_TIMEOUT="3")
        run_script(env, timeout=20)

        # Give the OS a moment to reap
        time.sleep(1)

        if sentinel.exists():
            grandchild_pid = int(sentinel.read_text().strip())
            try:
                os.kill(grandchild_pid, 0)
                pytest.fail(f"Grandchild process {grandchild_pid} is still alive — process group not killed")
            except ProcessLookupError:
                pass  # correctly dead


# ── 7. Environment overrides ───────────────────────────────────────────────────

class TestEnvOverrides:
    def test_custom_timeout_respected(self, tmp_path):
        """CLAUDE_TIMEOUT=2 should fire faster than CLAUDE_TIMEOUT=10."""
        bin_dir = fake_claude_bin(tmp_path, sleep_secs=60)

        start = time.monotonic()
        run_script(base_env(tmp_path, bin_dir, CLAUDE_TIMEOUT="2"), timeout=15)
        fast = time.monotonic() - start

        assert fast < 10, f"Custom short timeout not respected ({fast:.1f}s)"

    def test_project_dir_logged(self, tmp_path):
        custom_dir = tmp_path / "myproject"
        custom_dir.mkdir()
        bin_dir = fake_claude_bin(tmp_path, exit_code=0)
        env = base_env(tmp_path, bin_dir, CLAUDE_PROJECT_DIR=str(custom_dir))
        run_script(env)
        log = read_log(tmp_path / "Library" / "Logs" / "claude-daemon")
        assert str(custom_dir) in log, f"CLAUDE_PROJECT_DIR not in log:\n{log}"

    def test_timeout_shown_in_log(self, tmp_path):
        bin_dir = fake_claude_bin(tmp_path, exit_code=0)
        env = base_env(tmp_path, bin_dir, CLAUDE_TIMEOUT="42")
        run_script(env, timeout=15)
        log = read_log(tmp_path / "Library" / "Logs" / "claude-daemon")
        assert "timeout: 42s" in log
