from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_public_ci_workflow_uses_read_only_contract():
    workflow = read(".github/workflows/ci.yml")

    assert "pull_request:" in workflow
    assert "branches:" in workflow
    assert "- main" in workflow
    assert "contents: read" in workflow
    assert "uv sync --locked --group dev" in workflow
    assert "run: make ci" in workflow
    assert "secrets." not in workflow


def test_makefile_exposes_public_ci_components():
    makefile = read("Makefile")

    for target in ("ci", "syntax-check", "pytest", "neat-freak-ci"):
        assert f"{target}:" in makefile
    assert "scripts/syntax-check.sh" in makefile
    assert "scripts/neat-freak-ci.sh" in makefile


def test_neat_freak_ci_classifies_workflows_as_operational():
    gate = read("scripts/neat-freak-gate.sh")

    assert ".github/workflows/*" in gate
    assert "has_docs" in gate
