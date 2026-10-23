import os
import re
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANNOTATION = re.compile(r"^## (\d+)\.(\d+) (.+?) \| (.+?) \| (.+)$")


def annotations() -> list[tuple[int, str, str, str]]:
    """Return [(section_rank, section, display, description)] from the Makefile."""
    found: list[tuple[int, str, str, str]] = []
    with open(os.path.join(ROOT, "Makefile"), encoding="utf-8") as handle:
        for line in handle:
            match = ANNOTATION.match(line.rstrip("\n"))
            if match:
                rank, _order, section, display, description = match.groups()
                found.append((int(rank), section, display, description))
    return found


def sections(stdout: str) -> list[tuple[str, dict[str, str]]]:
    """Return [(section, {display: description})] in rendered order."""
    found: list[tuple[str, dict[str, str]]] = []
    for line in stdout.splitlines():
        if line.startswith("── ") and line.endswith(" ──"):
            found.append((line[3:-3], {}))
        elif line.startswith("  ") and found:
            display, _, description = line[2:].partition("  ")
            found[-1][1][display.rstrip()] = description.strip()
    return found


@pytest.fixture(name="help_output", scope="module")
def fixture_help_output() -> str:
    result = subprocess.run(
        ["make", "help"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_help_renders_every_annotation(help_output: str) -> None:
    assert "Usage: make <target>" in help_output

    rendered = dict(sections(help_output))
    entries = annotations()
    assert entries, "the Makefile should annotate its help entries"
    for _rank, section, display, description in entries:
        assert section in rendered
        assert rendered[section].get(display) == description


def test_sections_follow_their_rank(help_output: str) -> None:
    ranks: dict[str, int] = {}
    for rank, section, _display, _description in annotations():
        ranks.setdefault(section, rank)
    rendered = [name for name, _entries in sections(help_output)]
    assert rendered == sorted(ranks, key=lambda name: ranks[name])


def test_annotated_entries_name_a_real_target() -> None:
    targets: set[str] = set()
    with open(os.path.join(ROOT, "Makefile"), encoding="utf-8") as handle:
        for line in handle:
            if line.startswith(("\t", "#")) or not line.strip():
                continue
            match = re.match(r"^([A-Za-z0-9_][A-Za-z0-9_. -]*?)\s*:(?!=)", line)
            if match:
                targets.update(match.group(1).split())
    for _rank, _section, display, _description in annotations():
        words = [word for word in re.split(r"[\s/]+", display) if word]
        assert any(word in targets for word in words), display
