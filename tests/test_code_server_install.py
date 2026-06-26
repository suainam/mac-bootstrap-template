import os
import subprocess
from pathlib import Path


INSTALL_SCRIPT = Path(__file__).resolve().parents[1] / "infra" / "code-server" / "install.sh"


def test_code_server_install_requires_host():
    result = subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        capture_output=True,
        text=True,
        env={**os.environ, "CODE_SERVER_HOST": "", "MAC_BOOTSTRAP_PRIVATE_DIR": ""},
    )
    assert result.returncode == 1
    assert "CODE_SERVER_HOST is required" in result.stderr


def test_code_server_install_reads_private_overlay_env(tmp_path):
    private_dir = tmp_path / "private"
    env_dir = private_dir / "infra" / "code-server"
    env_dir.mkdir(parents=True)
    (env_dir / "env.sh").write_text(
        'CODE_SERVER_HOST="bastion-mux"\nCODE_SERVER_DIR="/srv/from-private"\n',
        encoding="utf-8",
    )

    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    (fakebin / "ssh").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "-O" ] && [ "${2:-}" = "check" ]; then
  exit 0
fi
if [ "${1:-}" = "bastion-mux" ] && [[ "${2:-}" == *"docker inspect code-server"* ]]; then
  printf "/srv/from-label"
  exit 0
fi
exit 0
""",
        encoding="utf-8",
    )
    (fakebin / "scp").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (fakebin / "ssh").chmod(0o755)
    (fakebin / "scp").chmod(0o755)

    result = subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "MAC_BOOTSTRAP_PRIVATE_DIR": str(private_dir),
            "PATH": f"{fakebin}:{os.environ['PATH']}",
            "HOME": str(tmp_path / "home"),
            "CODE_SERVER_HOST": "",
            "CODE_SERVER_DIR": "",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "Deploy code-server config to bastion-mux" in result.stdout
    assert "Target: bastion-mux:/srv/from-private" in result.stdout
