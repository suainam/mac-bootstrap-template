"""Regression checks for tracked global npm packages and OpenWiki template wiring."""

import os
from pathlib import Path

from helpers import TEMPLATE, run


def read(*parts: str) -> str:
    path = os.path.join(TEMPLATE, *parts)
    return open(path, encoding="utf-8").read()


def test_npm_global_manifest_tracks_agent_clis_without_openwiki():
    content = read("agent", "npm-global-packages.txt")
    for package in [
        "@upstash/context7-mcp",
        "@waishnav/devspace",
        "codebase-memory-mcp",
        "context-mode",
        "reasonix",
    ]:
        assert package in content
    assert "openwiki" not in content


def test_install_npm_global_packages_script_uses_manifest_and_upgrade_mode():
    content = read("scripts", "install-npm-global-packages.sh")
    assert 'PACKAGES_FILE="$DIR/agent/npm-global-packages.txt"' in content
    assert 'npm -g ls --depth=0 --json' in content
    assert 'npm install -g "$pkg"' in content
    assert '--upgrade' in content
    assert 'make npm-packages' in content


def test_install_script_tolerates_nonzero_npm_ls_with_valid_json(tmp_path: Path):
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    log_path = tmp_path / "npm-install.log"
    npm_script = fakebin / "npm"
    npm_script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [ \"$1\" = \"-g\" ] && [ \"$2\" = \"ls\" ]; then\n"
        "  cat <<'JSON'\n"
        "{\"dependencies\":{\"@upstash/context7-mcp\":{},\"@waishnav/devspace\":{},\"codebase-memory-mcp\":{},\"context-mode\":{},\"reasonix\":{}}}\n"
        "JSON\n"
        "  exit 1\n"
        "fi\n"
        "if [ \"$1\" = \"install\" ] && [ \"$2\" = \"-g\" ]; then\n"
        f"  echo \"$3\" >> \"{log_path}\"\n"
        "  exit 0\n"
        "fi\n"
        "echo \"unexpected npm args: $*\" >&2\n"
        "exit 2\n",
        encoding="utf-8",
    )
    npm_script.chmod(0o755)

    script = os.path.join(TEMPLATE, "scripts", "install-npm-global-packages.sh")
    env_path = f'{fakebin}:{os.environ["PATH"]}'
    out, err, rc = run(f'PATH="{env_path}" "{script}" --yes')
    assert rc == 0, err
    assert "SKIP: reasonix already installed" in out
    assert not log_path.exists(), out


def test_makefile_exposes_npm_package_targets_and_shell_check():
    content = read("Makefile")
    assert 'npm-packages:' in content
    assert './scripts/install-npm-global-packages.sh --yes' in content
    assert 'npm-packages-upgrade:' in content
    assert './scripts/install-npm-global-packages.sh --yes --upgrade' in content
    assert '$(MAKE) syntax-check' in content
    assert 'openwiki-distribute:' not in content
    assert 'distribute-openwiki-workflow.sh' not in content


def test_agent_doctor_checks_tracked_npm_globals():
    content = read("scripts", "agent-doctor.sh")
    assert 'npm-global-packages.txt' in content
    assert "npm -g ls --depth=0 --json 2>/dev/null || true" in content
    assert "MISS npm globals prerequisite" in content
    assert 'MISS npm global $package (run: make npm-packages)' in content
    assert 'OK   npm global $package' in content


def test_openwiki_distribution_files_are_removed_and_decision_doc_exists():
    assert not os.path.exists(os.path.join(TEMPLATE, "agent", "openwiki-repos.jsonc"))
    assert not os.path.exists(
        os.path.join(TEMPLATE, "scripts", "distribute-openwiki-workflow.sh")
    )
    decision = read("docs", "openwiki-boundary-decision.md")
    assert "不再接入 OpenWiki" in decision
    assert "AGENTS.md" in decision
    assert "README.md" in decision


def test_npm_global_manifest_documents_bare_package_names_only():
    manifest = read("agent", "npm-global-packages.txt")
    assert "bare npm package name" in manifest
    assert "no version pins or aliases" in manifest
