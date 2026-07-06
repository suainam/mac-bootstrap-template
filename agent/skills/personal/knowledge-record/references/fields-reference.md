# Fields Reference

All fields map to columns in `knowledge_records` table.

## Required (`--type`, `--title`, `--content`)

### `--type` `adr|card|daily`

See `type-guide.md` for selection guidance.

### `--title`

Line-length title (≤80 chars preferred).  Describes *what* the knowledge is
about, not *why* (that goes in content).

```
ADR: 用 Rust 重写认证核心模块
Card: macOS 上 Homebrew/Pyenv 共存时的 pip 问题
Daily: 2026-07-05 API 分页方案决策
```

### `--content`

Full text of the knowledge artifact.  Markdown supported.

## Optional Metadata

### `--background`

The user's original question or the trigger event.  Preserves context.

> 用户问：认证系统性能瓶颈怎么解决？
> 用户问：怎么在 Mac 上同时用 Homebrew 和 pyenv 的 Python？

### `--tags`

Comma-separated list.  Supports Obsidian tag queries.

```
架构,Rust,性能优化
踩坑,Homebrew,Python,macOS
Clash,CorpLink,DNS,TUN
```

### `--impact` `high|medium|low`

Subjective importance rating.

- `high` — 影响后续系统性决策
- `medium` — 值得注意但非紧要
- `low` — 纯备忘

### `--is-actionable`

Flag this record as containing a todo/follow-up.  These can be extracted by
pipeline later.

### `--references`

Comma-separated file paths or URLs that the knowledge refers to.

```
auth/main.py,auth/Cargo.toml
https://doc.rust-lang.org/book/
```

### `--project`

Override the auto-detected project name.  Defaults to CWD basename.

### `--expires-at`

ISO date when the knowledge becomes stale.  `2026-12-31`.

### `--why-record`

Agent's stated reason for recording.  Helps transparency in review logs.

## Auto-Filled (not passed by agent)

| Field | Source |
|-------|--------|
| `id` | SHA256(title+content+agent+timestamp) |
| `agent_type` | `$OPENCODE_AGENT` / `$CODEX_AGENT` / empty |
| `session_id` | `$SESSION_ID` / empty |
| `project_path` | `os.getcwd()` |
| `recorded_at` | `datetime.now().isoformat()` |
| `candidate_date` | today's date (overridable via `--date`) |
| `status` | `accepted` (always) |
