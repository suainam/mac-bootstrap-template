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
    target = tmp_path / "AGENTS.md"
    rules = tmp_path / "12-rules.md"
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
    assert "personal-default" in content
    assert "@/legacy/12-rules.md" not in content
    assert content.index("canonical-rule-sentinel") < content.index("personal-default")


def test_codex_instruction_generation_creates_missing_global_file(tmp_path: Path):
    target = tmp_path / "missing" / "AGENTS.md"
    rules = tmp_path / "12-rules.md"
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
    target = tmp_path / "AGENTS.md"
    rules = tmp_path / "12-rules.md"
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


def test_common_rules_have_exactly_twelve_general_rules():
    content = (Path(TEMPLATE) / "agent" / "rules" / "12-rules.md").read_text()
    headings = [line for line in content.splitlines() if line.startswith("### Rule ")]

    assert len(headings) == 12
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
