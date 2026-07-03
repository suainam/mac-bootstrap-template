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
