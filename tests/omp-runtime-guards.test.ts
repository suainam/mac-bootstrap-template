import { test, expect } from "bun:test"
import usageExtension, { UsageBudget } from "../agent/omp/extensions/usage-budget"
import { OperationBoundaries, boundaryFor } from "../agent/omp/extensions/operation-boundaries"

test("generated usage warns once, pauses, and preserves session across new tasks", () => {
  const b = new UsageBudget()
  b.count({ role: "assistant", usage: { output: 3200 } })
  expect(b.warnings()).toHaveLength(1)
  expect(b.warnings()).toEqual([])
  b.count({ role: "assistant", usage: { output: 800 } })
  expect(b.blocked).toBe(true)
  b.command("task")
  expect(b.state.session).toBe(4000)
  expect(b.state.task).toBe(0)
  b.count({ role: "assistant" })
  expect(b.state.incomplete).toBe(true)
  const restored = new UsageBudget()
  expect(restored.restore(b.state)).toBe(true)
  expect(restored.state.session).toBe(4000)
  expect(restored.command("add -1 3")).toBe(false)
})

test("session cap cannot be bypassed by resetting task", () => {
  const b = new UsageBudget()
  b.count({ role: "assistant", usage: { output: 30000 } })
  b.command("task")
  expect(b.blocked).toBe(true)
  b.command("add 0 100")
  expect(b.blocked).toBe(false)
})

test("normal auth passes, sensitive calls require one operator grant", () => {
  const g = new OperationBoundaries(); g.switchSession("one")
  const call = (command: string) => ({ toolName: "bash", input: { command } })
  expect(g.check(call("gh auth status"))).toBeUndefined()
  expect(g.check(call("gh issue create --body-file draft"))).toBeUndefined()
  expect(g.check(call("security dump-keychain"))?.block).toBe(true)
  g.allow("credentials")
  expect(g.check(call("security dump-keychain"))).toBeUndefined()
  expect(g.check(call("security find-generic-password -s gh -w"))?.block).toBe(true)
  g.allow("credentials"); g.switchSession("two")
  expect(g.check(call("security dump-keychain"))?.block).toBe(true)
})

test("isolated browser allowed, explicit profile and adoption guarded", () => {
  const check = (command: string) => boundaryFor({ toolName: "bash", input: { command } })
  expect(check("agent-browser --session diagnostic open https://example.com")).toBeUndefined()
  expect(check("agent-browser --profile='Default' open https://example.com")).toBe("browser")
  expect(check('agent-browser --profile "Default" open https://example.com')).toBe("browser")
  expect(boundaryFor({ toolName: "eval", input: { code: 'browser.open({app:{relay:true}})' } })).toBe("browser")
})

test("lifecycle aggregates child output once and refuses over-budget input/spawns", async () => {
  type Handler = (...args: unknown[]) => unknown
  const handlers = new Map<string, Handler>()
  const listeners = new Map<string, Handler>()
  const entries: unknown[] = []
  let aborted = 0
  const ctx = {
    sessionManager: { getSessionId: () => "main", getEntries: () => entries },
    abort: () => { aborted++ }, ui: { notify: () => {} },
  }
  const api = {
    on: (name: string, fn: Handler) => { handlers.set(name, fn) },
    appendEntry: (customType: string, data: unknown) => { entries.push({ type: "custom", customType, data }) },
    sendMessage: () => {}, registerCommand: () => {},
    events: { on: (name: string, fn: Handler) => { listeners.set(name, fn); return () => {} } },
  }
  // Harness implements only the extension's consumed host interfaces.
  const host = api as unknown as Parameters<typeof usageExtension>[0]
  usageExtension(host)
  await handlers.get("session_start")!({}, ctx)
  const child = { id: "child", event: { type: "message_end", message: { role: "assistant", timestamp: 1, usage: { output: 4000 } } } }
  await listeners.get("task:subagent:event")!(child)
  const first = entries.length
  await listeners.get("task:subagent:event")!(child)
  expect(entries.length).toBe(first)
  expect(aborted).toBe(1)
  expect(await handlers.get("input")!({}, ctx)).toEqual({ action: "handled" })
  expect(await handlers.get("before_subagent_spawn")!({}, ctx)).toMatchObject({ block: true })
})
