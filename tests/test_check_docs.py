"""Behavioural tests for template/scripts/check_docs.py."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_docs


def test_clean_doc_passes(tmp_path: Path):
    doc = tmp_path / "test.md"
    doc.write_text(
        "# Heading\n\n"
        "Here is an [internal anchor](#heading) and a [valid link](sub.md).\n\n"
        "```bash\n"
        "export MY_VAR=\"hello\"\n"
        "echo \"$MY_VAR\"\n"
        "```\n"
    )
    (tmp_path / "sub.md").write_text("# Subdoc\n")
    findings = check_docs.check_file(doc)
    assert findings == []


def test_broken_relative_link_detected(tmp_path: Path):
    doc = tmp_path / "test.md"
    doc.write_text(
        "[missing doc](non_existent_file.md)\n"
    )
    findings = check_docs.check_file(doc)
    assert len(findings) == 1
    assert "broken relative link: non_existent_file.md" in str(findings[0])


def test_invalid_shell_syntax_detected(tmp_path: Path):
    doc = tmp_path / "test.md"
    doc.write_text(
        "```bash\n"
        "if true; then\n"
        "# missing fi\n"
        "```\n"
    )
    findings = check_docs.check_file(doc)
    assert len(findings) == 1
    assert "shell block does not parse" in str(findings[0])


def test_secret_in_argv_detected(tmp_path: Path):
    doc = tmp_path / "test.md"
    doc.write_text(
        "```bash\n"
        "mycli --auth-token secret_key_12345\n"
        "```\n"
    )
    findings = check_docs.check_file(doc)
    assert len(findings) == 1
    assert "secret value in command-line argv: --auth-token secret_key_12345" in str(findings[0])


def test_safe_env_or_placeholder_argv_allowed(tmp_path: Path):
    doc = tmp_path / "test.md"
    doc.write_text(
        "```bash\n"
        "mycli --auth-token \"$AI_MEMORY_AUTH_TOKEN\"\n"
        "mycli --bearer-token \"<YOUR_TOKEN>\"\n"
        "mycli --api-key \"{{SECRET}}\"\n"
        "```\n"
    )
    findings = check_docs.check_file(doc)
    assert findings == []


def test_angle_and_brace_placeholders_do_not_break_shell_parse(tmp_path: Path):
    doc = tmp_path / "test.md"
    doc.write_text(
        "```bash\n"
        "python3 scripts/linter.py <path/to/solution.sql>\n"
        "mycli detail <表名> --filter <字段关键词>\n"
        "mycli --token {{TOKEN}}\n"
        "```\n"
    )
    findings = check_docs.check_file(doc)
    assert findings == []


def test_real_syntax_error_still_detected_with_placeholders(tmp_path: Path):
    doc = tmp_path / "test.md"
    doc.write_text(
        "```bash\n"
        "python3 scripts/linter.py <path/to/solution.sql>\n"
        "if true; then\n"
        "# missing fi\n"
        "```\n"
    )
    findings = check_docs.check_file(doc)
    assert len(findings) == 1
    assert "shell block does not parse" in str(findings[0])


def test_redirection_is_not_treated_as_placeholder(tmp_path: Path):
    doc = tmp_path / "test.md"
    doc.write_text(
        "```bash\n"
        "cat file.txt > out.txt\n"
        "diff a b >> log.txt\n"
        "```\n"
    )
    findings = check_docs.check_file(doc)
    assert findings == []
