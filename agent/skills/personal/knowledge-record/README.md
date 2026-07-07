# Knowledge Record

Project-scoped skill for writing trusted live-agent knowledge directly into
`knowledge_records`.

## Purpose

This skill owns the record contract and push-path implementation for:
- `adr`
- `card`
- `daily`

Use this skill when the agent is actively recording a curated knowledge item
into SQLite. Use `knowledge-lifecycle-manager` when you need the broader control
plane for pipeline execution, status, queue inspection, health checks, or to
delegate into this writer.

This skill is the semantic owner of the live-record contract. The lifecycle
manager may call into it, but should not redefine the field contract itself.

## Usage

```bash
# Direct writer entry
./run.sh --type adr --title "..." --content "..."

# Suggest-first entry
./run.sh suggest --thread-summary "本次会话完成了..." --action accept
```

## Suggest flow

`suggest` reads the current agent thread supplied by the calling agent, collects
repo evidence, drafts one best record, and saves only after explicit
confirmation. Humans should not need to manually provide the thread; the agent
should synthesize it from the active conversation and pass either:
- `--thread-summary`
- `--thread-json`
- `KNOWLEDGE_RECORD_THREAD_SUMMARY`
- `KNOWLEDGE_RECORD_THREAD_JSON`

Supported non-interactive confirmation actions:
- `--action accept`
- `--action cancel`
- `--action regenerate`
- `--action "edit title=新的中文标题"`
- `--action "edit tags=知识管理,记录生成"`
- `--action "edit why_record=需要保留这次沉淀。"`

Optional evidence inputs:
- `KNOWLEDGE_RECORD_THREAD_SUMMARY`
- `KNOWLEDGE_RECORD_THREAD_JSON`
- `KNOWLEDGE_RECORD_TEST_SUMMARY`
- `KNOWLEDGE_RECORD_COMMAND_SUMMARY`
- `KNOWLEDGE_RECORD_REFERENCES` separated by semicolons

Optional drafting backend:
- `KNOWLEDGE_RECORD_LLM_CMD` — command that reads the prompt from stdin and
  writes one JSON object to stdout.

The classifier still fixes the record type before drafting. If the optional LLM
command is missing, fails, or returns invalid JSON, `suggest` falls back to the
deterministic Chinese template and the strict SQLite writer remains the final
validation gate.

## Package

- `SKILL.md` — project-scoped skill metadata
- `README.md` — focused ownership note for the record contract
- `run.sh` — convenience wrapper for direct skill invocation
- `scripts/record_knowledge.py` — current push-path SQLite writer
- `scripts/suggest_record.py` — suggest/confirm/save orchestration
- `scripts/thread_capture.py` — current-thread packet capture
- `scripts/evidence_collect.py` — repo evidence collection
- `scripts/suggestion_engine.py` — rule-guided draft generation
- `scripts/confirmation_flow.py` — terminal confirmation flow
