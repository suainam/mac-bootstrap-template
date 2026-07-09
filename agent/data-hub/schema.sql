-- Agent Data Hub Schema

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,             -- 唯一标识符，例如 agent 返回的会话 id，或者是根据时间生成的 hash
    agent_type TEXT NOT NULL,        -- 'claude', 'codex', 'agy'
    project_path TEXT,               -- 工作目录
    start_time DATETIME NOT NULL,    -- 会话创建时间
    updated_at DATETIME NOT NULL,    -- 最后更新时间
    summary TEXT                     -- 会话摘要（可选，留作后用）
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    role TEXT NOT NULL,              -- 'user', 'assistant'
    content TEXT NOT NULL,           -- 去噪后的文本内容
    raw_payload TEXT,                -- 备用：原始 JSON payload（可用来恢复详细调用）
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- 全文搜索虚拟表 (FTS5) 用于快速检索用户提问和总结
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    session_id UNINDEXED
);

-- 触发器：当向 messages 插入数据时，自动同步到 fts 表
CREATE TRIGGER IF NOT EXISTS after_message_insert
AFTER INSERT ON messages
BEGIN
    INSERT INTO messages_fts(rowid, content, session_id)
    VALUES (new.id, new.content, new.session_id);
END;

CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);

CREATE TABLE IF NOT EXISTS source_documents (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,       -- meeting_note / mind_map / wiki_page / import_doc
    title TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    content_hash TEXT NOT NULL,
    version_tag TEXT,
    captured_at DATETIME NOT NULL,
    parser_version TEXT NOT NULL,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_type TEXT NOT NULL,        -- paragraph / bullet / topic / summary
    locator TEXT,
    content TEXT NOT NULL,
    metadata_json TEXT,
    FOREIGN KEY(document_id) REFERENCES source_documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS extracted_items (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    chunk_id TEXT,
    item_type TEXT NOT NULL,         -- fact / decision / action / risk / topic / open_loop
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'candidate',
    metadata_json TEXT,
    FOREIGN KEY(document_id) REFERENCES source_documents(id) ON DELETE CASCADE,
    FOREIGN KEY(chunk_id) REFERENCES document_chunks(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_source_documents_type ON source_documents(source_type);
CREATE INDEX IF NOT EXISTS idx_document_chunks_doc ON document_chunks(document_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_extracted_items_doc ON extracted_items(document_id, item_type);

CREATE TABLE IF NOT EXISTS knowledge_candidates (
    id TEXT PRIMARY KEY,
    extracted_item_id TEXT NOT NULL UNIQUE,
    source_document_id TEXT NOT NULL,
    candidate_date TEXT NOT NULL,    -- YYYY-MM-DD review bucket
    candidate_type TEXT NOT NULL,    -- daily / adr / card
    status TEXT NOT NULL DEFAULT 'pending', -- pending / accepted / rejected / merged / deferred
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    metadata_json TEXT,
    review_note TEXT,
    materialized_path TEXT,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    FOREIGN KEY(extracted_item_id) REFERENCES extracted_items(id) ON DELETE CASCADE,
    FOREIGN KEY(source_document_id) REFERENCES source_documents(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_knowledge_candidates_date ON knowledge_candidates(candidate_date, status);
CREATE INDEX IF NOT EXISTS idx_knowledge_candidates_type ON knowledge_candidates(candidate_type, status);

-- Skill-recorded knowledge (agent writes directly, bypassing pipeline)
CREATE TABLE IF NOT EXISTS knowledge_records (
    id TEXT PRIMARY KEY,
    record_type TEXT NOT NULL CHECK(record_type IN ('adr', 'card', 'daily')),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    background TEXT,
    tags TEXT,
    impact TEXT CHECK(impact IN ('high', 'medium', 'low')),
    is_actionable INTEGER NOT NULL DEFAULT 0,
    references_json TEXT,
    project TEXT,
    expires_at TEXT,
    why_record TEXT,
    agent_type TEXT NOT NULL,
    session_id TEXT,
    message_id INTEGER,
    project_path TEXT,
    recorded_at TEXT NOT NULL,
    candidate_date TEXT NOT NULL,
    materialized_path TEXT,
    status TEXT NOT NULL DEFAULT 'accepted',
    record_revision TEXT,
    authority TEXT,
    source_kind TEXT,
    source_fingerprint TEXT,
    raw_refs_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kr_date ON knowledge_records(candidate_date, status);
CREATE INDEX IF NOT EXISTS idx_kr_type ON knowledge_records(record_type, status);
CREATE INDEX IF NOT EXISTS idx_kr_revision ON knowledge_records(record_revision);

CREATE TABLE IF NOT EXISTS materializations (
    projection_key TEXT PRIMARY KEY,
    record_id TEXT NOT NULL,
    projection_type TEXT NOT NULL,
    logical_target TEXT NOT NULL,
    block_id TEXT NOT NULL,
    target_path TEXT,
    template_version TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    state_watermark TEXT NOT NULL,
    rendered_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'rendered',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(record_id) REFERENCES knowledge_records(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_materializations_record ON materializations(record_id, projection_type);

-- Execution log table for pipeline traceability
CREATE TABLE IF NOT EXISTS execution_log (
    id TEXT PRIMARY KEY,
    execution_date TEXT NOT NULL,
    step_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed')),
    records_affected INTEGER,
    error_message TEXT,
    metadata_json TEXT,
    UNIQUE(execution_date, step_name, started_at)
);

CREATE INDEX IF NOT EXISTS idx_execution_log_date ON execution_log(execution_date, status);
CREATE INDEX IF NOT EXISTS idx_execution_log_step ON execution_log(step_name, started_at DESC);

-- Durable workflow run state for resumable industrialized execution.
CREATE TABLE IF NOT EXISTS workflow_runs (
    id TEXT PRIMARY KEY,
    workflow_name TEXT NOT NULL,
    target_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed', 'degraded')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    max_attempts INTEGER NOT NULL DEFAULT 1,
    resumed_from_run_id TEXT,
    error_message TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_workflow_runs_date ON workflow_runs(target_date, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_status ON workflow_runs(status, started_at DESC);

CREATE TABLE IF NOT EXISTS workflow_steps (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    step_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'running', 'completed', 'failed', 'skipped', 'degraded')),
    attempt INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    completed_at TEXT,
    exit_code INTEGER,
    command_json TEXT NOT NULL,
    produces_json TEXT NOT NULL,
    stdout_path TEXT,
    stderr_path TEXT,
    input_hash TEXT,
    output_hash TEXT,
    error_message TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE,
    UNIQUE(run_id, step_index)
);

CREATE INDEX IF NOT EXISTS idx_workflow_steps_run ON workflow_steps(run_id, step_index);
CREATE INDEX IF NOT EXISTS idx_workflow_steps_status ON workflow_steps(status, started_at DESC);

CREATE TABLE IF NOT EXISTS artifact_manifest (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    step_id TEXT,
    artifact_path TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    content_hash TEXT,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(step_id) REFERENCES workflow_steps(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_artifact_manifest_run ON artifact_manifest(run_id, created_at);

CREATE TABLE IF NOT EXISTS backup_log (
    id TEXT PRIMARY KEY,
    run_id TEXT,
    backup_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('completed', 'failed')),
    error_message TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(run_id) REFERENCES workflow_runs(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_backup_log_created ON backup_log(created_at DESC);

CREATE TABLE IF NOT EXISTS summary_runs (
    id TEXT PRIMARY KEY,
    summary_level TEXT NOT NULL CHECK(summary_level IN ('daily', 'weekly', 'monthly', 'quarterly', 'yearly')),
    period_id TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    source_mode TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed')),
    output_path TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_summary_runs_level_period ON summary_runs(summary_level, period_id);
CREATE INDEX IF NOT EXISTS idx_summary_runs_status ON summary_runs(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS summary_run_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(run_id) REFERENCES summary_runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_summary_run_sources_run ON summary_run_sources(run_id);
