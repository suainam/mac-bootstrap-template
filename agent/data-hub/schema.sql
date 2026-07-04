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
