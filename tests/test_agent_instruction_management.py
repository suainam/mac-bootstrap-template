"""Behavioral checks for generated Codex global instructions."""

import subprocess
import sys
from pathlib import Path

from helpers import TEMPLATE


def run_bash(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )


def test_replace_managed_block_preserves_user_content_on_both_sides(tmp_path: Path):
    target = tmp_path / "AGENTS.md"
    target.write_text(
        "user-before\n\n<!-- managed:start -->\nstale\n<!-- managed:end -->\n\nuser-after\n"
    )

    result = run_bash(
        f'''set -euo pipefail
run() {{ "$@"; }}
source "{TEMPLATE}/scripts/lib/agent-shared.sh"
replace_managed_block "{target}" '<!-- managed:start -->' '<!-- managed:end -->' $'<!-- managed:start -->\nfresh\n<!-- managed:end -->'
'''
    )

    assert result.returncode == 0, result.stderr
    assert target.read_text() == (
        "user-before\n\n<!-- managed:start -->\nfresh\n<!-- managed:end -->\n\nuser-after\n"
    )


def test_codex_instruction_generation_embeds_canonical_sources_and_is_idempotent(
    tmp_path: Path,
):
    target = tmp_path / "codex" / "AGENTS.md"
    target.parent.mkdir(parents=True)
    rules = tmp_path / "canonical" / "AGENTS.md"
    rules.parent.mkdir(parents=True)
    rtk = tmp_path / "RTK.md"
    target.write_text("personal-default\n\n@/legacy/12-rules.md\n")
    rules.write_text("## Core Operating Rules\n\ncanonical-rule-sentinel\n")
    rtk.write_text("# RTK\n\ncanonical-rtk-sentinel\n")

    script = f'''set -euo pipefail
run() {{ "$@"; }}
source "{TEMPLATE}/scripts/lib/agent-shared.sh"
source "{TEMPLATE}/scripts/lib/agent-configure.sh"
DRY_RUN=0
BOOTSTRAP="{TEMPLATE}"
CODEX_AGENTS="{target}"
RULES_FILE="{rules}"
CODEX_RTK="{rtk}"
ensure_codex_instructions
ensure_codex_instructions
'''
    result = run_bash(script)

    assert result.returncode == 0, result.stderr
    content = target.read_text()
    assert content.count("canonical-rule-sentinel") == 1
    assert content.count("canonical-rtk-sentinel") == 1
    assert "@RTK.md" not in content
    assert "personal-default" in content
    assert "@/legacy/12-rules.md" not in content
    assert content.index("canonical-rule-sentinel") < content.index("personal-default")

def test_codex_instruction_generation_creates_missing_global_file(tmp_path: Path):
    target = tmp_path / "missing" / "AGENTS.md"
    rules = tmp_path / "canonical" / "AGENTS.md"
    rules.parent.mkdir(parents=True)
    rtk = tmp_path / "RTK.md"
    rules.write_text("canonical-rule\n")
    rtk.write_text("canonical-rtk\n")

    result = run_bash(
        f'''set -euo pipefail
run() {{ "$@"; }}
source "{TEMPLATE}/scripts/lib/agent-shared.sh"
source "{TEMPLATE}/scripts/lib/agent-configure.sh"
DRY_RUN=0
BOOTSTRAP="{TEMPLATE}"
CODEX_AGENTS="{target}"
RULES_FILE="{rules}"
CODEX_RTK="{rtk}"
ensure_codex_instructions
'''
    )

    assert result.returncode == 0, result.stderr
    assert "canonical-rule" in target.read_text()

def test_instruction_verifier_rejects_tampered_managed_content(tmp_path: Path):
    target = tmp_path / "codex" / "AGENTS.md"
    target.parent.mkdir(parents=True)
    rules = tmp_path / "canonical" / "AGENTS.md"
    rules.parent.mkdir(parents=True)
    rtk = tmp_path / "RTK.md"
    rules.write_text("canonical-rule\n")
    rtk.write_text("canonical-rtk\n")
    command = [
        sys.executable,
        str(Path(TEMPLATE) / "scripts" / "agent-instructions.py"),
        "render",
        "--target",
        str(target),
        "--rules",
        str(rules),
        "--rtk",
        str(rtk),
    ]
    assert subprocess.run(command, check=False).returncode == 0
    target.write_text(target.read_text().replace("canonical-rule", "tampered-rule"))
    command[2] = "verify"

    assert subprocess.run(command, check=False).returncode == 1


