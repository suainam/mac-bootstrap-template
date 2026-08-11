import json
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

def test_pre_push_uses_grouped_full_check_without_duplicate_doctor():
    manifest = json.loads(read("agent/quality-gates/manifest.jsonc"))
    assert manifest["events"]["pre-push"]["default_gates"] == [
        "classify",
        "neat-freak-apply",
        "make-check-parallel",
        "make-doctor-agent",
    ]


def test_trusted_git_hook_dispatcher_targets_are_explicit_migration_actions():
    template_makefile = read("Makefile")
    for target in (
        "quality-gate-hook-inventory",
        "quality-gate-hook-install",
        "quality-gate-hook-uninstall",
        "quality-gate-hook-doctor",
    ):
        assert f"{target}:" in template_makefile
    assert "scripts/agent_git_hook_dispatcher.py" in template_makefile

    installer = read("scripts/install-agent-tooling.sh")
    assert "agent_git_hook_dispatcher.py" not in installer
    assert "template/agent/quality-gates/hooks" in installer


def test_parallel_pytest_uses_bounded_default_worker_count():
    content = read("Makefile")
    assert "PYTEST_PARALLEL_WORKERS ?= 4" in content
    assert "PYTEST_PARALLEL_ARGS ?= -n $(PYTEST_PARALLEL_WORKERS) --dist loadfile" in content


def test_repo_and_machine_checks_split_pytest_markers():
    content = read("Makefile")
    repo_check = content.split("repo-check:", 1)[1].split("machine-check:", 1)[0]
    machine_check = content.split("machine-check:", 1)[1].split("ci:", 1)[0]

    assert "pytest-parallel" in repo_check
    assert "pytest-all" not in repo_check
    assert "$(MAKE) pytest-machine" in machine_check
    repo_check_serial = content.split("repo-check-serial:", 1)[1].split("repo-check-parallel:", 1)[0]
    assert "$(MAKE) pytest\n" in repo_check_serial
    repo_check_parallel = content.split("repo-check-parallel:", 1)[1].split("machine-check:", 1)[0]
    assert "repo-check" in repo_check_parallel


def test_pytest_targets_honor_python_override_without_leaking_it():
    content = read("Makefile")
    pytest_targets = content.split("pytest:", 1)[1].split("neat-freak-ci:", 1)[0]

    assert "$(PYTHON) -c 'import pytest_cov'" in pytest_targets
    assert "env -u PYTHON -u PYTHON_BIN $(PYTHON) -m pytest" in pytest_targets
    assert ".venv/bin/python -m pytest" not in pytest_targets


def test_shared_test_helper_uses_active_interpreter():
    content = read("tests/helpers.py")

    assert "PYTHON = sys.executable" in content
    assert 'PYTHON = os.path.join(TEMPLATE, ".venv", "bin", "python")' not in content


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
    assert Path(ROOT / "scripts" / "agent_git_hook_dispatcher.py").is_file()


def test_repo_managed_git_hooks_delegate_to_quality_gate_runner():
    pre_commit = read("agent/quality-gates/hooks/pre-commit")
    pre_push = read("agent/quality-gates/hooks/pre-push")
    installer = read("scripts/install-agent-tooling.sh")

    assert "agent-quality-gate.sh pre-commit" in pre_commit
    assert "agent-quality-gate.sh pre-push" in pre_push
    assert "core.hooksPath" in installer
    assert "template/agent/quality-gates/hooks" in installer
