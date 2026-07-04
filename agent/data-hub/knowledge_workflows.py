#!/usr/bin/env python3
"""
Codify the knowledge lifecycle workflows as stable step lists so Codex can
schedule them consistently.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent


def get_runtime_python() -> str:
    venv_python = CURRENT_DIR.parents[1] / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def build_workflow_steps(workflow_name: str, target_date: str) -> list[dict]:
    python = get_runtime_python()
    if workflow_name == "daily_ingest_and_review":
        return [
            {
                "name": "knowledge-reuse-retrieval",
                "command": [python, str(CURRENT_DIR / "knowledge_retrieval.py"), "--task-goal", workflow_name, "--keyword", target_date],
                "produces": ["retrieval_packet.json"],
            },
            {
                "name": "knowledge-source-ingestion:logs",
                "command": [python, str(CURRENT_DIR / "ingest_logs.py")],
                "produces": ["sessions", "messages"],
            },
            {
                "name": "knowledge-source-ingestion:sources",
                "command": [python, str(CURRENT_DIR / "ingest_sources.py")],
                "produces": ["source_documents", "document_chunks", "extracted_items"],
            },
            {
                "name": "knowledge-claim-extraction",
                "command": [python, str(CURRENT_DIR / "claim_extraction.py"), target_date],
                "produces": ["claim_packets.json"],
            },
            {
                "name": "knowledge-candidate-review",
                "command": [python, str(CURRENT_DIR / "generate_candidates.py"), target_date],
                "produces": [f"60_Inbox/Candidates/{target_date}.md"],
            },
        ]
    if workflow_name == "daily_promote_and_summary":
        return [
            {
                "name": "knowledge-materialization",
                "command": [python, str(CURRENT_DIR / "materialize_candidates.py"), target_date],
                "produces": ["40_Knowledge/*", f"10_Periodic/Daily/{target_date}.md"],
            },
            {
                "name": "knowledge-daily-weekly-synthesis",
                "command": [python, str(CURRENT_DIR / "daily_summary.py"), target_date],
                "produces": [f"10_Periodic/Daily/{target_date}.md"],
            },
        ]
    if workflow_name == "weekly_hygiene_and_reuse":
        return [
            {
                "name": "knowledge-hygiene-audit",
                "command": [python, str(CURRENT_DIR / "hygiene_audit.py"), "--stale-before", target_date],
                "produces": ["knowledge_hygiene_report.json"],
            },
            {
                "name": "knowledge-reuse-retrieval",
                "command": [python, str(CURRENT_DIR / "knowledge_retrieval.py"), "--task-goal", workflow_name, "--keyword", target_date],
                "produces": ["retrieval_packet.json"],
            },
        ]
    if workflow_name == "source_adapter_upgrade":
        return [
            {
                "name": "knowledge-source-ingestion:sources",
                "command": [python, str(CURRENT_DIR / "ingest_sources.py")],
                "produces": ["source_documents", "document_chunks", "extracted_items"],
            },
            {
                "name": "source-regression-tests",
                "command": [python, "-m", "pytest", "tests/test_data_hub_sources.py", "-q"],
                "produces": ["pytest-report"],
            },
        ]
    raise ValueError(f"unknown workflow: {workflow_name}")


def run_workflow(
    workflow_name: str,
    target_date: str,
    *,
    dry_run: bool = False,
    runner=None,
) -> list[dict]:
    steps = build_workflow_steps(workflow_name, target_date)
    if dry_run:
        return steps

    exec_runner = runner or subprocess.run
    results = []
    for step in steps:
        exec_runner(step["command"], check=True)
        results.append({"name": step["name"], "status": "completed", "produces": step["produces"]})
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or inspect a knowledge lifecycle workflow.")
    parser.add_argument("workflow")
    parser.add_argument("target_date")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_workflow(args.workflow, args.target_date, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
