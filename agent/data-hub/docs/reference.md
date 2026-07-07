# Data Hub 参考手册

> 目录约定、环境变量、Obsidian 插件、幂等性约定。

## 目录约定

### Obsidian Vault 结构

```text
~/work/knowledge/
├── 00_System/    Templates/ · Dashboards/ · Reports/
├── 10_Periodic/  Daily/ · Weekly/ · Monthly/ · Quarterly/ · Yearly/
├── 20_Projects/
├── 30_Areas/
├── 40_Knowledge/ ADR/ · Cards/ · Methods/ · Metrics/ · Playbooks/ · Wiki/
├── 50_Sources/   Meetings/ · Wiki-Clips/ · Mindmaps/ · Imports/
├── 60_Inbox/     Candidates/ · Review-Queue/
└── 90_Archive/
```

### 外部材料放法

放入 `~/work/knowledge/50_Sources/<family>/`，命名带日期前缀：

```
2026-07-04_weekly-sync_product.md
2026-07-04_data-hub-architecture.md
2026-07-04_growth-analysis.xmind
2026-07-04_vendor-brief.pdf
2026-07-04_confluence-export.html
```

若文件名以 `YYYY-MM-DD_` 开头，按该日期归入对应日报；否则按首次落库日期归入。

### 机器处理层

```text
~/work/data/agent-hub/
├── db/            SQLite 账本
├── ingest/
├── parsed/
├── extracted/
├── review-packets/
└── logs/
```

`knowledge/` 给人和 Obsidian 用；`data/agent-hub/` 给脚本和中间产物。

## 运行配置

主配置文件：`private/agent/data_hub.runtime.jsonc`，公开样例：
`template/agent/data-hub/data_hub.runtime.jsonc.example`。

该文件集中管理：

- `paths`：repo、template、data-hub、SQLite、vault、runs、Git 搜索根
- `sources.inputs`：会议纪要、思维导图、Wiki 等来源目录和文件 pattern
- `agent_logs`：Claude/Codex/OpenCode/AGY 日志目录
- `llm`：`llm_filter.py` 使用的有序 LLM backend fallback 列表和过滤阈值
- `workflow`：durable workflow 默认参数

不要再新增 `.env` 或 LLM-only 配置文件。

| 配置键 | 说明 |
|------|------|
| `paths.vault_dir` | Vault 根目录 |
| `paths.daily_dir` | 日报子目录（相对 Vault） |
| `paths.git_search_roots` | Git 活动搜索根，逗号分隔 |
| `paths.db_path` | SQLite 账本绝对路径 |
| `paths.runs_dir` | durable workflow stdout/stderr 日志目录，默认在 DB 同级 `runs/` |
| `sources.inputs` | 外部材料来源目录和文件 pattern |
| `agent_logs` | Claude/Codex/OpenCode/AGY 日志目录 |
| `llm.backends` | 有序 LLM fallback 列表 |

优先级：调用命令时显式传入的 shell 环境变量 > `data_hub.runtime.jsonc` > 代码默认值。隔离验收、临时 DB、临时 vault 或 CI 环境应使用显式 env，避免误读真实
`~/work/knowledge` 或 private DB。

### LLM backend 配置契约

`llm_filter.py` 只消费 `llm.backends` 这一个 backend 列表。它支持两类 backend：

- `openai_api`：必须提供 `base_url`、`model`，可选 `api_key`、`timeout`
- `*_cli`：如 `opencode_cli`、`codex_cli`、`agy_cli`、`claude_cli`，只需要 `name`/`kind`，可选 `timeout`

`api_key` 支持两种写法：

```json
{
  "name": "freellmapi-qwen3",
  "kind": "openai_api",
  "base_url": "http://10.0.103.217:3001/v1",
  "api_key": "real-secret-in-private-repo",
  "model": "Qwen/Qwen3.6-35B-A3B"
}
```

或：

```json
{
  "name": "freellmapi-qwen3",
  "kind": "openai_api",
  "base_url": "http://10.0.103.217:3001/v1",
  "api_key": "$DATA_HUB_LLM_API_KEY_FREELLMAPI_QWEN3",
  "model": "Qwen/Qwen3.6-35B-A3B"
}
```

约束：

- private 仓库内可以直接存字面量密钥；loader 不要求必须走环境变量
- 若写成 `$ENV_VAR` 占位符，运行时会先做环境变量展开；环境变量未设置时，原字符串会原样保留，最终多半表现为鉴权失败
- 同一个 backend 对象里不要同时写两次 `api_key`；JSON 解析会保留最后一个值，前一个会被静默覆盖
- `call_llm_raw()` 和结构化筛选共用同一 backend 顺序，因此改动 `llm.backends` 会同时影响 `daily_summary.py`、`weekly_summary.py` 和 `generate_candidates.py`

### `llm_filter.py` 职责边界

