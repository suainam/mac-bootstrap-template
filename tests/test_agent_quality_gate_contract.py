from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_makefiles_expose_quality_gate_targets():
    template_makefile = read("Makefile")

    for target in (
        "repo-check",
        "machine-check",
        "quality-gate-pre-commit",
        "quality-gate-pre-push",
        "quality-gate-doctor",
    ):
        assert f"{target}:" in template_makefile
    root_makefile = ROOT.parent / "Makefile"
    if root_makefile.is_file():
        content = root_makefile.read_text(encoding="utf-8")
        for target in (
            "repo-check",
            "machine-check",
            "quality-gate-pre-commit",
            "quality-gate-pre-push",
            "quality-gate-doctor",
        ):
            assert f"{target}:" in content


def test_repo_and_machine_checks_split_pytest_markers():
    content = read("Makefile")
    repo_check = content.split("repo-check:", 1)[1].split("machine-check:", 1)[0]
    machine_check = content.split("machine-check:", 1)[1].split("ci:", 1)[0]

    assert "$(MAKE) pytest\n" in repo_check
    assert "pytest-all" not in repo_check
    assert "$(MAKE) pytest-machine" in machine_check


def test_pytest_targets_honor_python_override():
    content = read("Makefile")
    pytest_targets = content.split("pytest:", 1)[1].split("neat-freak-ci:", 1)[0]

    assert "$(PYTHON) -c 'import pytest_cov'" in pytest_targets
    assert "$(PYTHON) -m pytest" in pytest_targets
    assert ".venv/bin/python -m pytest" not in pytest_targets


def test_agent_configure_wires_codex_quality_gate_hooks():
    content = read("scripts/lib/agent-configure.sh")

    assert "Removed legacy quality gate prompt hooks from Codex hooks.json" in content
    assert "QUALITY GATE PRE-COMMIT" in content
    assert "QUALITY GATE PRE-PUSH" in content
    assert "removeUserPromptHooks" in content


def test_agent_doctor_verifies_quality_gate_assets():
    content = read("scripts/agent-doctor.sh")

    assert "quality gate manifest" in content
    assert "agent-quality-gate.sh" in content
    assert "knowledge-record-gate.sh" in content
    assert "neat-freak-gate.sh" in content
    assert "no legacy Codex quality gate prompt hooks" in content


def test_repo_managed_git_hooks_delegate_to_quality_gate_runner():
    pre_commit = read("agent/quality-gates/hooks/pre-commit")
    pre_push = read("agent/quality-gates/hooks/pre-push")
    installer = read("scripts/install-agent-tooling.sh")

    assert "agent-quality-gate.sh pre-commit" in pre_commit
    assert "agent-quality-gate.sh pre-push" in pre_push
    assert "core.hooksPath" in installer
    assert "template/agent/quality-gates/hooks" in installer
