#!/usr/bin/env python3
"""Stable workflow registry and CLI for Agent Data Hub."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from workflow_contracts import StageSpec, SuccessCheck, stages_to_dicts
from workflow_runner import WorkflowRunner


CURRENT_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = CURRENT_DIR.parents[1]
SCRIPTS_DIR = CURRENT_DIR / "scripts"


def get_runtime_python() -> str:
    venv_python = TEMPLATE_DIR / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def supported_workflows() -> list[str]:
    return [
        "archive_to_sqlite",
        "render_obsidian",
        "full_cycle",
    ]


def build_workflow_steps(workflow_name: str, target_date: str) -> list[StageSpec]:
    python = get_runtime_python()
    if workflow_name == "archive_to_sqlite":
        return [
            StageSpec(
                name="knowledge-reuse-retrieval",
                command=[
                    python,
                    str(SCRIPTS_DIR / "knowledge_retrieval.py"),
                    "--task-goal",
                    workflow_name,
                    "--keyword",
                    target_date,
                ],
                produces=["retrieval_packet.json"],
            ),
            StageSpec(
                name="knowledge-source-ingestion:logs",
                command=[python, str(SCRIPTS_DIR / "ingest_logs.py")],
                produces=["sessions", "messages"],
            ),
            StageSpec(
                name="knowledge-source-ingestion:sources",
                command=[python, str(SCRIPTS_DIR / "ingest_sources.py")],
                produces=["source_documents", "document_chunks", "extracted_items"],
            ),
            StageSpec(
                name="knowledge-claim-extraction",
                command=[python, str(SCRIPTS_DIR / "claim_extraction.py"), target_date],
                produces=["claim_packets.json"],
            ),
            StageSpec(
                name="knowledge-candidate-review",
                command=[python, str(SCRIPTS_DIR / "generate_candidates.py"), target_date],
                produces=[f"60_Inbox/Candidates/{target_date}.md"],
                success_checks=[
                    SuccessCheck("file_exists", f"60_Inbox/Candidates/{target_date}.md"),
                ],
            ),
        ]
    if workflow_name == "render_obsidian":
        return [
            materialization_stage(python, target_date),
            daily_summary_stage(python, target_date),
        ]
    if workflow_name == "full_cycle":
        return [
            *build_workflow_steps("archive_to_sqlite", target_date),
            *build_workflow_steps("render_obsidian", target_date),
        ]
    raise ValueError(f"unknown workflow: {workflow_name}")


def materialization_stage(python: str, target_date: str) -> StageSpec:
    return StageSpec(
        name="knowledge-materialization",
        command=[python, str(SCRIPTS_DIR / "materialize_candidates.py"), target_date],
        produces=["40_Knowledge/*", f"10_Periodic/Daily/{target_date}.md"],
        success_checks=[
            SuccessCheck("file_exists", f"10_Periodic/Daily/{target_date}.md"),
            SuccessCheck("output_not_contains", "combined", ["duplicate marker failure"]),
        ],
    )


def daily_summary_stage(python: str, target_date: str) -> StageSpec:
    return StageSpec(
        name="knowledge-daily-weekly-synthesis",
        command=[python, str(SCRIPTS_DIR / "daily_summary.py"), target_date],
        produces=[f"10_Periodic/Daily/{target_date}.md"],
        success_checks=[
            SuccessCheck("file_exists", f"10_Periodic/Daily/{target_date}.md"),
            SuccessCheck("output_not_contains", "combined", ["LLM generation failed", "生成总结失败", "调用 LLM 失败"]),
        ],
        degraded_ok=True,
    )


def run_durable_workflow(
    workflow_name: str,
    target_date: str,
    *,
    run_id: str | None = None,
    resume_run_id: str | None = None,
    retry_failed_run_id: str | None = None,
    from_step: str | None = None,
    max_attempts: int = 1,
    command_runner=None,
    conn=None,
    runs_dir: Path | None = None,
    sleep=None,
) -> list[dict]:
    steps = build_workflow_steps(workflow_name, target_date)
    runner = WorkflowRunner(conn=conn, command_runner=command_runner, runs_dir=runs_dir, sleep=sleep or time.sleep)
    try:
        return runner.run(
            workflow_name,
            target_date,
            steps,
            run_id=run_id,
            resume_run_id=resume_run_id,
            retry_failed_run_id=retry_failed_run_id,
            from_step=from_step,
            max_attempts=max_attempts,
        )
    finally:
        runner.close()


def run_workflow(
    workflow_name: str,
    target_date: str,
    *,
    dry_run: bool = False,
    runner=None,
    durable: bool = False,
    run_id: str | None = None,
    resume_run_id: str | None = None,
    retry_failed_run_id: str | None = None,
    from_step: str | None = None,
    max_attempts: int = 1,
) -> list[dict]:
    steps = build_workflow_steps(workflow_name, target_date)
    if dry_run:
        return stages_to_dicts(steps)
    if durable:
        return run_durable_workflow(
            workflow_name,
            target_date,
            run_id=run_id,
            resume_run_id=resume_run_id,
            retry_failed_run_id=retry_failed_run_id,
            from_step=from_step,
            max_attempts=max_attempts,
        )

    exec_runner = runner or subprocess.run
    results = []
    for step in steps:
        exec_runner(step.command, check=True)
        results.append({"name": step.name, "status": "completed", "produces": step.produces})
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or inspect a knowledge lifecycle workflow.")
    parser.add_argument("workflow", choices=supported_workflows())
    parser.add_argument("target_date")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--durable", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--resume")
    parser.add_argument("--retry-failed")
    parser.add_argument("--from-step")
    parser.add_argument("--max-attempts", type=int, default=1)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_workflow(
        args.workflow,
        args.target_date,
        dry_run=args.dry_run,
        durable=args.durable or bool(args.resume or args.retry_failed or args.from_step or args.run_id),
        run_id=args.run_id,
        resume_run_id=args.resume,
        retry_failed_run_id=args.retry_failed,
        from_step=args.from_step,
        max_attempts=args.max_attempts,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
