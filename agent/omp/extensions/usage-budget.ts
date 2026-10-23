import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent"

const ENTRY = "generated-usage-budget"
export const DEFAULT_TASK_LIMIT = 50_000
export const DEFAULT_SESSION_LIMIT = 500_000
// Infinity serializes to null through entry persistence; restore() maps any
// non-integer limit back to Infinity so a disabled budget stays disabled
// across compaction and session switch.

type CountedMessage = { role?: string; usage?: { output?: number }; timestamp?: number }
type Snapshot = {
  task: number; session: number; taskLimit: number; sessionLimit: number
  incomplete: boolean; taskWarned: boolean; sessionWarned: boolean
}
export class UsageBudget {
  state: Snapshot = {
    task: 0, session: 0, taskLimit: DEFAULT_TASK_LIMIT, sessionLimit: DEFAULT_SESSION_LIMIT,
    incomplete: false, taskWarned: false, sessionWarned: false,
  }
  restore(value: unknown) {
    if (!value || typeof value !== "object") return false
    const s = value as Snapshot
    if (![s.task, s.session].every(n => Number.isSafeInteger(n) && n >= 0)) return false
    if (![s.taskLimit, s.sessionLimit].every(n => typeof n === "number" || n === null)) return false
    if (![s.incomplete, s.taskWarned, s.sessionWarned].every(b => typeof b === "boolean")) return false
    this.state = {
      ...s,
      taskLimit: Number.isSafeInteger(s.taskLimit) && s.taskLimit! >= 0 ? s.taskLimit! : Infinity,
      sessionLimit: Number.isSafeInteger(s.sessionLimit) && s.sessionLimit! >= 0 ? s.sessionLimit! : Infinity,
    }
    return true
  }
  count(message: CountedMessage | undefined) {
    if (message?.role !== "assistant") return
    const output = message.usage?.output
    if (typeof output !== "number" || !Number.isSafeInteger(output) || output < 0) this.state.incomplete = true
    else { this.state.task += output; this.state.session += output }
  }
  get blocked() { return this.state.task >= this.state.taskLimit || this.state.session >= this.state.sessionLimit }
  get disabled() { return this.state.taskLimit === Infinity && this.state.sessionLimit === Infinity }
  warnings() {
    const out: string[] = []
    if (this.disabled) return out
    for (const key of ["task", "session"] as const) {
      const flag = key === "task" ? "taskWarned" : "sessionWarned"
      const limit = key === "task" ? this.state.taskLimit : this.state.sessionLimit
      if (!this.state[flag] && this.state[key] >= limit * 0.8) {
        this.state[flag] = true; out.push(`${key} generated tokens: ${this.state[key]}/${limit}`)
      }
    }
    return out
  }
  status() {
    const s = this.state
    const fmt = (n: number) => n === Infinity ? "off" : String(n)
    return `Generated-token budget: task ${s.task}/${fmt(s.taskLimit)}; session ${s.session}/${fmt(s.sessionLimit)}` +
      (s.incomplete ? "; accounting incomplete" : "") +
      (this.blocked ? "; PAUSED. Operator: /usage-budget add TASK SESSION, /usage-budget task for a new task, or /usage-budget disable." : "")
  }
  command(args: string) {
    const words = args.trim().split(/\s+/)
    if (words[0] === "task" && words.length === 1) {
      this.state.task = 0
      if (this.state.taskLimit !== Infinity) this.state.taskLimit = DEFAULT_TASK_LIMIT
      this.state.taskWarned = false
    } else if (words[0] === "add" && words.length === 3 && words.slice(1).every(s => /^\d+$/.test(s))) {
      const [task, session] = words.slice(1).map(Number)
      if (![task, session].every(Number.isSafeInteger)) return false
      if (this.state.taskLimit !== Infinity && !Number.isSafeInteger(task + this.state.taskLimit)) return false
      if (this.state.sessionLimit !== Infinity && !Number.isSafeInteger(session + this.state.sessionLimit)) return false
      if (this.state.taskLimit !== Infinity) this.state.taskLimit += task
      if (this.state.sessionLimit !== Infinity) this.state.sessionLimit += session
      this.state.taskWarned = false; this.state.sessionWarned = false
    } else return false
    return true
  }
}

