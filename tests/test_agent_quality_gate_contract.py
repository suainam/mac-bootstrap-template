from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_makefiles_expose_quality_gate_targets():
    template_makefile = read("Makefile")
    root_makefile = (ROOT.parent / "Makefile").read_text(encoding="utf-8")

    for target in ("quality-gate-pre-commit", "quality-gate-pre-push", "quality-gate-doctor"):
        assert f"{target}:" in template_makefile
        assert f"{target}:" in root_makefile


def test_agent_configure_wires_codex_quality_gate_hooks():
    content = read("scripts/lib/agent-configure.sh")

    assert "QUALITY GATE PRE-COMMIT" in content
    assert "QUALITY GATE PRE-PUSH" in content
    assert "agent-quality-gate.sh pre-commit" in content
    assert "agent-quality-gate.sh pre-push" in content


def test_agent_doctor_verifies_quality_gate_assets():
    content = read("scripts/agent-doctor.sh")

    assert "quality gate manifest" in content
    assert "agent-quality-gate.sh" in content
    assert "knowledge-record-gate.sh" in content
    assert "neat-freak-gate.sh" in content


def test_repo_managed_git_hooks_delegate_to_quality_gate_runner():
    pre_commit = read("agent/quality-gates/hooks/pre-commit")
    pre_push = read("agent/quality-gates/hooks/pre-push")
    installer = read("scripts/install-agent-tooling.sh")

    assert "agent-quality-gate.sh pre-commit" in pre_commit
    assert "agent-quality-gate.sh pre-push" in pre_push
    assert "core.hooksPath" in installer
    assert "template/agent/quality-gates/hooks" in installer
