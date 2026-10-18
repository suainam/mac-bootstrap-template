## Agent Memory & Codebase Intelligence Hierarchy

### Architecture Overview

Agents operating across this workstation utilize a three-tier memory and intelligence stack. Each tier has a strictly delineated single source of truth (SSOT). Do not conflate code architecture with long-term semantic knowledge.

| Intelligence Tier | Backing Engine & Protocol | Scope & Responsibilities | Persistence Target |
| :--- | :--- | :--- | :--- |
| **Codebase Memory (CBM)** | Knowledge Graph + BM25 + AST (`xd://mcp__codebase_memory_mcp_*`) | **Deterministic code architecture**: functions, classes, call graphs, callers/callees, blast radius, symbol definitions. | Repository index (`.codebase-memory/` / service index) |
| **Hy-Memory PRO** | FastMCP + SQLite + Vector Embeddings (`http://10.144.10.11/mcp`) | **Long-term semantic & cross-session memory**: project architectural decisions, operational traps, domain preferences, lessons learned. | Production cluster (`qqg1299`: `/opt/dockers/hy_memory/data/`) |
| **Local Runtime Memory** | SQLite runtime database (`agent.db`) | **Transient session state**: active conversation compaction, OAuth state, ephemeral tool execution context. | Host workstation (`~/.omp/agent/agent.db` / `~/.claude/`) |

---

### Mandatory Routing Protocol

#### 1. Code & Architectural Queries ➡️ Codebase Memory (CBM)
- **Mandatory First Action**: Always query CBM (`search_graph`, `trace_path`, `query_graph`) for symbols, dependencies, and blast radius.
- **Strict Prohibition**: Never use `glob` or broad text search across repository directories before consulting CBM. If a naive file search would match >20 files, abort and use CBM.
- **Refactoring & Symbol Moves**: Cross-file references and renames must be resolved via LSP (`xd://lsp`), never manual text replacement.

#### 2. Cross-Session Decisions & Operational Pitfalls ➡️ Hy-Memory PRO
- **Write Path (`remember`)**:
  - Store non-obvious operational lessons (e.g. virtualization lock quirks, network egress throttling, reverse proxy headers).
  - Store architectural trade-offs approved by the operator.
  - Tag memory with clear repository and domain keys (e.g., `repo:auroraops-control`, `role:docker_apps`).
- **Read Path (`recall`)**:
  - When starting a task involving complex infrastructure or previously refactored services, query Hy-Memory for past traps and design decisions before proposing breaking changes.

#### 3. Ephemeral Workflow & Compaction ➡️ Local Runtime
- Context compression, temporary checkpoints, and conversational turn tokens belong in the local session.
- Do not serialize transient debug traces into Hy-Memory.

---

### Truth Boundary & Anti-Drift Rule
1. **Code Is the Ultimate SSOT**: Memory tools assist discovery, but committed repository files (`git`, `catalog/`, `CONTEXT.md`, `ports.yml`) remain the binding contract. If Hy-Memory or CBM diverges from verified file content, the live repository wins.
2. **Double Graduation**:
   - Discovered operational trap ➡️ Validate on live system ➡️ Store in Hy-Memory (`remember`) ➡️ Codify into repository documentation or Ansible task assertions.
