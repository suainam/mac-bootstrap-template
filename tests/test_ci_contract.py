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

    for target in ("ci", "syntax-check", "pytest", "pytest-all", "neat-freak-ci"):
        assert f"{target}:" in makefile
    assert "scripts/syntax-check.sh" in makefile
    assert "scripts/neat-freak-ci.sh" in makefile
    assert "-m 'not machine'" in makefile


def test_neat_freak_ci_classifies_workflows_as_operational():
    gate = read("scripts/neat-freak-gate.sh")

    assert ".github/workflows/*" in gate
    assert "docs/archive/*" in gate
    assert "*.json" in gate
    assert "*/requirements*.txt" in gate
    assert "has_docs" in gate


def test_syntax_check_discovers_tracked_source_files():
    checker = read("scripts/syntax-check.sh")

    assert "git ls-files -z -- '*.sh'" in checker
    assert "git ls-files -z -- '*.py'" in checker
    assert "git ls-files -z -- '*.lua'" in checker


def test_neat_freak_ci_rejects_unknown_base_revision():
    checker = read("scripts/neat-freak-ci.sh")

    assert 'BASE_REF="${NEAT_FREAK_BASE_REF-}"' in checker
    assert "base revision not found" in checker
    assert "0000000000000000000000000000000000000000" in checker
