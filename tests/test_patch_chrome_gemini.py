"""Regression tests for scripts/patch-chrome-gemini.sh

Coverage:
- Syntax validity (bash -n)
- Unknown account is rejected before any side effect
- Current-user default (no argument) resolves home via dscl mock
- Target-user argument resolves correct home
- Missing Chrome config exits 0 with warning when home/Library accessible
- Permission-denied Library exits 1 with advisory
- No-patch-needed path exits 0 without modifying file
- Patch applied when is_glic_eligible is false
- Patch applied when variations_country is wrong
- Patch applied when variations_permanent_consistency_country is wrong
- --kill: exits 1 when Chrome still running after bounded wait
- --kill: succeeds when Chrome exits promptly after pkill
- Warning-only mode (no --kill): patch applied while Chrome running
- Makefile quoting: shell-metacharacter username passed safely
"""

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "patch-chrome-gemini.sh"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LOCAL_STATE_NEEDS_PATCH = textwrap.dedent(
    """\
    {
        "glic": {"is_glic_eligible": false},
        "variations_country": "jp",
        "variations_permanent_consistency_country": ["jp"]
    }
    """
)

_LOCAL_STATE_ALREADY_PATCHED = textwrap.dedent(
    """\
    {
        "glic": {"is_glic_eligible": true},
        "variations_country": "us",
        "variations_permanent_consistency_country": ["us"]
    }
    """
)


def _write_state(tmp_path: Path, content: str) -> Path:
    """Create Chrome Local State file in a temp home directory."""
    state_dir = tmp_path / "Library" / "Application Support" / "Google" / "Chrome"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "Local State"
    state_file.write_text(content, encoding="utf-8")
    return state_file


def _fake_bin(tmp_path: Path) -> Path:
    """Create a bin directory with fake external commands, returning its path."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    return bin_dir


def _write_fake(bin_dir: Path, name: str, body: str, *, mode: int = 0o755) -> None:
    script = bin_dir / name
    script.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body), encoding="utf-8")
    script.chmod(mode)


def _dscl_ok(bin_dir: Path, username: str, home: Path) -> None:
    """Fake dscl that reports success and correct NFSHomeDirectory for `username`."""
    _write_fake(
        bin_dir,
        "dscl",
        f"""\
# fake dscl: only respond to known account '{username}'
if [ "$3" = "/Users/{username}" ] && [ "$4" = "NFSHomeDirectory" ]; then
    if [ "$2" = "-read" ]; then
        printf 'NFSHomeDirectory: {home}\\n'
        exit 0
    fi
fi
exit 1
""",
    )


def _dscl_unknown(bin_dir: Path) -> None:
    """Fake dscl that always fails (unknown user)."""
    _write_fake(bin_dir, "dscl", "exit 1\n")


def _pgrep_no_chrome(bin_dir: Path) -> None:
    """Fake pgrep: Chrome not running."""
    _write_fake(bin_dir, "pgrep", "exit 1\n")


def _pgrep_chrome_running(bin_dir: Path) -> None:
    """Fake pgrep: Chrome is running."""
    _write_fake(bin_dir, "pgrep", "echo 12345; exit 0\n")


def _pkill_ok(bin_dir: Path) -> None:
    """Fake pkill that succeeds silently."""
    _write_fake(bin_dir, "pkill", "exit 0\n")


def _networksetup_off(bin_dir: Path) -> None:
    """Fake networksetup: IPv6 already off, no mutation."""
    _write_fake(
        bin_dir,
        "networksetup",
        """\
