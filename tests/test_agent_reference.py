"""The checked reference must follow the manifest, including after edits."""
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/agent-reference.py"


def invoke(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)


def test_repository_reference_is_current():
    result = invoke("--check")
    assert result.returncode == 0, result.stderr


def test_manifest_change_requires_reference_update(tmp_path):
    manifest = tmp_path / "manifest.json"
    readme = tmp_path / "README.md"
    data = json.loads((ROOT / "agent/agent-manifest.json").read_text())
    manifest.write_text(json.dumps(data))
    readme.write_text((ROOT / "agent/README.md").read_text())
    data["canonical"]["rules_file"] = "agent/rules/changed.md"
    manifest.write_text(json.dumps(data))
    args = ["--manifest", manifest, "--readme", readme]
    assert invoke("--check", *args).returncode != 0
    assert invoke("--write", *args).returncode == 0
    assert "agent/rules/changed.md" in readme.read_text()
    assert invoke("--check", *args).returncode == 0
    before = readme.read_bytes()
    assert invoke("--write", *args).returncode == 0
    assert readme.read_bytes() == before


def test_missing_markers_fail_without_rewriting(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("User content\n")
    assert invoke("--write", "--readme", readme).returncode != 0
    assert readme.read_text() == "User content\n"
