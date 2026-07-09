"""Regression checks for llm_wiki install/build wiring."""

import os
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent


def read(*parts: str) -> str:
    return (TEMPLATE / Path(*parts)).read_text(encoding="utf-8")


def test_makefile_and_doctor_expose_llm_wiki_ops_surface():
    makefile = read("Makefile")
    doctor = read("scripts", "agent-doctor.sh")
    install_script = read("scripts", "install-llm-wiki.sh")

    assert "llm-wiki-install:" in makefile
    assert "llm-wiki-build:" in makefile
    assert "llm-wiki-mcp-build:" in makefile
    assert "llm-wiki-doctor:" in makefile
    assert "LLM_WIKI_DIR" in install_script
    assert "cargo" in install_script
    assert "npm install" in install_script
    assert "npm run tauri build" in install_script
    assert "npm run mcp:build" in install_script
    assert "llm_wiki" in doctor
    assert "llm-wiki-mcp-build" in doctor
