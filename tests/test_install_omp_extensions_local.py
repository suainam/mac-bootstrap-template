"""Tests for `install-omp-extensions.sh` local-source mode — TB-01.

The npm path must not change: a regression there would silently repoint every
machine's extension at a different version. So most of these tests pin the
existing behaviour and add the local-source case alongside it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "install-omp-extensions.sh"

pytestmark = pytest.mark.skipif(
    # `shutil.which`, not `subprocess.run(["command", "-v", "jq"])`. `command` is
    # a shell builtin; it happens to exist as a real executable at /usr/bin/command
    # on macOS, so the exec form passed locally while raising FileNotFoundError at
    # collection time on Linux CI, taking the whole run down before any test ran.
    shutil.which("jq") is None,
    reason="jq is required by the installer under test",
)


def _fake_omp(tmp_path: Path, installed_version: str = "0.1.1") -> Path:
    """Create a stub `omp` whose plugin list reports `installed_version`."""
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    stub = bindir / "omp"
    stub.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            if [[ "$1" == "plugin" && "$2" == "list" ]]; then
              echo '{{"npm":[{{"name":"@narumitw/pi-typesafe","version":"{installed_version}"}}]}}'
              exit 0
            fi
            if [[ "$1" == "install" ]]; then
              echo "installed $2"
              exit 0
            fi
            exit 0
            """
        )
    )
    stub.chmod(0o755)
    return bindir


def _repo(tmp_path: Path, extensions: list[dict], *, settings: tuple[str, ...] = ()) -> Path:
    """Lay out a minimal repository the installer can run against."""
    root = tmp_path / "repo"
    (root / "agent" / "omp").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    (root / "agent" / "omp" / "extensions.json").write_text(
        json.dumps({"version": 1, "extensions": extensions}, indent=2)
    )
    for name in settings:
        (root / "agent" / "omp" / name).write_text("{}\n")
    script = root / "scripts" / "install-omp-extensions.sh"
    script.write_text(SCRIPT.read_text(encoding="utf-8"))
    script.chmod(0o755)
    return root


