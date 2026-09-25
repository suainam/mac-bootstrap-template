"""Regression checks for llm_wiki retirement (inactive/rollback-only status)."""

from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent


def read(*parts: str) -> str:
    return (TEMPLATE / Path(*parts)).read_text(encoding="utf-8")


def test_makefile_and_doctor_retire_active_llm_wiki_surface():
    makefile = read("Makefile")
    doctor = read("scripts", "agent-doctor.sh")
    install_script = read("scripts", "install-llm-wiki.sh")
    runtime_example = read("data-hub", "data_hub.runtime.jsonc.example")

    # Retired from default Makefile targets and help
    assert "llm-wiki-install:" not in makefile
    assert "llm-wiki-build:" not in makefile
    assert "llm-wiki-mcp-build:" not in makefile
    assert "llm-wiki-doctor:" not in makefile

    # Historical install script preserved for rollback-only
    assert "LLM_WIKI_DIR" in install_script
    assert "cargo" in install_script

    # Doctor no longer probes LLM Wiki
    assert "llm_wiki" not in doctor
    assert "LLM Wiki.app" not in doctor

    # Example runtime config no longer exposes active llm_wiki section
    assert '"llm_wiki"' not in runtime_example


def test_period_summary_defaults_to_no_llm_wiki():
    period_summary = read("data-hub", "period_summary.py")

    assert "include_llm_wiki=False" in period_summary
    assert "make_llm_wiki_client()" not in period_summary