`llm_filter.py` 是 data-hub 内部共用能力，不是仓库级通用 SDK。它提供两条能力面：

- 结构化筛选：`score_one()` / `filter_candidates_batch()`，要求 backend 返回完整 `FilterResult` JSON schema；无效 JSON、HTML 错误页、缺字段响应都会触发 fallback
- 自由文本生成：`call_llm_raw()`，给 `daily_summary.py` / `weekly_summary.py` 复用同一条 backend 链，只要求拿到首个非空文本

它不负责 prompt 设计、workflow retry、SQLite 持久化或 Obsidian 写回；这些职责分别留在调用脚本和 workflow 层。

## Obsidian 插件约定

插件目录必须与 Vault 结构保持一致：

| 插件 | 目录 |
|------|------|
| daily-notes | `10_Periodic/Daily` |
| periodic-notes | `10_Periodic/{Daily,Weekly,Monthly,Quarterly,Yearly}` |
| templates | `00_System/Templates` |
| templater | `00_System/Templates` |

如果 Obsidian 表现异常，优先检查：
- `.obsidian/daily-notes.json`
- `.obsidian/templates.json`
- `.obsidian/plugins/periodic-notes/data.json`
- `.obsidian/plugins/templater-obsidian/data.json`

### Dataview 路径约定（2026-07-05 修复）

周报/月报/季报/年报模板用 `dv.pages('"文件夹路径"')` 聚合日报时，**必须使用完整大写路径，不能用小写缩写**：

| 模板 | 正确查询 | 错误写法（大小写不匹配，返回空） |
|------|---------|-------------------------------|
| `weekly.md` | `dv.pages('"10_Periodic/Daily"')` | `dv.pages('"daily"')` |
| `monthly.md` | `dv.pages('"10_Periodic/Daily"')` + `dv.pages('"10_Periodic/Weekly"')` | `dv.pages('"daily"')` |
| `quarterly.md` | `dv.pages('"10_Periodic/Monthly"')` | `dv.pages('"monthly"')` |
| `yearly.md` | `dv.pages('"10_Periodic/Quarterly"')` | `dv.pages('"quarterly"')` |

Dataview 按文件夹路径过滤时**区分大小写**；vault 实际目录是 `Daily/`（大写），小写路径永远返回空集合。

## Canonical State vs Projection

数据层有两种角色，不能混淆：

| 角色 | 实体 | 特性 |
|------|------|------|
| **Canonical State** | SQLite（`agent_history.db`） | 唯一真相，只增不删（除孤儿清理），所有状态以此为准 |
| **Projection** | Obsidian vault 笔记 | 可由 SQLite 重建，允许被 LLM/人工覆盖，不是 source of truth |

推论：
- Obsidian 日报、ADR、Cards — 丢了可重建，跑 `materialize_candidates.py` 还原
- SQLite 里的 `review_action`（accept/reject）— 不可从 vault 反推，必须备份 DB
- `generate_candidates.py` 生成的 review markdown — 是 Projection，幂等重写无损；来源包括外部材料 extracted items 和 assistant chat response claims

备份策略：只需备份 `AGENT_DB_PATH`，vault 内容可重建。

## Durable Workflow State

工业化运行新增 4 类状态表：

| 表 | 用途 |
|----|------|
| `workflow_runs` | workflow 级 run_id、状态、日期、错误 |
| `workflow_steps` | step 级 attempt、exit_code、日志路径、输入/输出 hash |
| `artifact_manifest` | stdout/stderr 等产物登记 |
| `backup_log` | SQLite 备份路径、checksum、结果 |

`execution_log` 保留给单个脚本内部记录；`workflow_*` 负责跨脚本编排和恢复。

## 幂等性约定

| 脚本 | 幂等策略 |
|------|---------|
| `ingest_logs.py` | SQLite 按现有去重/增量逻辑，不重复写入 |
| `ingest_sources.py` | source 未变化直接跳过；变化时重建该 document 的 chunks/items |
| `generate_candidates.py` | 对 `extracted_item_id` 做 upsert；assistant replies 会生成 `chat_response/chat-answer-v2` 投影并保持 pending；旧 `chat_message/chat-claim-v1` 用户提问投影会被清理；markdown 审核清单每次整文件重写 |
| `auto_review.py` | 外部材料按阈值自动 accepted；chat response candidates 一律 skipped，必须人工审核 |
| `daily_summary.py` | 只重写 `## AI 总结` 一节，不重复追加 |
| `materialize_candidates.py` | `daily` 依赖 `<!-- knowledge_candidate:<id> -->` marker 防重复；`adr/card` 依赖 frontmatter `candidate_id` 防重复 |

层级职责：
- `SQLite` = 状态账本（唯一真相）
- `候选 review markdown` = 可重建视图
- `Obsidian materialized note` = 带 trace id 的投影层
