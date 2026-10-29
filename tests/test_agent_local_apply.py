import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def snapshot(root):
    return {
        str(p.relative_to(root)): ('link', os.readlink(p)) if p.is_symlink()
        else ('file', hashlib.sha256(p.read_bytes()).hexdigest())
        for p in root.rglob('*') if p.is_file() or p.is_symlink()
    }


def test_local_apply_is_offline_and_repeatable(tmp_path):
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required by the agent installer')
    checkout = tmp_path / 'checkout'
    shutil.copytree(ROOT / 'scripts', checkout / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(ROOT / 'agent', checkout / 'agent')
    registry = checkout / 'agent-skills/registry'
    registry.mkdir(parents=True)
    (registry / 'sources.jsonc').write_text(json.dumps({
        'version': 2,
        'sources': {'fixture': {'type': 'internal', 'scope': 'global',
                                'agents': ['codex'], 'skills': {'example': {}}}},
    }))
    (registry / 'targets.jsonc').write_text(json.dumps({
        'version': 1, 'targets': {'codex': {'path': '~/.codex/skills',
                                             'format': 'directory', 'strategy': 'symlink'}},
    }))
    skill = checkout / 'agent-skills/local/example/SKILL.md'
    skill.parent.mkdir(parents=True)
    skill.write_text('# Fixture skill\n')
    home = tmp_path / 'home'
    home.mkdir()
    private = tmp_path / 'private/agent'
    private.mkdir(parents=True)
    (private / 'context7.runtime.jsonc').write_text('{"api_key":"REPLACE_ME"}\n')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'python3').symlink_to(sys.executable)
    (bin_dir / 'node').symlink_to(node)
    calls = tmp_path / 'calls'
    for name in ('npm', 'npx', 'claude', 'context-mode', 'git', 'curl', 'wget',
                 'brew', 'rtk', 'codex', 'opencode', 'agy', 'reasonix', 'omp',
                 'codebase-memory-mcp', 'context7-mcp'):
        stub = bin_dir / name
        stub.write_text('#!/bin/sh\necho "' + name + ' $*" >> "$CALLS"\n' +
                        ('exit 0\n' if name == 'rtk' else 'exit 97\n'))
        stub.chmod(0o755)
    (home / '.codex').mkdir()
    (home / '.codex/RTK.md').write_text('RTK reference\n')
    opencode = home / '.config/opencode/opencode.json'
    opencode.parent.mkdir(parents=True)
    opencode.write_text('{}\n')
    env = {'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config'),
           'PATH': f'{bin_dir}:/usr/bin:/bin', 'PYTHON': sys.executable,
           'MAC_BOOTSTRAP_PRIVATE_DIR': str(private.parent), 'CALLS': str(calls)}

    def apply(*args):
        return subprocess.run([str(checkout / 'scripts/install-agent-tooling.sh'), *args],
                              env=env, cwd=checkout, text=True, capture_output=True)

    first = apply('--local-apply')
    assert first.returncode == 0, first.stdout + first.stderr
    assert (home / '.codex/AGENTS.md').is_file()
    assert (home / '.codex/skills/example').is_symlink()
    assert './plugins/rtk.ts' in opencode.read_text()
    files = snapshot(home)
    checkout_files = snapshot(checkout)
    second = apply('--local-apply')
    assert second.returncode == 0, second.stdout + second.stderr
    assert files == snapshot(home)
    assert checkout_files == snapshot(checkout)
    invocations = calls.read_text().splitlines() if calls.exists() else []
    assert invocations == ['rtk init --global --auto-patch', 'rtk init --global --codex'] * 2

    full = apply('--configure', '--dry-run')
    assert full.returncode == 0, full.stdout + full.stderr
    for operation in ('ensure-bundles', 'replace @opencode-ai/plugin', 'claude plugin install',
                      'context-mode upgrade', 'npx -y github:'):
        assert operation in full.stdout