def test_common_rules_stay_free_of_stale_references():
    content = (Path(TEMPLATE) / "agent" / "rules" / "AGENTS.md").read_text()

    assert "Occam Gate" in content
    assert "context-mode" not in content
    assert "Hammerspoon" not in content


def test_hammerspoon_tasks_route_to_local_reload_authority():
    rules = (Path(TEMPLATE) / "CLAUDE.md").read_text()
    guide = Path(TEMPLATE) / "desktop" / "hammerspoon" / "README.md"

    assert "desktop/hammerspoon/README.md" in rules
    assert guide.is_file()
    content = guide.read_text()
    assert "killall Hammerspoon && open -a Hammerspoon" in content
    assert 'hammerspoon -c "hs.reload()"' in content


def test_link_canonical_symlinks_creates_agents_md_and_claude_md_symlinks(tmp_path: Path):
    """link_canonical_symlinks must:
    1. Symlink AGENTS.md → canonical AGENTS.md
    2. Symlink CLAUDE.md → AGENTS.md  (compatibility alias)
    Both must be actual symlinks, not regular files.
    """
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    rules = tmp_path / "canonical" / "AGENTS.md"
    rules.parent.mkdir(parents=True)
    rules.write_text("## Core Operating Rules\n\nsentinel\n")
    agents_md = claude_dir / "AGENTS.md"
    claude_md = claude_dir / "CLAUDE.md"

    result = run_bash(
        f'''set -euo pipefail
run() {{ "$@"; }}
source "{TEMPLATE}/scripts/lib/agent-shared.sh"
source "{TEMPLATE}/scripts/lib/agent-configure.sh"
DRY_RUN=0
BOOTSTRAP="{TEMPLATE}"
RULES_FILE="{rules}"
ADVERSARIAL_REVIEW_SRC=""
CLAUDE_AGENTS_MD="{agents_md}"
CLAUDE_MD="{claude_md}"
CLAUDE_RULES_ADVERSARIAL_REVIEW=""
RULES_COMMON_SRC="{tmp_path}/src_common"
RULES_PYTHON_SRC="{tmp_path}/src_python"
CLAUDE_RULES_COMMON="{claude_dir}/rules/common"
CLAUDE_RULES_PYTHON="{claude_dir}/rules/python"
link_canonical_symlinks
'''
    )

    assert result.returncode == 0, result.stderr
    assert agents_md.is_symlink(), "AGENTS.md must be a symlink"
    assert agents_md.resolve() == rules.resolve()
    assert claude_md.is_symlink(), "CLAUDE.md must be a symlink (not a plain file)"
    assert claude_md.resolve() == agents_md.resolve()
    # Both must deliver the same content
    assert "sentinel" in agents_md.read_text()
    assert "sentinel" in claude_md.read_text()

def test_managed_symlink_replaces_only_legacy_generated_targets(tmp_path: Path):
    source = tmp_path / "rules" / "AGENTS.md"
    source.parent.mkdir()
    source.write_text("canonical\n")
    managed = tmp_path / "home" / ".gemini" / "GEMINI.md"
    managed.parent.mkdir(parents=True)
    managed.write_text("<!-- Generated by install-agent-tooling.sh -->\nlegacy\n")
    unmanaged = tmp_path / "home" / ".omp" / "agent" / "AGENTS.md"
    unmanaged.parent.mkdir(parents=True)
    unmanaged.write_text("personal OMP instruction\n")

    result = run_bash(
        f'''set -euo pipefail
run() {{ "$@"; }}
source "{TEMPLATE}/scripts/lib/agent-shared.sh"
DRY_RUN=0
write_managed_symlink "{source}" "{managed}"
write_managed_symlink "{source}" "{unmanaged}"
'''
    )

    assert result.returncode == 0, result.stderr
    assert managed.is_symlink()
    assert managed.resolve() == source.resolve()
    assert unmanaged.is_file() and not unmanaged.is_symlink()
    assert unmanaged.read_text() == "personal OMP instruction\n"