export default function (pi: ExtensionAPI) {
  let budget = new UsageBudget()
  let context: ExtensionContext | undefined
  let sessionId: string | undefined
  const childMessages = new Set<string>()
  const save = () => pi.appendEntry(ENTRY, { ...budget.state })
  const notice = (text: string) => context?.ui.notify(text, "warning")
  const load = (ctx: ExtensionContext) => {
    context = ctx
    const id = ctx.sessionManager.getSessionId()
    if (id === sessionId) return
    sessionId = id; budget = new UsageBudget(); childMessages.clear()
    // Full entries survive compaction; branch views would discard old usage.
    const entries = ctx.sessionManager.getEntries()
    for (const entry of entries) {
      if (entry.type === "custom" && entry.customType === ENTRY) budget.restore(entry.data)
      else if (entry.type === "message") budget.count(entry.message)
    }
  }
  const settle = (message: CountedMessage, ctx: ExtensionContext) => {
    budget.count(message)
    const warnings = budget.warnings()
    if (warnings.length) notice(warnings.join("\n"))
    if (budget.blocked) { notice(budget.status()); ctx.abort() }
  }
  pi.on("session_start", (_event, ctx) => { load(ctx) })
  pi.on("session_switch", (_event, ctx) => { sessionId = undefined; load(ctx) })
  pi.on("input", (_event, ctx) => {
    load(ctx)
    if (budget.blocked) { notice(budget.status()); return { handled: true } }
  })
  pi.on("before_agent_start", (_event, ctx) => {
    load(ctx)
    if (budget.blocked) { notice(budget.status()); ctx.abort() }
  })
  // Awaited by the agent loop, before tool dispatch and a continuation request.
  pi.on("assistant_message", (event, ctx) => { load(ctx); settle(event.message, ctx) })
  pi.on("agent_end", () => { save() })
  pi.on("tool_call", (_event, ctx) => {
    load(ctx)
    if (budget.blocked) return { block: true, reason: budget.status() }
  })
  pi.on("before_subagent_spawn", (_event, ctx) => {
    load(ctx)
    if (budget.blocked) return { block: true, reason: budget.status() }
  })
  // The host forwards completed child messages on the parent session bus.
  // This accounts child output even when child extension discovery is disabled.
  const unsubscribe = pi.events.on("task:subagent:event", (raw: unknown) => {
    if (!context || !raw || typeof raw !== "object" || !("id" in raw) || typeof raw.id !== "string" || !("event" in raw)) return
    const event = raw.event
    if (!event || typeof event !== "object" || !("type" in event) || event.type !== "message_end" || !("message" in event)) return
    const candidate = event.message
    if (!candidate || typeof candidate !== "object" || !("role" in candidate) || candidate.role !== "assistant") return
    const usage = "usage" in candidate ? candidate.usage : undefined
    const output = usage && typeof usage === "object" && "output" in usage && typeof usage.output === "number" ? usage.output : undefined
    const timestamp = "timestamp" in candidate && typeof candidate.timestamp === "number" ? candidate.timestamp : undefined
    const message: CountedMessage = { role: "assistant", usage: { output }, timestamp }
    const key = `${raw.id}:${timestamp}:${JSON.stringify(usage)}`
    if (childMessages.has(key)) return
    childMessages.add(key)
    settle(message, context)
    save()
  })
  pi.on("session_shutdown", () => { unsubscribe() })
  pi.registerCommand("usage-budget", {
    description: "Show usage; add TASK SESSION tokens; start a new task with task; clear limits with disable; restore defaults with enable; disable+continue with unlock",
    handler: async (args, ctx) => {
      load(ctx)
      const trimmed = args.trim()
      if (trimmed === "disable" || trimmed === "unlock") {
        budget.state.taskLimit = Infinity; budget.state.sessionLimit = Infinity
        budget.state.taskWarned = false; budget.state.sessionWarned = false
        save()
        ctx.ui.notify(`usage-budget limits off; /usage-budget enable restores defaults\n${budget.status()}`, "info")
        if (trimmed === "unlock") pi.sendUserMessage("继续")
        return
      }
      if (trimmed === "enable") {
        budget.state.taskLimit = DEFAULT_TASK_LIMIT; budget.state.sessionLimit = DEFAULT_SESSION_LIMIT
        budget.state.taskWarned = false; budget.state.sessionWarned = false
        save(); ctx.ui.notify(budget.status(), "info")
        return
      }
      if (trimmed && !budget.command(args)) { ctx.ui.notify("Usage: /usage-budget [add TASK SESSION | task | disable | enable | unlock]", "error"); return }
      save(); ctx.ui.notify(budget.status(), "info")
    },
  })
}
