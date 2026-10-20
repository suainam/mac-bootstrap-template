"""Tern config distribution must adopt a fresh install without losing app edits."""
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "terminals/tern/install.sh"
TEMPLATE_SETTINGS = (SCRIPT.parent / "settings.json").read_bytes()


def run_tern(mode: str, env: Mapping[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), mode, *args],
        env=dict(env),
        capture_output=True,
        text=True,
        check=False,
    )


def test_first_sync_adopts_then_protects_in_app_edits(tmp_path: Path) -> None:
    live = tmp_path / "live"
    (live / "carly").mkdir(parents=True)
    settings = live / "settings.json"
    settings.write_text('{"font_size": 23}\n')
    memory = live / "carly/MEMORY.md"
    memory.write_text("learned runtime state")
    private = tmp_path / "private"
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "TERN_CONFIG_DIR": str(live),
        "MAC_BOOTSTRAP_PRIVATE_DIR": str(private),
    }

    adopted = run_tern("sync", env)
    assert adopted.returncode == 0, adopted.stderr
    assert settings.read_bytes() == TEMPLATE_SETTINGS
    assert [p.read_text() for p in live.glob("settings.json.bak.*")] == ['{"font_size": 23}\n']
    assert run_tern("status", env).returncode == 0

    settings.write_text('{"font_size": 24}\n')
    assert run_tern("status", env).returncode == 1
    captured = run_tern("capture", env)
    assert captured.returncode == 0, captured.stderr
    private_settings = private / "terminals/tern/settings.json"
    assert private_settings.read_text() == '{"font_size": 24}\n'
    assert not (private / "terminals/tern/carly/MEMORY.md").exists()

    settings.write_text('{"font_size": 25}\n')
    conflicted = run_tern("sync", env)
    assert conflicted.returncode == 1, "sync must not silently overwrite in-app edits"
    assert settings.read_text() == '{"font_size": 25}\n'

    forced = run_tern("sync", env, "--force")
    assert forced.returncode == 0, forced.stderr
    assert settings.read_bytes() == private_settings.read_bytes()
    assert '{"font_size": 25}\n' in [p.read_text() for p in live.glob("settings.json.bak.*")]
    assert memory.read_text() == "learned runtime state"