def test_managed_symlink_migrates_legacy_claude_reference_to_alias(tmp_path: Path):
    source = tmp_path / "rules" / "AGENTS.md"
    source.parent.mkdir()
    source.write_text("canonical\n")
    agents = tmp_path / ".claude" / "AGENTS.md"
    claude = tmp_path / ".claude" / "CLAUDE.md"
    agents.parent.mkdir()
    agents.symlink_to(source)
    claude.write_text("@" + "12-rules.md\n@" + "adversarial-review-gate.md\n@" + "RTK.md\n")

    result = run_bash(
        f'''set -euo pipefail
run() {{ "$@"; }}
source "{TEMPLATE}/scripts/lib/agent-shared.sh"
DRY_RUN=0
write_managed_symlink "{agents}" "{claude}"
'''
    )

    assert result.returncode == 0, result.stderr
    assert claude.is_symlink()
    assert claude.resolve() == agents.resolve()
    assert claude.read_text() == "canonical\n"

def test_managed_symlink_migrates_legacy_symlink_and_preserves_unrelated_symlink(tmp_path: Path):
    source = tmp_path / "rules" / "AGENTS.md"
    source.parent.mkdir(parents=True)
    source.write_text("canonical\n")

    old_rules = tmp_path / "old" / "agent" / "rules" / "12-rules.md"
    old_rules.parent.mkdir(parents=True)
    old_rules.write_text("old-12-rules\n")

    user_rules = tmp_path / "user" / "custom-rules.md"
    user_rules.parent.mkdir(parents=True)
    user_rules.write_text("user-rules\n")

    stale_symlink = tmp_path / "target_stale"
    stale_symlink.symlink_to(old_rules)

    unrelated_symlink = tmp_path / "target_user"
    unrelated_symlink.symlink_to(user_rules)

    result = run_bash(
        f'''set -euo pipefail
run() {{ "$@"; }}
source "{TEMPLATE}/scripts/lib/agent-shared.sh"
DRY_RUN=0
write_managed_symlink "{source}" "{stale_symlink}"
write_managed_symlink "{source}" "{unrelated_symlink}"
'''
    )

    assert result.returncode == 0, result.stderr
    assert stale_symlink.is_symlink()
    assert stale_symlink.resolve() == source.resolve()
    assert unrelated_symlink.is_symlink()
    assert unrelated_symlink.resolve() == user_rules.resolve()


def test_configure_global_instruction_links_distributes_symlinks_and_never_writes_workspace(
    tmp_path: Path,
):
    rules = tmp_path / "agent" / "rules" / "AGENTS.md"
    rules.parent.mkdir(parents=True)
    rules.write_text("canonical-rules-content\n")

    pi_agents = tmp_path / "home" / ".pi" / "agent" / "AGENTS.md"
    pi_agents.parent.mkdir(parents=True)
    pi_agents.write_text("user-authored pi rules\n")

    global_gemini = tmp_path / "home" / ".gemini" / "GEMINI.md"
    global_gemini.parent.mkdir(parents=True)
    global_gemini.write_text("<!-- Generated by install-agent-tooling.sh -->\nstale-gemini\n")

    omp_dir = tmp_path / "home" / ".omp" / "agent"
    omp_dir.mkdir(parents=True)
    omp_agents = omp_dir / "AGENTS.md"

    work_root = tmp_path / "work"
    repo_dir = work_root / "sample-repo"
    repo_dir.mkdir(parents=True)
    (repo_dir / "README.md").write_text("# Project\n")

    result = run_bash(
        f'''set -euo pipefail
run() {{ "$@"; }}
have() {{ return 0; }}
source "{TEMPLATE}/scripts/lib/agent-shared.sh"
source "{TEMPLATE}/scripts/lib/agent-configure.sh"
DRY_RUN=0
BOOTSTRAP="{TEMPLATE}"
RULES_FILE="{rules}"
GLOBAL_GEMINI="{global_gemini}"
PI_CODING_AGENT_DIR="{omp_dir}"
WORK_ROOT="{work_root}"
configure_global_instruction_links
'''
    )

    assert result.returncode == 0, result.stderr

    # Stale generated file migrated to symlink
    assert global_gemini.is_symlink()
    assert global_gemini.resolve() == rules.resolve()

    assert pi_agents.read_text() == "user-authored pi rules\n"

    # OMP global instruction symlink created
    assert omp_agents.is_symlink()
    assert omp_agents.resolve() == rules.resolve()

    # Absence of workspace writes: no instruction files generated in workspace
    assert not (work_root / "AGENTS.md").exists()
    assert not (work_root / "GEMINI.md").exists()
    assert not (work_root / "REASONIX.md").exists()
    assert sorted(p.name for p in repo_dir.iterdir()) == ["README.md"]


