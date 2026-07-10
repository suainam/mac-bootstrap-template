import sys
from pathlib import Path

# 添加脚本目录到 sys.path
scripts_dir = Path(__file__).parent.parent / "agent" / "data-hub"
sys.path.insert(0, str(scripts_dir))
sys.path.insert(0, str(scripts_dir / "scripts"))

import ingest_logs
from db_helper import get_db_connection

def test_clean_xml_tags():
    text_with_metadata = "Hello <ADDITIONAL_METADATA>some metadata</ADDITIONAL_METADATA> World"
    assert ingest_logs.clean_xml_tags(text_with_metadata) == "Hello  World"

    text_with_settings = "Test <USER_SETTINGS_CHANGE>settings changed</USER_SETTINGS_CHANGE> Passed"
    assert ingest_logs.clean_xml_tags(text_with_settings) == "Test  Passed"

    text_with_html = "<USER_REQUEST>This is a request</USER_REQUEST>"
    assert ingest_logs.clean_xml_tags(text_with_html) == "This is a request"

def test_is_system_boilerplate():
    assert ingest_logs.is_system_boilerplate("你是一名资深产品数据分析师的工作助理。今天是...") == True
    assert ingest_logs.is_system_boilerplate("The user changed their mind") == True
    assert ingest_logs.is_system_boilerplate("# AGENTS.md instructions for...") == True
    assert ingest_logs.is_system_boilerplate(">>> TRANSCRIPT START") == True
    assert ingest_logs.is_system_boilerplate("System: context injected") == True
    
    # Valid user messages
    assert ingest_logs.is_system_boilerplate("帮我跑一下 docker images") == False
    assert ingest_logs.is_system_boilerplate("修改为 sqlite 存储") == False

def test_compute_hash():
    h1 = ingest_logs.compute_hash("test string")
    h2 = ingest_logs.compute_hash("test string")
    h3 = ingest_logs.compute_hash("different string")
    
    assert h1 == h2
    assert h1 != h3

def test_schema_includes_durable_workflow_tables(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "agent_history.db"))
    conn = get_db_connection()
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        conn.close()

    assert {"workflow_runs", "workflow_steps", "artifact_manifest", "backup_log"} <= tables