def _run(repo: Path, agent_dir: Path, bindir: Path, *args: str):
    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["PI_CODING_AGENT_DIR"] = str(agent_dir)
    return subprocess.run(
        [str(repo / "scripts" / "install-omp-extensions.sh"), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


# --------------------------------------------------------------------------
# Regression: the existing npm path
# --------------------------------------------------------------------------


def test_existing_npm_entry_is_byte_identical(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        [
            {
                "package": "@narumitw/pi-typesafe",
                "version": "0.1.1",
                "settings": "pi-typesafe.json",
            }
        ],
        settings=("pi-typesafe.json",),
    )
    agent_dir = tmp_path / "agent"
    bindir = _fake_omp(tmp_path)

    result = _run(repo, agent_dir, bindir, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "Already installed @narumitw/pi-typesafe@0.1.1" in result.stdout
    assert "Would link" in result.stdout
    assert not agent_dir.exists() or not list(agent_dir.rglob("*.json"))


def test_version_mismatch_triggers_install(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path, [{"package": "@narumitw/pi-typesafe", "version": "0.2.0"}]
    )
    agent_dir = tmp_path / "agent"
    result = _run(repo, agent_dir, _fake_omp(tmp_path, installed_version="0.1.1"))
    assert result.returncode == 0, result.stderr
    assert "installed @narumitw/pi-typesafe@0.2.0" in result.stdout


# --------------------------------------------------------------------------
# Local source mode
# --------------------------------------------------------------------------


def _local_entry(target: str = "dispatch-omp.ts") -> dict:
    return {
        "kind": "local",
        "package": "multiplexer/herdr-dispatch/omp/index.ts",
        "target": target,
    }


def test_local_source_is_symlinked(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [_local_entry()])
    source = repo / "multiplexer" / "herdr-dispatch" / "omp"
    source.mkdir(parents=True)
    (source / "index.ts").write_text("export default function () {}\n")

    agent_dir = tmp_path / "agent"
    result = _run(repo, agent_dir, _fake_omp(tmp_path))

    assert result.returncode == 0, result.stderr
    link = agent_dir / "extensions" / "dispatch-omp.ts"
    assert link.is_symlink()
    assert link.resolve() == (source / "index.ts").resolve()
    # A pure-local manifest must not need a registry round-trip.
    assert "omp install" not in result.stdout


def test_local_install_is_idempotent(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [_local_entry()])
    source = repo / "multiplexer" / "herdr-dispatch" / "omp"
    source.mkdir(parents=True)
    (source / "index.ts").write_text("export default function () {}\n")

    agent_dir = tmp_path / "agent"
    bindir = _fake_omp(tmp_path)
    assert _run(repo, agent_dir, bindir).returncode == 0

    link = agent_dir / "extensions" / "dispatch-omp.ts"
    first = link.lstat().st_ino

    assert _run(repo, agent_dir, bindir).returncode == 0
    assert link.is_symlink()
    assert link.lstat().st_ino == first, "second run must not churn the link"
    assert not list(agent_dir.rglob("*.pre-mac-bootstrap"))


def test_local_target_defaults_to_basename(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        [{"kind": "local", "package": "multiplexer/herdr-dispatch/omp/brain-loop.ts"}],
    )
    source = repo / "multiplexer" / "herdr-dispatch" / "omp"
    source.mkdir(parents=True)
    (source / "brain-loop.ts").write_text("export default function () {}\n")

    agent_dir = tmp_path / "agent"
    assert _run(repo, agent_dir, _fake_omp(tmp_path)).returncode == 0
    assert (agent_dir / "extensions" / "brain-loop.ts").is_symlink()


def test_unscoped_package_without_kind_is_treated_as_local(tmp_path: Path) -> None:
    """Backwards-compatible inference for manifests that omit `kind`."""
    repo = _repo(tmp_path, [{"package": "multiplexer/herdr-dispatch/omp/index.ts"}])
    source = repo / "multiplexer" / "herdr-dispatch" / "omp"
    source.mkdir(parents=True)
    (source / "index.ts").write_text("export default function () {}\n")

    agent_dir = tmp_path / "agent"
    result = _run(repo, agent_dir, _fake_omp(tmp_path))
    assert result.returncode == 0, result.stderr
    assert (agent_dir / "extensions" / "index.ts").is_symlink()


def test_missing_local_source_is_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [_local_entry()])
    agent_dir = tmp_path / "agent"
    result = _run(repo, agent_dir, _fake_omp(tmp_path))
    assert result.returncode == 2
    assert "Missing local extension source" in result.stderr
    assert not (agent_dir / "extensions").exists()


def test_local_source_refuses_to_clobber_without_backup_consent(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [_local_entry()])
    source = repo / "multiplexer" / "herdr-dispatch" / "omp"
    source.mkdir(parents=True)
    (source / "index.ts").write_text("export default function () {}\n")

    agent_dir = tmp_path / "agent"
    link = agent_dir / "extensions" / "dispatch-omp.ts"
    link.parent.mkdir(parents=True)
    link.write_text("operator-owned content\n")
    (link.parent / "dispatch-omp.ts.pre-mac-bootstrap").write_text("older backup\n")

    result = _run(repo, agent_dir, _fake_omp(tmp_path))
    assert result.returncode == 2
    assert "Refusing to overwrite" in result.stderr
    # Operator content and the older backup both survive untouched.
    assert link.read_text() == "operator-owned content\n"
    assert (link.parent / "dispatch-omp.ts.pre-mac-bootstrap").read_text() == (
        "older backup\n"
    )


def test_local_source_backs_up_operator_file_once(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [_local_entry()])
    source = repo / "multiplexer" / "herdr-dispatch" / "omp"
    source.mkdir(parents=True)
    (source / "index.ts").write_text("export default function () {}\n")

    agent_dir = tmp_path / "agent"
    link = agent_dir / "extensions" / "dispatch-omp.ts"
    link.parent.mkdir(parents=True)
    link.write_text("operator content\n")

    assert _run(repo, agent_dir, _fake_omp(tmp_path)).returncode == 0
    assert link.is_symlink()
    assert (link.parent / "dispatch-omp.ts.pre-mac-bootstrap").read_text() == (
        "operator content\n"
    )


def test_local_dry_run_writes_nothing(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [_local_entry()])
    source = repo / "multiplexer" / "herdr-dispatch" / "omp"
    source.mkdir(parents=True)
    (source / "index.ts").write_text("export default function () {}\n")

    agent_dir = tmp_path / "agent"
    result = _run(repo, agent_dir, _fake_omp(tmp_path), "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "Would link" in result.stdout
    assert not agent_dir.exists()


def test_doctor_recognizes_plugin_extension_and_reports_baseline_status(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [_local_entry()])
    source = repo / "multiplexer" / "herdr-dispatch" / "omp"
    source.mkdir(parents=True)
    (source / "index.ts").write_text("export default function () {}\n")
    plugin = repo / "multiplexer" / "herdr-dispatch" / "bin" / "dispatch_plugin.py"
    plugin.parent.mkdir(parents=True)
    plugin.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    agent_dir = tmp_path / "agent"
    bindir = _fake_omp(tmp_path)
    assert _run(repo, agent_dir, bindir).returncode == 0

    result = _run(repo, agent_dir, bindir, "--doctor")
    assert result.returncode == 0, result.stderr
    assert "OK   plugin entrypoint:" in result.stdout
    assert "OK   local extension dispatch-omp.ts" in result.stdout
    assert "certification baseline 18.5.0" in result.stdout
    assert "NOT VERIFIED" in result.stdout


def test_doctor_fails_when_local_extension_is_not_installed(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [_local_entry()])
    source = repo / "multiplexer" / "herdr-dispatch" / "omp"
    source.mkdir(parents=True)
    (source / "index.ts").write_text("export default function () {}\n")
    plugin = repo / "multiplexer" / "herdr-dispatch" / "bin" / "dispatch_plugin.py"
    plugin.parent.mkdir(parents=True)
    plugin.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    result = _run(repo, tmp_path / "agent", _fake_omp(tmp_path), "--doctor")
    assert result.returncode == 1
    assert "MISS local extension dispatch-omp.ts" in result.stdout


def test_local_entry_may_carry_settings(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        [{**_local_entry(), "settings": "dispatch.json"}],
        settings=("dispatch.json",),
    )
    source = repo / "multiplexer" / "herdr-dispatch" / "omp"
    source.mkdir(parents=True)
    (source / "index.ts").write_text("export default function () {}\n")

    agent_dir = tmp_path / "agent"
    assert _run(repo, agent_dir, _fake_omp(tmp_path)).returncode == 0
    assert (agent_dir / "extensions" / "dispatch-omp.ts").is_symlink()
    assert (agent_dir / "dispatch.json").is_symlink()


# --------------------------------------------------------------------------
# Preconditions
# --------------------------------------------------------------------------


def test_invalid_manifest_exits_2(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [])
    (repo / "agent" / "omp" / "extensions.json").write_text('{"version": 2}')
    result = _run(repo, tmp_path / "agent", _fake_omp(tmp_path))
    assert result.returncode == 2
    assert "Invalid OMP extension manifest" in result.stderr


def test_missing_omp_exits_2(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [_local_entry()])
    # Keep a shell-capable PATH (the shebang needs bash) but hide jq and omp.
    thin = tmp_path / "thin-bin"
    thin.mkdir()
    for tool in ("bash", "env", "sed", "basename", "dirname", "cat",
                 "mkdir", "rm", "mv", "ln", "readlink", "command"):
        found = shutil.which(tool)
        if found:
            (thin / tool).symlink_to(found)
    env = dict(os.environ)
    env["PATH"] = str(thin)
    env["PI_CODING_AGENT_DIR"] = str(tmp_path / "agent")
    result = subprocess.run(
        [str(repo / "scripts" / "install-omp-extensions.sh")],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 2
    assert "Missing required command" in result.stderr


def test_repository_manifest_is_still_valid() -> None:
    """The shipped manifest must keep parsing under the new jq program."""
    manifest = REPO_ROOT / "agent" / "omp" / "extensions.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    for entry in payload["extensions"]:
        assert entry["package"], entry
        if entry.get("kind") == "local":
            assert not entry["package"].startswith("@"), entry
        else:
            assert entry["version"], entry