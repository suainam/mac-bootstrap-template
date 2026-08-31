import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "net-tune-macos.sh"


def test_save_profile_rounds_fractional_probe_rtt(tmp_path: Path) -> None:
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "ping").write_text(
        "#!/bin/sh\nprintf '%s\\n' 'round-trip min/avg/max/stddev = 5.598/5.598/5.598/0.000 ms'\n",
        encoding="utf-8",
    )
    (fake_bin / "ping").chmod(0o755)
    (fake_bin / "bc").write_text("#!/bin/sh\nprintf '0\\n'\n", encoding="utf-8")
    (fake_bin / "bc").chmod(0o755)

    env = os.environ.copy()
    env.update(HOME=str(home), PATH=f"{fake_bin}:{env['PATH']}")
    result = subprocess.run(
        ["bash", str(SCRIPT), "save", "office"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    profile_file = home / ".config" / "mac-bootstrap" / "net-profiles.json"
    profiles = json.loads(profile_file.read_text(encoding="utf-8"))
    assert profiles["profiles"]["office"]["target_rtt_ms"] == 6
