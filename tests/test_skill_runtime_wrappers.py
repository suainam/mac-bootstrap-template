"""Integration tests for skills invoked through distribution-shaped symlinks."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _install_command_stubs(template_root: Path, stub_log: Path) -> tuple[Path, Path]:
    python = template_root / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/sh\n"
        'printf "python" >> "$STUB_LOG"\n'
        'for arg in "$@"; do printf "\\t%s" "$arg" >> "$STUB_LOG"; done\n'
        'printf "\\n" >> "$STUB_LOG"\n',
        encoding="utf-8",
    )
    python.chmod(0o755)

    sqlite = template_root / ".test-bin/sqlite3"
    sqlite.parent.mkdir(parents=True)
    sqlite.write_text(
        "#!/bin/sh\n"
        'printf "sqlite3\\n" >> "$STUB_LOG"\n',
        encoding="utf-8",
    )
    sqlite.chmod(0o755)
    stub_log.touch()
    return python, sqlite


def _run_distributed_wrapper(
    tmp_path: Path,
    source_wrapper: str,
    wrapper_relative_to_skill: str,
    *args: str,
) -> tuple[Path, list[list[str]]]:
    source = ROOT / source_wrapper
    source_parts = Path(source_wrapper).parts
    skill_index = source_parts.index("agent-skills") + 3
    skill_name = source_parts[skill_index]
    source_skill = ROOT.joinpath(*source_parts[: skill_index + 1])

    synthetic_template = tmp_path / "checkout/template"
    synthetic_skill = synthetic_template.joinpath(*source_parts[: skill_index + 1])
    synthetic_skill.parent.mkdir(parents=True)
    shutil.copytree(source_skill, synthetic_skill)
    synthetic_wrapper = synthetic_skill / wrapper_relative_to_skill
    assert synthetic_wrapper.read_bytes() == source.read_bytes()
    assert source.stat().st_mode & 0o111
    assert synthetic_wrapper.stat().st_mode & 0o111

    stub_log = tmp_path / f"{skill_name}-{Path(wrapper_relative_to_skill).stem}.calls"
    _python, sqlite = _install_command_stubs(synthetic_template, stub_log)

    distribution = tmp_path / "runtime/skills"
    distribution.mkdir(parents=True)
    linked_skill = distribution / skill_name
    linked_skill.symlink_to(synthetic_skill, target_is_directory=True)
    linked_wrapper = linked_skill / wrapper_relative_to_skill
    command = [str(linked_wrapper), *args]
    env = {
        **os.environ,
        "STUB_LOG": str(stub_log),
        "PATH": f"{sqlite.parent}:{os.environ['PATH']}",
    }

    subprocess.run(command, check=True, env=env, text=True, capture_output=True)

    template = str(synthetic_template)
    repo = str(synthetic_template.parent)
    calls = []
    for line in stub_log.read_text(encoding="utf-8").splitlines():
        calls.append([part.replace(template, "<template>").replace(repo, "<repo>") for part in line.split("\t")])
    return synthetic_wrapper, calls


@pytest.mark.parametrize(
    ("source_wrapper", "wrapper_relative", "args", "expected_calls"),
    [
        (
            "agent-skills/local/global/knowledge-lifecycle-manager/run.sh",
            "run.sh",
            ("status",),
            [["python", "<template>/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py", "status"]],
        ),
        (
            "agent-skills/local/mac-bootstrap/knowledge-candidate-review/scripts/run-candidate-review.sh",
            "scripts/run-candidate-review.sh",
            ("2026-07-10",),
            [["python", "<template>/data-hub/scripts/generate_candidates.py", "2026-07-10"]],
        ),
        (
            "agent-skills/local/mac-bootstrap/knowledge-claim-extraction/scripts/run-claim-extraction.sh",
            "scripts/run-claim-extraction.sh",
            ("2026-07-10",),
            [["python", "<template>/data-hub/scripts/claim_extraction.py", "2026-07-10"]],
        ),
        (
            "agent-skills/local/mac-bootstrap/knowledge-daily-weekly-synthesis/scripts/run-daily-synthesis.sh",
            "scripts/run-daily-synthesis.sh",
            ("2026-07-10",),
            [["python", "<template>/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py", "run", "--workflow", "build_daily_summary", "--date", "2026-07-10"]],
        ),
        (
            "agent-skills/local/mac-bootstrap/knowledge-hygiene-audit/scripts/run-hygiene-audit.sh",
            "scripts/run-hygiene-audit.sh",
            ("--json",),
            [["python", "<template>/data-hub/scripts/hygiene_audit.py", "--json"]],
        ),
        (
            "agent-skills/local/mac-bootstrap/knowledge-materialization/scripts/run-materialization.sh",
            "scripts/run-materialization.sh",
            ("2026-07-10",),
            [["python", "<template>/data-hub/scripts/materialize_candidates.py", "2026-07-10"]],
        ),
        (
            "agent-skills/local/mac-bootstrap/knowledge-record/run.sh",
            "run.sh",
            ("suggest",),
            [["python", "<template>/agent-skills/local/mac-bootstrap/knowledge-record/scripts/record_knowledge.py", "suggest"]],
        ),
        (
            "agent-skills/local/mac-bootstrap/knowledge-reuse-retrieval/scripts/run-retrieval.sh",
            "scripts/run-retrieval.sh",
            ("query",),
            [["python", "<template>/data-hub/scripts/knowledge_retrieval.py", "query"]],
        ),
        (
            "agent-skills/local/mac-bootstrap/knowledge-source-ingestion/scripts/check-ingestion.sh",
            "scripts/check-ingestion.sh",
            (),
            [
                ["python", "<template>/data-hub/scripts/ingest_sources.py"],
                ["python", "-m", "py_compile", "<template>/data-hub/scripts/ingest_sources.py", "<template>/data-hub/scripts/generate_candidates.py", "<template>/data-hub/scripts/materialize_candidates.py", "<template>/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py"],
                ["sqlite3"],
                ["sqlite3"],
            ],
        ),
        (
            "agent-skills/local/mac-bootstrap/knowledge-source-ingestion/scripts/run-full-cycle.sh",
            "scripts/run-full-cycle.sh",
            ("<repo>", "2026-07-10"),
            [
                ["python", "<template>/data-hub/scripts/ingest_logs.py"],
                ["python", "<template>/data-hub/scripts/ingest_sources.py"],
                ["python", "<template>/data-hub/scripts/generate_candidates.py", "2026-07-10"],
                ["sqlite3"],
                ["sqlite3"],
                ["sqlite3"],
                ["python", "<template>/agent-skills/local/global/knowledge-lifecycle-manager/scripts/manager.py", "run", "--workflow", "build_daily_summary", "--date", "2026-07-10"],
            ],
        ),
        (
            "agent-skills/local/mac-bootstrap/knowledge-source-ingestion/scripts/run-sqlite-landing.sh",
            "scripts/run-sqlite-landing.sh",
            ("<repo>", "2026-07-10"),
            [
                ["python", "<template>/data-hub/scripts/ingest_logs.py"],
                ["python", "<template>/data-hub/scripts/ingest_sources.py"],
                ["python", "<template>/data-hub/scripts/generate_candidates.py", "2026-07-10"],
                ["sqlite3"],
                ["sqlite3"],
                ["sqlite3"],
            ],
        ),
    ],
)
def test_migrated_wrapper_resolves_runtime_from_distributed_symlink(
    tmp_path: Path,
    source_wrapper: str,
    wrapper_relative: str,
    args: tuple[str, ...],
    expected_calls: list[list[str]],
) -> None:
    synthetic_repo = tmp_path / "checkout"
    resolved_args = tuple(str(synthetic_repo) if arg == "<repo>" else arg for arg in args)
    wrapper, calls = _run_distributed_wrapper(
        tmp_path,
        source_wrapper,
        wrapper_relative,
        *resolved_args,
    )

    assert wrapper.stat().st_mode & 0o111
    assert calls == expected_calls
