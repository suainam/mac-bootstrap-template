import sqlite3
import sys
import types
from datetime import datetime
from pathlib import Path
import zipfile


DATA_HUB_DIR = Path(__file__).parent.parent / "agent" / "data-hub"
SCRIPTS_DIR = DATA_HUB_DIR / "scripts"
sys.path.insert(0, str(DATA_HUB_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

import generate_candidates
import materialize_candidates
import daily_summary
import source_dates
import source_ingest_store
from candidate_store import candidate_type_for
from source_adapters import hash_text_file
from source_adapters.wiki_html import parse as parse_wiki_html
from source_adapters.wiki_pdf import parse as parse_wiki_pdf
from source_adapters.meeting_markdown import parse as parse_meeting_markdown
from source_adapters.xmind_adapter import parse as parse_xmind
from candidate_review_io import stable_candidate_id


def test_document_matches_target_prefers_filename_date_then_landing_date():
    metadata = {"filename_date": "2026-07-04", "landing_date": "2026-07-05"}
    assert source_dates.document_matches_target(
        "/tmp/2026-07-04_sample.html",
        "2026-07-03T10:00:00",
        "2026-07-05T12:00:00",
        metadata,
        "2026-07-04",
    )
    assert not source_dates.document_matches_target(
        "/tmp/2026-07-04_sample.html",
        "2026-07-03T10:00:00",
        "2026-07-05T12:00:00",
        metadata,
        "2026-07-05",
    )
    assert source_dates.document_matches_target(
        "/tmp/no-date.html",
        "2026-07-03T10:00:00",
        "2026-07-05T12:00:00",
        {"landing_date": "2026-07-05"},
        "2026-07-05",
    )
    assert not source_dates.document_matches_target(
        "/tmp/no-date.html",
        "2026-07-03T10:00:00",
        "2026-07-05T12:00:00",
        {"landing_date": "2026-07-05"},
        "2026-07-04",
        mode="filename_only",
    )


def test_parse_wiki_html_extracts_structured_blocks(tmp_path: Path):
    html_path = tmp_path / "2026-07-04_confluence_sample.html"
    html_path.write_text(
        """
        <html><head><title>Confluence Export Sample</title></head>
        <body>
        <h1>增长实验周会</h1>
        <p>验证 html adapter。</p>
        <h2>决策</h2>
        <ul><li>决定先保留轻量审核。</li></ul>
        <h2>行动项</h2>
        <ul><li>整理 HTML 导出样例。</li></ul>
        <table><tr><th>负责人</th><th>事项</th></tr><tr><td>南宗帅</td><td>验证 parser</td></tr></table>
        </body></html>
        """,
        encoding="utf-8",
    )

    title, chunks, items, meta = parse_wiki_html(html_path)

    assert title == "增长实验周会"
    assert meta["source_kind"] == "wiki_html"
    assert [chunk.chunk_type for chunk in chunks] == [
        "heading",
        "paragraph",
        "heading",
        "bullet",
        "heading",
        "bullet",
        "table_row",
        "table_row",
    ]
    assert items[0].item_type == "summary"
    assert any(item.item_type == "decision" for item in items)
    assert any(item.item_type == "action" for item in items)


def test_parse_wiki_pdf_extracts_page_items_without_real_pdf_dependency(tmp_path: Path, monkeypatch):
    pdf_path = tmp_path / "2026-07-04_confluence_sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    class FakePage:
        def __init__(self, text: str):
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakeReader:
        def __init__(self, path: str):
            assert path.endswith(".pdf")
            self.pages = [
                FakePage("增长实验周会\n决定先保留轻量审核。"),
                FakePage("行动项\n整理 PDF 导出样例。"),
            ]

    monkeypatch.setitem(sys.modules, "pypdf", types.SimpleNamespace(PdfReader=FakeReader))

    title, chunks, items, meta = parse_wiki_pdf(pdf_path)

    assert title == "增长实验周会"
    assert meta["source_kind"] == "wiki_pdf"
    assert meta["page_count"] == 2
    assert [chunk.chunk_type for chunk in chunks] == ["page", "page"]
    assert items[0].item_type == "summary"
    assert items[1].item_type in {"fact", "action", "decision"}


def test_parse_xmind_extracts_topic_tree(tmp_path: Path):
    xmind_path = tmp_path / "2026-07-04_growth_map.xmind"
    content_json = """
    [
      {
        "title": "增长实验图谱",
        "rootTopic": {
          "title": "增长实验",
          "children": {
            "attached": [
              {
                "title": "决策",
                "children": {
                  "attached": [
                    {"title": "采用 filename_first"}
                  ]
                }
              },
              {
                "title": "行动项",
                "children": {
                  "attached": [
                    {"title": "整理 xmind 导出样例"}
                  ]
                }
              }
            ]
          }
        }
      }
    ]
    """.strip()
    with zipfile.ZipFile(xmind_path, "w") as zf:
        zf.writestr("content.json", content_json)

    title, chunks, items, meta = parse_xmind(xmind_path)

    assert title == "增长实验"
    assert meta["source_format"] == "xmind"
    assert meta["topic_count"] == 5
    assert chunks[0].chunk_type == "topic"
    assert chunks[0].content == "增长实验"
    assert any(item.title == "采用 filename_first" for item in items)


def test_ingest_document_skips_unchanged_source_and_preserves_candidate_state(tmp_path: Path):
    db_path = tmp_path / "agent_history.db"
    source_path = tmp_path / "2026-07-04_meeting.md"
    source_path.write_text("摘要\n待办\n· 拉取数据@南宗帅\n", encoding="utf-8")

    title, chunks, items, metadata = parse_meeting_markdown(source_path)
    content_hash = hash_text_file(source_path)

    conn = source_ingest_store.get_db_connection(db_path)
    try:
        chunk_count, item_count = source_ingest_store.ingest_document(
            conn,
            "meeting_note",
            source_path,
            title,
            chunks,
            items,
            metadata,
            content_hash,
        )
        doc_id = conn.execute("SELECT id FROM source_documents WHERE path = ?", (str(source_path),)).fetchone()[0]
        extracted_item_id = conn.execute(
            "SELECT id FROM extracted_items WHERE document_id = ? ORDER BY rowid LIMIT 1",
            (doc_id,),
        ).fetchone()[0]
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """
            INSERT INTO knowledge_candidates
                (id, extracted_item_id, source_document_id, candidate_date, candidate_type, status,
                 title, content, confidence, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "cand_test_preserve",
                extracted_item_id,
                doc_id,
                "2026-07-04",
                "daily",
                "accepted",
                "拉取数据",
                "· 拉取数据@南宗帅",
                0.9,
                "{}",
                now,
                now,
            ),
        )
        conn.commit()

        second_chunk_count, second_item_count = source_ingest_store.ingest_document(
            conn,
            "meeting_note",
            source_path,
            title,
            chunks,
            items,
            metadata,
            content_hash,
        )
        preserved_status = conn.execute(
            "SELECT status FROM knowledge_candidates WHERE id = ?",
            ("cand_test_preserve",),
        ).fetchone()[0]
    finally:
        conn.close()

    assert (chunk_count, item_count) == (second_chunk_count, second_item_count)
    assert preserved_status == "accepted"


def test_prune_stale_candidates_removes_orphans(tmp_path: Path):
    db_path = tmp_path / "agent_history.db"
    source_path = tmp_path / "2026-07-04_meeting.md"
    source_path.write_text("摘要\n待办\n· 拉取数据@南宗帅\n", encoding="utf-8")

    title, chunks, items, metadata = parse_meeting_markdown(source_path)
    content_hash = hash_text_file(source_path)

    conn = source_ingest_store.get_db_connection(db_path)
    try:
        source_ingest_store.ingest_document(
            conn,
            "meeting_note",
            source_path,
            title,
            chunks,
            items,
            metadata,
            content_hash,
        )
        doc_id = conn.execute("SELECT id FROM source_documents WHERE path = ?", (str(source_path),)).fetchone()[0]
        extracted_item_id = conn.execute(
            "SELECT id FROM extracted_items WHERE document_id = ? ORDER BY rowid LIMIT 1",
            (doc_id,),
        ).fetchone()[0]
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """
            INSERT INTO knowledge_candidates
                (id, extracted_item_id, source_document_id, candidate_date, candidate_type, status,
                 title, content, confidence, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "cand_test_orphan",
                extracted_item_id,
                doc_id,
                "2026-07-04",
                "daily",
                "pending",
                "拉取数据",
                "· 拉取数据@南宗帅",
                0.9,
                "{}",
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    raw_conn = sqlite3.connect(db_path)
    raw_conn.execute("DELETE FROM source_documents WHERE id = ?", (doc_id,))
    raw_conn.commit()
    raw_conn.close()

    prune_conn = source_ingest_store.get_db_connection(db_path)
    try:
        generate_candidates.prune_stale_candidates(prune_conn)
        prune_conn.commit()
        remaining = prune_conn.execute(
            "SELECT COUNT(*) FROM knowledge_candidates WHERE id = ?",
            ("cand_test_orphan",),
        ).fetchone()[0]
    finally:
        prune_conn.close()

    assert remaining == 0


def test_prune_stale_candidates_removes_wrong_date_candidates(tmp_path: Path):
    db_path = tmp_path / "agent_history.db"
    source_path = tmp_path / "2026-05-14_meeting.md"
    source_path.write_text("摘要\n待办\n· 拉取数据@南宗帅\n", encoding="utf-8")

    title, chunks, items, metadata = parse_meeting_markdown(source_path)
    content_hash = hash_text_file(source_path)

    conn = source_ingest_store.get_db_connection(db_path)
    try:
        source_ingest_store.ingest_document(
            conn,
            "meeting_note",
            source_path,
            title,
            chunks,
            items,
            {
                **metadata,
                "filename_date": "2026-05-14",
                "landing_date": "2026-07-04",
            },
            content_hash,
        )
        doc_id = conn.execute("SELECT id FROM source_documents WHERE path = ?", (str(source_path),)).fetchone()[0]
        extracted_item_id = conn.execute(
            "SELECT id FROM extracted_items WHERE document_id = ? ORDER BY rowid LIMIT 1",
            (doc_id,),
        ).fetchone()[0]
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """
            INSERT INTO knowledge_candidates
                (id, extracted_item_id, source_document_id, candidate_date, candidate_type, status,
                 title, content, confidence, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "cand_wrong_date",
                extracted_item_id,
                doc_id,
                "2026-07-04",
                "daily",
                "pending",
                "拉取数据",
                "· 拉取数据@南宗帅",
                0.9,
                "{}",
                now,
                now,
            ),
        )
        conn.commit()

        generate_candidates.prune_stale_candidates(conn)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM knowledge_candidates WHERE id = ?",
            ("cand_wrong_date",),
        ).fetchone()[0]
    finally:
        conn.close()

    assert remaining == 0


def test_inject_summary_to_daily_rewrites_section_in_place(tmp_path: Path):
    daily_path = tmp_path / "2026-07-04.md"
    daily_path.write_text(
        "# 2026-07-04\n\n## AI 总结\n\n- old item\n\n## 明日计划\n\n- [ ] next\n",
        encoding="utf-8",
    )

    daily_summary.inject_summary_to_daily(daily_path, "- new item\n- next item")
    daily_summary.inject_summary_to_daily(daily_path, "- final item")
    text = daily_path.read_text(encoding="utf-8")

    assert text.count("## AI 总结") == 1
    assert "- old item" not in text
    assert "- new item" not in text
    assert "- final item" in text
    assert "## 明日计划" in text


def test_materialize_daily_candidate_is_idempotent(tmp_path: Path):
    daily_path = tmp_path / "2026-07-04.md"
    daily_path.write_text(
        "# 2026-07-04\n\n## AI 总结\n\n- summary\n",
        encoding="utf-8",
    )

    materialize_candidates.materialize_daily_candidate(
        daily_path,
        "cand_demo",
        "拉取数据",
        "拉取数据@南宗帅",
    )
    materialize_candidates.materialize_daily_candidate(
        daily_path,
        "cand_demo",
        "拉取数据",
        "拉取数据@南宗帅",
    )
    text = daily_path.read_text(encoding="utf-8")

    assert text.count("## 候选事项") == 1
    assert text.count("knowledge_candidate:cand_demo") == 1


def test_upsert_candidates_preserves_existing_review_status(tmp_path: Path):
    db_path = tmp_path / "agent_history.db"
    source_path = tmp_path / "2026-07-04_meeting.md"
    source_path.write_text("摘要\n待办\n· 拉取数据@南宗帅\n", encoding="utf-8")

    title, chunks, items, metadata = parse_meeting_markdown(source_path)
    content_hash = hash_text_file(source_path)

    conn = source_ingest_store.get_db_connection(db_path)
    try:
        source_ingest_store.ingest_document(
            conn,
            "meeting_note",
            source_path,
            title,
            chunks,
            items,
            metadata,
            content_hash,
        )
        row = next(
            row for row in generate_candidates.iter_source_rows(conn, "2026-07-04")
            if row["item_type"] in {"action", "open_loop", "decision", "fact", "summary", "topic", "risk"}
            and candidate_type_for(row["item_type"], float(row["confidence"])) is not None
        )
        generate_candidates.upsert_candidates(
            conn,
            "2026-07-04",
            [row],
            stable_candidate_id,
        )
        extracted_item_id = row["extracted_item_id"]
        conn.execute(
            "UPDATE knowledge_candidates SET status = 'accepted' WHERE extracted_item_id = ?",
            (extracted_item_id,),
        )
        conn.commit()

        generate_candidates.upsert_candidates(
            conn,
            "2026-07-04",
            [row],
            stable_candidate_id,
        )
        status = conn.execute(
            "SELECT status FROM knowledge_candidates WHERE extracted_item_id = ?",
            (extracted_item_id,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert status == "accepted"
