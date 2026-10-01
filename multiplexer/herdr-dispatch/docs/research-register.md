# Absorbed research register

What fed this design, and where each finding landed. Split by cost: items cheap
enough to land went into the branch; items needing host progress are tracked as
issues so the knowledge is not lost.

## Landed in `feat/dispatch-plugin`

| Finding | Source | Where |
|---|---|---|
| `deliverAs: "aside"` injects at the next step boundary without interrupting a live turn | omp extension docs | `notify.ts`, `[NOTIFY]` consumption |
| `session_stop` supports `{continue}` and `{decision:"block"}` with human-only crossing | omp extension docs | `human_gate` guard in `index.ts` |
| `ctx.setInterval` is isolated; a raw timer throw is a fatal `uncaughtException` that tears down the session | omp extension docs | every timer; enforced by a source-level test |
| `before_subagent_spawn` fires once per child, before the child resolves a model | omp extension docs | `RouterCursor` keyed on `spawnKey` |
| Extensions cannot write the session todo list (`set_todos` is an RPC host command) | omp extension + RPC docs | documented limitation; guard implemented as a corrective steer |
| Herdr has a full Plugin v1 surface (`herdr-plugin.toml`, `plugin.*` socket methods) | Herdr 0.9.3 docs | `herdr-plugin.toml`, `dispatch_plugin.py` |
| `pane.report_metadata` is display-only; `pane.report_agent` is owned by the agent's integration | Herdr socket API | single-writer audit gate |
| `agent.view.set` has no CLI wrapper and replaces `ui.agent_panel_sort` while active | Herdr socket API | opt-in projection, off by default |
| `resume_argv` is only accepted from an agent that already holds the pane | Herdr socket API | dispatch records and validates; `herdr:omp` attaches |
| Upstream `bestony/herdr-dispatch` ships no TUI; observability is a disk probe plus text | upstream README | plain-text board, no widget framework |
| Upstream `_shared/{plan,supervise}` + per-agent driver structure | upstream README | skill family convergence |
| Context and memory governance (pruning, rollover, downgrading, host pressure) | pi 0.99 findings | `governance.ts`, `docs/memory-governance.md` |

## Tracked as issues

| # | Item | Why it is not landed yet |
|---|---|---|
| [#118](https://github.com/suainam/mac-bootstrap-template/issues/118) | Register `xd://dispatch` as a virtual device bus | Namespace shape is a host-surface decision; landing it now would freeze an unstable contract |
| [#119](https://github.com/suainam/mac-bootstrap-template/issues/119) | Consolidate routing onto `registerVirtualModel` | Precedence semantics are not yet stable; the current `before_subagent_spawn` handler keeps working meanwhile |
| [#120](https://github.com/suainam/mac-bootstrap-template/issues/120) | Two-layer elastic concurrency across omp workpool and Herdr lanes | Needs one shared admission budget; risk of reintroducing a blocking wait that would break fire-and-yield |

## The through-line

Nearly every finding landed as a *guard* rather than a feature. That is the
pattern worth keeping:

- a second writer does not fail loudly, so state ownership is enforced by a gate
- a todo reminder does not announce itself as harm, so the park refuses to be
  woken by anything but a real report
- a heartbeat and a result look similar, so they are distinct markers and only
  one of them ends a park
- memory pressure and a stalled pane look similar, so they are separate policies
  with separate responses

The features were the easy part. The guards are what make the features safe to
run unattended.