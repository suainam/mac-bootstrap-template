import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_patrol(extra_env=None, args=None):
    env = {
        **os.environ,
        "SYSTEM_PATROL_SKIP_LOG_STORM": "true",
        **(extra_env or {}),
    }
    cmd = [str(ROOT / "scripts" / "system-patrol.sh")] + (args or [])
    return subprocess.run(cmd, env=env, capture_output=True, text=True)


def test_system_patrol_healthy_exit(tmp_path):
    logs_dir = tmp_path / "Logs"
    logs_dir.mkdir()
    diag_dir = tmp_path / "Diag"
    diag_dir.mkdir()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    launchctl = fake_bin / "launchctl"
    launchctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launchctl.chmod(0o755)

    df_cmd = fake_bin / "df"
    df_cmd.write_text("#!/bin/sh\nprintf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n/dev/disk1 100 50 50 50%% /\\n'\n", encoding="utf-8")
    df_cmd.chmod(0o755)

    res = run_patrol(
        extra_env={
            "SYSTEM_PATROL_LOGS_DIR": str(logs_dir),
            "SYSTEM_PATROL_DIAG_USER": str(diag_dir),
            "SYSTEM_PATROL_DIAG_SYSTEM": str(diag_dir),
            "SYSTEM_PATROL_LAUNCHCTL_CMD": str(launchctl),
            "SYSTEM_PATROL_DF_CMD": str(df_cmd),
        }
    )
    assert res.returncode == 0
    assert "System patrol: all checks passed. System healthy." in res.stdout


def test_system_patrol_auto_rotates_large_log(tmp_path):
    logs_dir = tmp_path / "Logs"
    logs_dir.mkdir()
    diag_dir = tmp_path / "Diag"
    diag_dir.mkdir()

    large_log = logs_dir / "test-runaway.log"
    # Write 3000 lines of data (~1.5 MB)
    large_log.write_text("log line content here\n" * 70000, encoding="utf-8")
    initial_size = large_log.stat().st_size
    assert initial_size > 1048576

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    launchctl = fake_bin / "launchctl"
    launchctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launchctl.chmod(0o755)

    df_cmd = fake_bin / "df"
    df_cmd.write_text("#!/bin/sh\nprintf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n/dev/disk1 100 50 50 50%% /\\n'\n", encoding="utf-8")
    df_cmd.chmod(0o755)

    # Use 1MB threshold so the file is rotated
    res = run_patrol(
        extra_env={
            "SYSTEM_PATROL_LOGS_DIR": str(logs_dir),
            "SYSTEM_PATROL_DIAG_USER": str(diag_dir),
            "SYSTEM_PATROL_DIAG_SYSTEM": str(diag_dir),
            "SYSTEM_PATROL_MAX_LOG_MB": "1",
            "SYSTEM_PATROL_LAUNCHCTL_CMD": str(launchctl),
            "SYSTEM_PATROL_DF_CMD": str(df_cmd),
        }
    )
    assert res.returncode == 0
    assert "Auto-rotated test-runaway.log" in res.stdout

    # Verify rotated file has ~2000 lines and is significantly smaller
    rotated_lines = len(large_log.read_text(encoding="utf-8").splitlines())
    assert rotated_lines == 2000
    assert large_log.stat().st_size < initial_size


def test_system_patrol_dry_run_preserves_file(tmp_path):
    logs_dir = tmp_path / "Logs"
    logs_dir.mkdir()
    diag_dir = tmp_path / "Diag"
    diag_dir.mkdir()

    large_log = logs_dir / "test-runaway.log"
    content = "log line content here\n" * 70000
    large_log.write_text(content, encoding="utf-8")
    orig_size = large_log.stat().st_size

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    launchctl = fake_bin / "launchctl"
    launchctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launchctl.chmod(0o755)

    df_cmd = fake_bin / "df"
    df_cmd.write_text("#!/bin/sh\nprintf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n/dev/disk1 100 50 50 50%% /\\n'\n", encoding="utf-8")
    df_cmd.chmod(0o755)

    res = run_patrol(
        extra_env={
            "SYSTEM_PATROL_LOGS_DIR": str(logs_dir),
            "SYSTEM_PATROL_DIAG_USER": str(diag_dir),
            "SYSTEM_PATROL_DIAG_SYSTEM": str(diag_dir),
            "SYSTEM_PATROL_MAX_LOG_MB": "1",
            "SYSTEM_PATROL_LAUNCHCTL_CMD": str(launchctl),
            "SYSTEM_PATROL_DF_CMD": str(df_cmd),
        },
        args=["--dry-run"],
    )
    assert res.returncode == 0
    assert "Would rotate test-runaway.log" in res.stdout
    assert large_log.stat().st_size == orig_size


def test_system_patrol_detects_crash_and_service_faults(tmp_path):
    logs_dir = tmp_path / "Logs"
    logs_dir.mkdir()
    diag_dir = tmp_path / "Diag"
    diag_dir.mkdir()

    # Create mock crash report
    crash_file = diag_dir / "test_app-2026-10-08.ips"
    crash_file.write_text("{}", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    launchctl = fake_bin / "launchctl"
    # Mock launchctl returning 1 failed user service
    launchctl.write_text(
        "#!/bin/sh\nprintf '1234\\t1\\tio.local.mac-bootstrap.bad-service\\n'\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)

    df_cmd = fake_bin / "df"
    df_cmd.write_text("#!/bin/sh\nprintf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n/dev/disk1 100 95 5 95%% /\\n'\n", encoding="utf-8")
    df_cmd.chmod(0o755)

    notify_log = tmp_path / "notify.log"
    notify_cmd = fake_bin / "fake-notify"
    notify_cmd.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{notify_log}'\n",
        encoding="utf-8",
    )
    notify_cmd.chmod(0o755)

    res = run_patrol(
        extra_env={
            "SYSTEM_PATROL_LOGS_DIR": str(logs_dir),
            "SYSTEM_PATROL_DIAG_USER": str(diag_dir),
            "SYSTEM_PATROL_DIAG_SYSTEM": str(diag_dir),
            "SYSTEM_PATROL_LAUNCHCTL_CMD": str(launchctl),
            "SYSTEM_PATROL_DF_CMD": str(df_cmd),
            "SYSTEM_PATROL_NOTIFY_CMD": str(notify_cmd),
        },
        args=["--notify", "--strict"],
    )
    # Under --strict, exits with 1 when faults found
    assert res.returncode == 1
    assert "System Patrol Alerts (3)" in res.stderr
    assert "test_app-2026-10-08.ips" in res.stderr
    assert "io.local.mac-bootstrap.bad-service" in res.stderr
    assert "Root volume usage is critically high (95%)" in res.stderr

    # Check notification was dispatched
    assert notify_log.exists()
    assert "display notification" in notify_log.read_text(encoding="utf-8")
