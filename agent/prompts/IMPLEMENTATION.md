# Prompt Library Implementation Plan

## Goal

```text
/goal 在 template/agent 下落地可复用 prompt-library 系统，集成 Fabric patterns 与 Wonderful Prompts，复用现有 ~/.agent upstream/generated-state 模式，并为未来 MCP 分发保留稳定 index 接口。
验证：运行 template/.venv/bin/python 相关语法检查，运行新增 prompt indexer 的合成 fixture pytest，运行 template pytest 回归测试，确认 make prompt-sync/prompt-index/prompt-list/doctor-agent 路径已注册。
约束：不把第三方 prompt 全量 vendored 到 template，不引入数据库作为源头，不改动无关 agent skills 分发语义，不使用系统 Python 跑本项目脚本。
边界：只修改 template/agent/prompts、template/scripts、template/Makefile、template/agent 文档、template/README、template/docs/adr、template/tests/ 下的相关测试文件。
迭代策略：先固化 registry/index/lookup 最小闭环，再接 Makefile 和 doctor，最后补 pytest；每次失败先读日志和测试输出后做聚焦修复。
完成条件：prompt registry、sync、index、lookup、文档和 pytest 验收均完成，失败或未运行项明确说明。
暂停条件：需要真实网络同步授权、外部账号、发布到远端、删除已有用户 prompt 库、或第三方许可证解释超出 MIT 明文信息时暂停。
```

## Data Model

```text
template/agent/prompts/sources.json      # source registry
~/.agent/upstream/<source>/              # cloned upstream repos
~/.agent/prompts/index.json              # generated lookup index
~/.local/bin/agent-prompt                # stable lookup helper
```

Index records keep:

- stable `source:id`
- title and format
- repo and license label
- file path plus line range for markdown sections
- Fabric pattern directory plus role files
- short preview for search/list

## Implementation Phases

1. Add prompt source registry and architecture docs.
2. Add local-only indexer for `fabric-patterns` and `markdown-sections`.
3. Add sync wrapper that clones/updates upstream repos and rebuilds the index.
4. Add lookup wrapper for `list`, `search`, `show`, and `doctor`.
5. Wire Makefile and `agent-tools` helper install.
6. Add a stdio MCP server that implements official `prompts/list` and
   `prompts/get`, plus a read-only `search_prompts` tool.
7. Add doctor visibility.
8. Add pytest coverage for config, venv Python use, MCP protocol shape, and
   synthetic end-to-end indexing.

## Design Reasons

- Markdown is the source of truth because both upstreams maintain prompts as
  markdown and Fabric itself treats markdown patterns as portable prompts.
- JSON index is inspectable, diffable, and enough for Codex lookup.
- SQLite/FTS can be generated later for MCP ranking without changing canonical
  storage.
- Keeping upstream repos under `~/.agent/upstream/` matches existing skill sync
  behavior and keeps the public template small.

## Acceptance

```bash
make -C template prompt-index
make -C template prompt-list Q=analyze
template/.venv/bin/python -m pytest template/tests -q
```

`prompt-index` requires local upstream repos. On a fresh machine, use:

```bash
make -C template prompt-sync
```
