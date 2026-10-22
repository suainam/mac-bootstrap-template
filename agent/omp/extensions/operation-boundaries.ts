import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent"

type Boundary = "credentials" | "browser"
type ToolInput = { toolName: string; input: Record<string, unknown> }

export function boundaryFor(call: ToolInput): Boundary | undefined {
  const values = Object.values(call.input).filter((v): v is string => typeof v === "string")
  const text = values.join("\n") + "\n" + JSON.stringify(call.input)
  // Known command signatures only; arbitrary code and shell expansion are not sandboxed.
  if (/\bsecurity\s+(?:dump-keychain|find-(?:generic|internet)-password\b[^\n;]*\s-[^\s]*[wg])/.test(text) ||
      /\b(?:bw|op)\s+(?:export|list\s+(?:items|passwords))\b/.test(text)) return "credentials"
  if (/\bagent-browser\b/.test(text) && /--(?:profile|auto-connect|cdp)\b/.test(text)) return "browser"
  if (/--user-data-dir\b/.test(text)) return "browser"
  if (/\brelay\s*["']?\s*:\s*true|\btarget\s*["']?\s*:/.test(text) && /browser|app/.test(text)) return "browser"
  if (call.toolName === "browser" && /"(?:profile|cdp|target|relay)"\s*:/.test(text)) return "browser"
  return undefined
}

export class OperationBoundaries {
  private session = ""
  private grants = new Set<Boundary>()
  switchSession(id: string) { if (id !== this.session) { this.session = id; this.grants.clear() } }
  allow(value: string) {
    if (value !== "credentials" && value !== "browser") return false
    this.grants.add(value); return true
  }
  check(call: ToolInput) {
    const boundary = boundaryFor(call)
    if (!boundary) return undefined
    if (this.grants.delete(boundary)) return undefined
    return {
      block: true as const,
      reason: `Operation boundary: ${boundary}. Use normal CLI authentication or an isolated temporary browser. ` +
        `For this specific operation, the operator may grant one matching call with /operation-boundary allow ${boundary}. ` +
        "Do not search for an alternate route around this block.",
    }
  }
}

export default function (pi: ExtensionAPI) {
  const guard = new OperationBoundaries()
  pi.on("tool_call", (event, ctx) => {
    guard.switchSession(ctx.sessionManager.getSessionId())
    return guard.check({ toolName: event.toolName, input: event.input })
  })
  pi.on("session_switch", (_event, ctx) => { guard.switchSession(ctx.sessionManager.getSessionId()) })
  pi.registerCommand("operation-boundary", {
    description: "Operator-only: allow credentials or browser for one matching tool call",
    handler: async (args, ctx) => {
      guard.switchSession(ctx.sessionManager.getSessionId())
      const words = args.trim().split(/\s+/)
      if (words.length !== 2 || words[0] !== "allow" || !guard.allow(words[1])) {
        ctx.ui.notify("Usage: /operation-boundary allow credentials|browser", "error"); return
      }
      ctx.ui.notify(`One ${words[1]} call allowed in this session; review the proposed operation before continuing.`, "warning")
    },
  })
}
