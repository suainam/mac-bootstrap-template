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


def test_inline_code_is_not_scanned_as_a_link(tmp_path: Path):
    doc = tmp_path / "test.md"
    doc.write_text("Paste `![](url)` into the note after the upload.\n")
    assert check_docs.check_file(doc) == []


def test_archive_and_quarantine_directories_are_skipped(tmp_path: Path):
    for name in ("archive", "quarantine"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "broken.md").write_text("[gone](missing.md)\n")
    kept = tmp_path / "kept.md"
    kept.write_text("[gone](missing.md)\n")
    assert [path.name for path in check_docs.iter_docs([tmp_path])] == ["kept.md"]


def _repo(tmp_path: Path, makefile: str) -> Path:
    (tmp_path / "Makefile").write_text(makefile)
    return tmp_path


def test_unknown_make_target_detected(tmp_path: Path):
    root = _repo(tmp_path, "build:\n\t@:\n")
    doc = root / "guide.md"
    doc.write_text("```bash\nmake deploy\n```\n")
    findings = check_docs.check_file(doc)
    assert [str(finding) for finding in findings] == [
        f"{doc}:2: unknown make target: deploy"
    ]


def test_known_make_targets_and_arguments_are_allowed(tmp_path: Path):
    root = _repo(
        tmp_path,
        "build:\n\t@:\nrelease: build\n\t@:\ninstall:\n\t@:\n.phonyish:\n",
    )
    doc = root / "guide.md"
    doc.write_text(
        "```bash\n"
        "make build\n"
        "make -j4 release\n"
        "PROFILE=work make build\n"
        "make -C . build\n"
        "make install DEST=/tmp/x\n"
        "make\n"
        "```\n"
        "Run `make build` after editing.\n"
    )
    assert check_docs.check_file(doc) == []


def test_prose_and_placeholders_are_not_make_targets(tmp_path: Path):
    root = _repo(tmp_path, "build:\n\t@:\n")
    doc = root / "guide.md"
    doc.write_text(
        "Make sure the build works, then make it fast.\n"
        "```bash\n"
        "make <target>\n"
        "make $TARGET\n"
        "make build* \n"
        "# make commented-out\n"
        "```\n"
    )
    assert check_docs.check_file(doc) == []


def test_catch_all_makefile_accepts_forwarded_targets(tmp_path: Path):
    (tmp_path / "template").mkdir()
    (tmp_path / "template" / "Makefile").write_text("forwarded:\n\t@:\n")
    (tmp_path / "Makefile").write_text("%:\n\t$(MAKE) -C template $@\n")
    doc = tmp_path / "guide.md"
    doc.write_text("```bash\nmake forwarded\n```\n")
    assert check_docs.check_file(doc) == []


def test_make_target_check_never_runs_recipes(tmp_path: Path):
    marker = tmp_path / "ran"
    (tmp_path / "Makefile").write_text(f"deploy:\n\ttouch {marker}\n")
    doc = tmp_path / "guide.md"
    doc.write_text("```bash\nmake deploy\n```\n")
    assert check_docs.check_file(doc) == []
    assert not marker.exists()


def test_missing_authority_path_detected(tmp_path: Path):
    (tmp_path / "Makefile").write_text("build:\n\t@:\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "present.md").write_text("ok\n")
    doc = tmp_path / "matrix.md"
    doc.write_text(
        "| 主题 | 权威来源 |\n"
        "|---|---|\n"
        "| A | `docs/present.md` |\n"
        "| B | `docs/absent.md` |\n"
    )
    findings = check_docs.check_file(doc)
    assert [str(finding) for finding in findings] == [
        f"{doc}:4: authority path does not exist: docs/absent.md"
    ]


def test_authority_paths_skip_prose_globs_and_home(tmp_path: Path):
    (tmp_path / "Makefile").write_text("build:\n\t@:\n")
    (tmp_path / "a.md").write_text("ok\n")
    (tmp_path / "b.md").write_text("ok\n")
    doc = tmp_path / "matrix.md"
    doc.write_text(
        "| 主题 | 权威来源 | 备注 |\n"
        "|---|---|---|\n"
        "| A | `{a,b}.md` | `missing.md` 不在权威列 |\n"
        "| B | `~/runtime.jsonc`、`https://example.com/x.md` |\n"
    )
    assert check_docs.check_file(doc) == []


def test_historical_marker_skips_content_checks(tmp_path: Path):
    doc = tmp_path / "proposal.md"
    doc.write_text(
        "<!-- check-docs: historical -->\n"
        "```bash\nmake not-implemented-yet\n```\n"
    )
    assert check_docs.check_file(doc) == []


def test_make_targets_checked_only_in_own_interface_docs(tmp_path: Path):
    """Skill docs describe other repositories' make targets, not this one."""
    (tmp_path / "Makefile").write_text("build:\n\t@:\n")
    skill_doc = tmp_path / "skills" / "other"
    skill_doc.mkdir(parents=True)
    doc = skill_doc / "SKILL.md"
    doc.write_text("```bash\nmake deploy-to-their-server\n```\n")
    assert check_docs.check_file(doc) == []


def test_quoted_arguments_are_not_make_targets(tmp_path: Path):
    (tmp_path / "Makefile").write_text("new-project:\n\t@:\n")
    doc = tmp_path / "guide.md"
    doc.write_text('```bash\nmake new-project NAME=x DESC="Short description"\n```\n')
    assert check_docs.check_file(doc) == []


def test_make_after_cd_elsewhere_is_ignored(tmp_path: Path):
    (tmp_path / "Makefile").write_text("build:\n\t@:\n")
    doc = tmp_path / "guide.md"
    doc.write_text(
        "```bash\ncd $HOME/work/projects/sales\nmake export\n```\n"
    )
    assert check_docs.check_file(doc) == []
