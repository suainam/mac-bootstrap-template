# knowledge-record Skill — Design

## Motivation

Existing knowledge pipeline extracts knowledge *after* the conversation via
`classify_chat_response` / `llm_filter` / `auto_review`. This "Pull" model
loses most chat content to conservative classification and hard-coded skip
rules.

The **Push** model lets the agent write knowledge directly to SQLite *during*
the conversation, skipping the unreliable pipeline steps.

## Architecture

```
Agent (skill-record) ──→ knowledge_records (status=accepted)
                                  ↓
                         materialize_candidates.py
                                  ↓
                         Obsidian vault (daily/adr/card)
```

## Partitioning

`knowledge_records` is a **separate table** from `knowledge_candidates`:

| Aspect | `knowledge_candidates` | `knowledge_records` |
|--------|------------------------|---------------------|
| Producer | Pipeline (auto-review) | Agent skill (manual) |
| Status flow | pending → accepted/accepted | accepted only |
| Foreign keys | `extracted_items` + `source_documents` | None (agent writes) |
| Cleanup safety | `DELETE FROM knowledge_candidates` | Never caught by cleanup |
| Schema | Fixed (refs pipeline objects) | Optimized for agent fields |

Cleanup scripts target `knowledge_candidates` only; skill records always
survive.

## `knowledge_records` Schema

```sql
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
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

## Field Reference

| Field | Required | Description |
|-------|----------|-------------|
| `id` | auto | Content-hash based UUID (冪等) |
| `record_type` | yes | `adr`, `card`, or `daily` |
| `title` | yes | 知识标题 |
| `content` | yes | 知识正文 |
| `background` | no | 触发该知识的用户原始问题 |
| `tags` | no | 逗号分隔的标签 |
| `impact` | no | `high/medium/low` |
| `is_actionable` | no | 是否为待办事项 |
| `references_json` | no | 引用的文件路径 JSON 数组 |
| `project` | no | 所属项目 |
| `expires_at` | no | 过期时间 |
| `why_record` | no | Agent 自述记录理由 |
| `agent_type` | auto | 从环境推断 |
| `session_id` | auto | 会话标识 |
| `message_id` | auto | 消息序号 |
| `project_path` | auto | CWD |
| `recorded_at` | auto | 记录时间 |
| `candidate_date` | auto | 所属知识日期 |
| `materialized_path` | pipeline | Obsidian 落地路径 |

## File Layout

```
template/agent/skills/personal/knowledge-record/
├── SKILL.md
├── EXAMPLES.md
├── references/
│   ├── type-guide.md
│   └── fields-reference.md
└── scripts/
    └── record_knowledge.py
```

## Distribution

- `skills-distribution.json`: `"knowledge-record": {}` → 继承 `defaults.apps` = 全量 agent
- `skills-manifest.json`: `global_skills` 列表 → 全局可用

## Testing

```bash
# Record a test entry
python template/agent/skills/personal/knowledge-record/scripts/record_knowledge.py \
  --type adr \
  --title "知识记录测试" \
  --content "这是手动创建的测试记录。" \
  --tags "测试"

# Verify in SQLite
sqlite3 /tmp/test-hub.db "SELECT id, record_type, title, created_at FROM knowledge_records"

# Run materialization (dry date)
python template/agent/data-hub/materialize_candidates.py $(date +%F)
```