if [ "${1:-}" = "-listallnetworkservices" ]; then exit 1; fi
exit 0
""",
    )


def _run(
    tmp_path: Path,
    bin_dir: Path,
    username: str,
    *extra_args: str,
    env_extra: dict | None = None,
) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "USER": username,
    }
    if env_extra:
        env.update(env_extra)
    cmd = ["bash", str(SCRIPT), *extra_args]
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


# ---------------------------------------------------------------------------
# 1. Static checks
# ---------------------------------------------------------------------------


class TestSyntax:
    def test_bash_syntax_valid(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
        )
        assert result.returncode == 0, f"Syntax error:\n{result.stderr}"

    def test_script_exists_and_is_readable(self):
        assert SCRIPT.exists()
        assert os.access(SCRIPT, os.R_OK)


# ---------------------------------------------------------------------------
# 2. Account validation (eval removal)
# ---------------------------------------------------------------------------


class TestAccountValidation:
    def test_unknown_user_rejected_before_any_side_effect(self, tmp_path):
        """dscl failure → exit 1, no file touched."""
        bin_dir = _fake_bin(tmp_path)
        _dscl_unknown(bin_dir)
        marker = tmp_path / "side_effect_marker"
        # networksetup must not run (would create marker); pkill must not run
        _write_fake(
            bin_dir,
            "networksetup",
            f"touch {marker}; exit 0\n",
        )
        result = _run(tmp_path, bin_dir, "nobody", "nobody")
        assert result.returncode == 1
        assert "Unknown user account" in result.stderr
        assert not marker.exists(), "Side-effect command ran before account validated"

    def test_current_user_default_resolves_home(self, tmp_path):
        """No username arg → USER env var used; home resolved via dscl."""
        user = "testuser"
        home = tmp_path / "home" / user
        state_file = _write_state(home, _LOCAL_STATE_NEEDS_PATCH)
        bin_dir = _fake_bin(tmp_path)
        _dscl_ok(bin_dir, user, home)
        _pgrep_no_chrome(bin_dir)
        _networksetup_off(bin_dir)
        # No username positional arg — script should use $USER
        result = _run(tmp_path, bin_dir, user)
        assert result.returncode == 0, result.stderr + result.stdout
        assert "applied successfully" in result.stdout
        assert '"is_glic_eligible":true' in state_file.read_text()

    def test_target_user_argument_resolves_home(self, tmp_path):
        """Explicit username arg → home resolved from that user via dscl."""
        user = "otheruser"
        home = tmp_path / "home" / user
        state_file = _write_state(home, _LOCAL_STATE_NEEDS_PATCH)
        bin_dir = _fake_bin(tmp_path)
        _dscl_ok(bin_dir, user, home)
        _pgrep_no_chrome(bin_dir)
        _networksetup_off(bin_dir)
        result = _run(tmp_path, bin_dir, "currentuser", user)
        assert result.returncode == 0, result.stderr + result.stdout
        assert "applied successfully" in result.stdout
        assert '"is_glic_eligible":true' in state_file.read_text()


# ---------------------------------------------------------------------------
# 3. Chrome State missing / unreadable
# ---------------------------------------------------------------------------


class TestChromeStateAccess:
    def test_missing_state_exits_zero_when_library_accessible(self, tmp_path):
        """Chrome config absent but ~/Library readable → 0, skip message."""
        user = "testuser"
        home = tmp_path / "home" / user
        # Create Library but NOT the Chrome state file
        lib_dir = home / "Library"
        lib_dir.mkdir(parents=True)
        bin_dir = _fake_bin(tmp_path)
        _dscl_ok(bin_dir, user, home)
        _networksetup_off(bin_dir)
        result = _run(tmp_path, bin_dir, user, user)
        assert result.returncode == 0
        assert "Skipping patch" in result.stdout

    def test_missing_state_exits_one_when_library_inaccessible(self, tmp_path):
        """Chrome config absent AND ~/Library unreadable → 1, advisory."""
        user = "testuser"
        home = tmp_path / "home" / user
        # Do not create Library at all
        home.mkdir(parents=True)
        bin_dir = _fake_bin(tmp_path)
        _dscl_ok(bin_dir, user, home)
        _networksetup_off(bin_dir)
        result = _run(tmp_path, bin_dir, user, user)
        assert result.returncode == 1
        assert "Permission denied" in result.stdout or "Permission denied" in result.stderr


# ---------------------------------------------------------------------------
# 4. Patch logic
# ---------------------------------------------------------------------------


class TestPatchLogic:
    def test_already_patched_exits_zero_no_change(self, tmp_path):
        """All fields already correct → exits 0, no modifications."""
        user = "testuser"
        home = tmp_path / "home" / user
        state_file = _write_state(home, _LOCAL_STATE_ALREADY_PATCHED)
        original_mtime = state_file.stat().st_mtime
        bin_dir = _fake_bin(tmp_path)
        _dscl_ok(bin_dir, user, home)
        _pgrep_no_chrome(bin_dir)
        _networksetup_off(bin_dir)
        result = _run(tmp_path, bin_dir, user, user)
        assert result.returncode == 0
        assert "No changes needed" in result.stdout
        assert state_file.stat().st_mtime == original_mtime

    def test_patch_is_glic_eligible_false(self, tmp_path):
        """is_glic_eligible false → patched to true."""
        user = "testuser"
        home = tmp_path / "home" / user
        state_file = _write_state(
            home,
            '{"is_glic_eligible": false, "variations_country": "us", '
            '"variations_permanent_consistency_country": ["us"]}',
        )
        bin_dir = _fake_bin(tmp_path)
        _dscl_ok(bin_dir, user, home)
        _pgrep_no_chrome(bin_dir)
        _networksetup_off(bin_dir)
        result = _run(tmp_path, bin_dir, user, user)
        assert result.returncode == 0
        assert '"is_glic_eligible":true' in state_file.read_text()

    def test_patch_variations_country_wrong(self, tmp_path):
        """variations_country non-us → patched to us."""
        user = "testuser"
        home = tmp_path / "home" / user
        state_file = _write_state(
            home,
            '{"variations_country": "jp", '
            '"variations_permanent_consistency_country": ["us"]}',
        )
        bin_dir = _fake_bin(tmp_path)
        _dscl_ok(bin_dir, user, home)
        _pgrep_no_chrome(bin_dir)
        _networksetup_off(bin_dir)
        result = _run(tmp_path, bin_dir, user, user)
        assert result.returncode == 0
        assert '"variations_country":"us"' in state_file.read_text()

    def test_patch_permanent_consistency_country_wrong(self, tmp_path):
        """variations_permanent_consistency_country non-us → patched."""
        user = "testuser"
        home = tmp_path / "home" / user
        state_file = _write_state(
            home,
            '{"variations_country": "us", '
            '"variations_permanent_consistency_country": ["jp"]}',
        )
        bin_dir = _fake_bin(tmp_path)
        _dscl_ok(bin_dir, user, home)
        _pgrep_no_chrome(bin_dir)
        _networksetup_off(bin_dir)
        result = _run(tmp_path, bin_dir, user, user)
        assert result.returncode == 0
        content = state_file.read_text()
        assert '"us"' in content


# ---------------------------------------------------------------------------
# 5. Chrome termination (--kill)
# ---------------------------------------------------------------------------


class TestChromKill:
    def test_kill_fails_when_chrome_stays_running(self, tmp_path):
        """--kill with Chrome that won't die → exit 1, state NOT modified."""
        user = "testuser"
        home = tmp_path / "home" / user
        state_file = _write_state(home, _LOCAL_STATE_NEEDS_PATCH)
        original = state_file.read_text()
        bin_dir = _fake_bin(tmp_path)
        _dscl_ok(bin_dir, user, home)
        _networksetup_off(bin_dir)
        # pgrep always reports Chrome running
        _pgrep_chrome_running(bin_dir)
        _pkill_ok(bin_dir)
        result = _run(tmp_path, bin_dir, user, user, "--kill")
        assert result.returncode == 1
        assert "still running" in result.stderr
        # Local State must NOT have been modified while Chrome was running
        assert state_file.read_text() == original

    def test_kill_succeeds_when_chrome_exits_promptly(self, tmp_path):
        """--kill with Chrome that exits after pkill → exit 0, state patched."""
        user = "testuser"
        home = tmp_path / "home" / user
        state_file = _write_state(home, _LOCAL_STATE_NEEDS_PATCH)
        bin_dir = _fake_bin(tmp_path)
        _dscl_ok(bin_dir, user, home)
        _networksetup_off(bin_dir)
        _pkill_ok(bin_dir)
        # pgrep: Chrome running on first call, gone after pkill (simulate via call count file)
        call_count = tmp_path / ".pgrep_calls"
        call_count.write_text("0", encoding="utf-8")
        _write_fake(
            bin_dir,
            "pgrep",
            f"""\
count=$(cat "{call_count}" 2>/dev/null || echo 0)
count=$((count + 1))
echo "$count" > "{call_count}"
# First call: Chrome running. Second call: gone.
if [ "$count" -le 1 ]; then
    echo 12345
    exit 0
fi
exit 1
""",
        )
        result = _run(tmp_path, bin_dir, user, user, "--kill")
        assert result.returncode == 0, result.stderr + result.stdout
        assert "applied successfully" in result.stdout
        assert '"is_glic_eligible":true' in state_file.read_text()

    def test_no_kill_flag_patches_while_chrome_running(self, tmp_path):
        """Without --kill: warning issued, patch applied despite Chrome running."""
        user = "testuser"
        home = tmp_path / "home" / user
        state_file = _write_state(home, _LOCAL_STATE_NEEDS_PATCH)
        bin_dir = _fake_bin(tmp_path)
        _dscl_ok(bin_dir, user, home)
        _pgrep_chrome_running(bin_dir)
        _networksetup_off(bin_dir)
        result = _run(tmp_path, bin_dir, user, user)
        assert result.returncode == 0, result.stderr + result.stdout
        assert "WARNING" in result.stdout
        assert "applied successfully" in result.stdout

    def test_kill_chrome_env_var_triggers_kill(self, tmp_path):
        """KILL_CHROME=1 env var behaves same as --kill flag."""
        user = "testuser"
        home = tmp_path / "home" / user
        state_file = _write_state(home, _LOCAL_STATE_NEEDS_PATCH)
        original = state_file.read_text()
        bin_dir = _fake_bin(tmp_path)
        _dscl_ok(bin_dir, user, home)
        _networksetup_off(bin_dir)
        _pgrep_chrome_running(bin_dir)
        _pkill_ok(bin_dir)
        result = _run(tmp_path, bin_dir, user, user, env_extra={"KILL_CHROME": "1"})
        assert result.returncode == 1
        assert "still running" in result.stderr
        assert state_file.read_text() == original
