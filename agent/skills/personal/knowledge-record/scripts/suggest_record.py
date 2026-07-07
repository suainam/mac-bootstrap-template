#!/usr/bin/env python3
"""Suggest-first workflow for knowledge-record."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import confirmation_flow
import evidence_collect
import record_knowledge
import suggestion_engine
import thread_capture


def save_draft(
    draft: suggestion_engine.RecordDraft,
    *,
    date: str | None = None,
    db_path: str | None = None,
    project_path: str | None = None,
) -> str:
    args = draft.to_record_args(date=date, db_path=db_path, project_path=project_path)
    record = record_knowledge.build_record(args)
    target = Path(db_path) if db_path else record_knowledge.find_db_path()
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        return str(record_knowledge.insert_record(conn, record))
    finally:
        conn.close()


def load_saved_record(record_id: str, *, db_path: str | None = None) -> dict[str, object]:
    target = Path(db_path) if db_path else record_knowledge.find_db_path()
    with sqlite3.connect(str(target)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT
                id,
                record_type,
                title,
                content,
                background,
                tags,
                references_json,
                why_record,
                agent_type,
                status,
                candidate_date,
                project_path,
                recorded_at
            FROM knowledge_records
            WHERE id = ?
            """,
            (record_id,),
        ).fetchone()
    if row is None:
        raise RuntimeError(f"saved record not found: {record_id}")
    return dict(row)


def render_saved_record(record: dict[str, object]) -> str:
    ordered_keys = [
        "id",
        "record_type",
        "title",
        "content",
        "background",
        "tags",
        "references_json",
        "why_record",
        "agent_type",
        "status",
        "candidate_date",
        "project_path",
        "recorded_at",
    ]
    lines = ["Saved knowledge record:"]
    for key in ordered_keys:
        value = record.get(key)
        if value is not None:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Suggest and confirm a knowledge record")
    parser.add_argument("--repo-root", default=str(Path.cwd()))
    parser.add_argument("--agent", default="codex")
    parser.add_argument("--date")
    parser.add_argument("--db-path")
    parser.add_argument("--project-path")
    parser.add_argument("--thread-json", help="Current agent thread as JSON list of {role, content}")
    parser.add_argument("--thread-summary", help="Current agent thread summary supplied by the agent")
    parser.add_argument(
        "--action",
        action="append",
        help="Non-interactive confirmation action; repeat for edit/regenerate/accept flows",
    )
    return parser


def run_suggest(args: argparse.Namespace) -> confirmation_flow.ConfirmationResult:
    thread = thread_capture.capture_current_thread(
        thread_json=args.thread_json,
        thread_summary=args.thread_summary,
    )
    evidence = evidence_collect.collect_repo_evidence(Path(args.repo_root))

    def regenerate() -> suggestion_engine.RecordDraft:
        return suggestion_engine.suggest_record(thread, evidence, agent_type=args.agent)

    draft = regenerate()
    return confirmation_flow.confirm_draft(
        draft,
        actions=args.action,
        regenerate_callback=regenerate,
        save_callback=lambda accepted: save_draft(
            accepted,
            date=args.date,
            db_path=args.db_path,
            project_path=args.project_path,
        ),
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_suggest(args)
    if result.status == "accepted":
        print(f"Saved suggested record: {result.saved}")
        print(render_saved_record(load_saved_record(str(result.saved), db_path=args.db_path)))
        return 0
    print("Suggestion canceled")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
