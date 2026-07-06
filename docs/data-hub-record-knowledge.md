# lifecycle-manager record — Design

## Motivation

Agent 在当前对话里确认的决策、知识卡片和日报事项，应直接进入
`knowledge_records`。这条 Push 路径不依赖历史材料提炼、候选审核或
`auto_review`，避免把“现在/未来”的知识混进历史归纳链路。

## Architecture

```text
knowledge-lifecycle-manager record
  -> knowledge_records (status=accepted, record_revision=kr-v1)
  -> render_obsidian / materialize_candidates.py
  -> Obsidian vault (daily / adr / card)
```

`knowledge_records` 是当前可信知识主表；`knowledge_candidates` 只承接
archive/history lane 的候选结果。旧候选可以继续存在，但新渲染主路径应以
`knowledge_records.record_revision IS NOT NULL` 作为新契约准入标记。

## Schema Contract

`knowledge_records` 保留原有字段，并增加新三层契约字段：

| Field | Default | Purpose |
|-------|---------|---------|
| `record_revision` | `kr-v1` | 新契约准入标记 |
| `authority` | `trusted_agent` | 记录可信来源 |
| `source_kind` | `live_agent` | 区分 live push / archive import |
| `source_fingerprint` | generated | 幂等与排查用输入指纹 |
| `raw_refs_json` | `[]` | 可追溯引用集合 |

Render 状态不写回知识主字段，统一进入 `materializations`：

| Field | Purpose |
|-------|---------|
| `projection_key` | `record_id + projection_type + logical_target + block_id` 当前投影身份 |
| `template_version` | 当前模板版本 |
| `input_fingerprint` | 本次投影输入集合指纹 |
| `state_watermark` | 同一 SQLite 快照中的状态水位 |

## File Layout

```text
template/agent/skills/personal/knowledge-lifecycle-manager/
├── SKILL.md
├── README.md
├── run.sh
└── scripts/
    ├── manager.py
    ├── manager_reporting.py
    └── record_knowledge.py
```

## Usage

```bash
template/.venv/bin/python \
  template/agent/skills/personal/knowledge-lifecycle-manager/scripts/manager.py \
  record \
  --type adr \
  --title "知识记录测试" \
  --content "这是手动创建的测试记录。" \
  --tags "测试" \
  --date "$(date +%F)"
```

Verify:

```bash
sqlite3 "$AGENT_DB_PATH" \
  "SELECT id, record_type, title, record_revision, authority, source_kind FROM knowledge_records ORDER BY created_at DESC LIMIT 5"
```