def test_shared_rules_do_not_require_host_specific_transport_or_runtime_settings():
    """One source reaches several hosts; unavailable APIs must not become mandatory."""
    content = (Path(TEMPLATE) / "agent" / "rules" / "AGENTS.md").read_text()
    for host_only in ("xd://", "proc://", "history://", "agent://", "task.maxRuntimeMs", "task.maxConcurrency", "agent.db", "memory_query"):
        assert host_only not in content, f"Host-specific contract leaked into shared rules: {host_only}"


def test_opencode_projection_updates_migrates_and_preserves_user_text(tmp_path: Path):
    target = tmp_path / 'AGENTS.md'
    target.write_text('<!-- Generated by install-agent-tooling.sh — do not edit manually -->\n'
                      'obsolete generated summary\n'
                      '<!-- opencode-user:start -->\nmy personal rule\n<!-- opencode-user:end -->\n')
    rules = tmp_path / 'rules.md'
    rules.write_text('shared rule one\n')
    rtk = tmp_path / 'RTK.md'
    rtk.write_text('rtk content\n')
    script = f'''set -euo pipefail
source "{TEMPLATE}/scripts/lib/agent-shared.sh"
source "{TEMPLATE}/scripts/lib/agent-configure.sh"
BOOTSTRAP="{TEMPLATE}"
RULES_FILE="{rules}"
OPENCODE_AGENTS="{target}"
RTK_SOURCE="{rtk}"
ADVERSARIAL_REVIEW_SRC=""
DRY_RUN=0
generate_opencode_agents_doc
'''
    assert run_bash(script).returncode == 0
    first = target.read_text()
    assert 'obsolete generated summary' not in first
    assert first.count('shared rule one') == 1
    assert first.count('rtk content') == 1
    assert '@RTK.md' not in first
    assert first.count('my personal rule') == 1
    assert run_bash(script).returncode == 0
    assert target.read_text() == first
    rules.write_text('shared rule two\n')
    assert run_bash(script).returncode == 0
    assert 'shared rule one' not in target.read_text()
    assert target.read_text().count('shared rule two') == 1
    assert target.read_text().count('my personal rule') == 1
    command = [sys.executable, str(Path(TEMPLATE) / 'scripts/agent-instructions.py'),
               'verify', '--host', 'opencode', '--target', str(target),
               '--rules', str(rules), '--rtk', str(rtk)]
    assert subprocess.run(command).returncode == 0
    target.write_text(target.read_text().replace('shared rule two', 'tampered'))
    assert subprocess.run(command).returncode == 1


def test_opencode_projection_preserves_unmanaged_file(tmp_path: Path):
    target = tmp_path / 'AGENTS.md'
    target.write_text('my existing instructions\n')
    rules = tmp_path / 'rules.md'
    rules.write_text('canonical\n')
    command = [sys.executable, str(Path(TEMPLATE) / 'scripts/agent-instructions.py'),
               'render', '--host', 'opencode', '--target', str(target), '--rules', str(rules)]
    assert subprocess.run(command).returncode == 0
    assert 'my existing instructions' in target.read_text()
