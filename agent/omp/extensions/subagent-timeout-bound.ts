// Managed OMP extension: turn a subagent timeout into a bounded, closed handoff.
//
// Why this exists: a `task` worker that hits `task.maxRuntimeMs` returns a
// partial result, and the parent's instinct is to resume it ("continue",
// "keep exploring"). That resume is unbounded work on a dead budget. The
// host text for that outcome is deterministic (see TIMEOUT_RE below), so the
// closure can be mechanical instead of a prose rule in a skill.
//
// Mechanism (both supported ExtensionAPI surfaces, no binary patching):
//   1. `tool_result` on the `task` tool: detect the timeout marker, then emit a
//      bounded snapshot and remember the affected agent ids as closed.
//   2. `tool_call` on the `task` tool: refuse a re-spawn that resumes a closed
//      id, with a reason that tells the caller what to do instead.
//
// Scope note: the synchronous `task` result carries the timeout text. With
// `async.enabled=true` the spawn call only acknowledges the job and the final
// result arrives later as an `async-result` injection, which this extension
// does not intercept; the timeout there is still bounded by the same
// `task.maxRuntimeMs` setting, but the snapshot/closure below is not applied.

import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent"

/** Host-generated timeout marker. Keep in sync with the task runtime. */
export const TIMEOUT_RE = /Subagent runtime limit exceeded \(task\.maxRuntimeMs=(\d+)\)/

/** How many closed agents we remember before evicting the oldest. */
const CLOSED_LIMIT = 32

/** Bytes of a partial result kept in the snapshot. */
const SNAPSHOT_TAIL_BYTES = 1_500

export type ClosedRecord = {
  agentId: string
  maxRuntimeMs: number
  closedAt: number
}

/** Extract the agent ids and budget from a timeout-bearing task result. */
export function parseTimeout(
  content: string,
  details?: unknown,
): { maxRuntimeMs: number; agentIds: string[] } | null {
  const match = TIMEOUT_RE.exec(content)
  if (!match) return null
  const maxRuntimeMs = Number.parseInt(match[1], 10)
  const ids: string[] = []

  // 1. Structured details from tool_result (TaskToolDetails: results: [{ id, ... }])
  if (details && typeof details === "object") {
    if ("results" in details && Array.isArray((details as { results: unknown[] }).results)) {
      for (const r of (details as { results: unknown[] }).results) {
        if (r && typeof r === "object" && "id" in r && typeof (r as { id: unknown }).id === "string") {
          ids.push((r as { id: string }).id)
        }
      }
    }
    // 2. Structured details from async-result (jobs: [{ jobId, agentId }])
    if ("jobs" in details && Array.isArray((details as { jobs: unknown[] }).jobs)) {
      for (const j of (details as { jobs: unknown[] }).jobs) {
        if (j && typeof j === "object") {
          const job = j as { jobId?: unknown; agentId?: unknown }
          if (typeof job.agentId === "string") ids.push(job.agentId)
          else if (typeof job.jobId === "string") ids.push(job.jobId)
        }
      }
    }
  }

  // 3. Fallback: match XML attribute id="..." or agent://<id> tokens in text
  if (ids.length === 0) {
    for (const m of content.matchAll(/<task-result[^>]+id="([^"]+)"/g)) {
      ids.push(m[1])
    }
    for (const m of content.matchAll(/agent:\/\/([A-Za-z0-9_.-]+)/g)) {
      ids.push(m[1])
    }
  }
  return { maxRuntimeMs: Number.isFinite(maxRuntimeMs) ? maxRuntimeMs : 0, agentIds: ids }
}

/** Bounded snapshot: what survived the timeout, and what must not resume. */
export function buildSnapshot(record: ClosedRecord, partialOutput: string): string {
  const tail = partialOutput.length > SNAPSHOT_TAIL_BYTES
    ? partialOutput.slice(-SNAPSHOT_TAIL_BYTES)
    : partialOutput
  const lines = [
    "SUBAGENT CLOSED FOR EXPLORATION",
    `agent: ${record.agentId || "(unnamed)"}`,
    `budget: task.maxRuntimeMs=${record.maxRuntimeMs}ms exceeded`,
    "",
    "Partial evidence captured before the timeout (authoritative; do not re-derive):",
    tail.trim() || "(no output before the limit)",
    "",
    "Do not resume or re-spawn this agent to keep exploring. Allowed next steps:",
    "1. Report the partial result above as the outcome.",
    "2. Spawn a NEW agent with a narrower task if more work is required.",
  ]
  return lines.join("\n")
}

export default function (pi: ExtensionAPI) {
  const closed = new Map<string, ClosedRecord>()

  const remember = (record: ClosedRecord) => {
    const key = record.agentId || "(unnamed)"
    closed.set(key, record)
    while (closed.size > CLOSED_LIMIT) {
      const oldest = closed.keys().next()
      if (oldest.done) break
      closed.delete(oldest.value)
    }
  }

  pi.on("tool_result", async (event) => {
    if (event.toolName !== "task") return
    const content = event.content
      .map((chunk) => (chunk.type === "text" ? chunk.text : ""))
      .filter(Boolean)
      .join("\n")
    const parsed = parseTimeout(content, event.details)
    if (!parsed) return

    const ids = parsed.agentIds.length > 0 ? parsed.agentIds : ["(unnamed)"]
    for (const agentId of ids) {
      remember({ agentId, maxRuntimeMs: parsed.maxRuntimeMs, closedAt: Date.now() })
    }
    const record = closed.get(ids[0])
    if (!record) return
    return { additionalContext: buildSnapshot(record, content) }
  })

  pi.on("tool_call", async (event) => {
    if (closed.size === 0) return

    // Guard 1: `write agent://<id>` resume messaging
    if (event.toolName === "write") {
      const path = typeof event.input?.path === "string" ? event.input.path : ""
      for (const [agentId, record] of closed) {
        if (!agentId || agentId === "(unnamed)") continue
        if (path === `agent://${agentId}` || path.startsWith(`agent://${agentId}/`)) {
          return {
            block: true,
            reason:
              `Agent ${agentId} is closed for exploration: it exceeded task.maxRuntimeMs=` +
              `${record.maxRuntimeMs}ms. Messaging/resuming this agent is disabled. ` +
              `Report its partial result, or spawn a new agent with a narrower task.`,
          }
        }
      }
    }

    // Guard 2: `task` re-spawn / continuation referencing closed agent
    if (event.toolName === "task") {
      const raw = JSON.stringify(event.input ?? {})
      for (const [agentId, record] of closed) {
        if (!agentId || agentId === "(unnamed)") continue
        if (!raw.includes(agentId)) continue
        return {
          block: true,
          reason:
            `Agent ${agentId} is closed for exploration: it exceeded task.maxRuntimeMs=` +
            `${record.maxRuntimeMs}ms. Report its partial result, or spawn a new agent ` +
            `with a narrower task.`,
        }
      }
    }
  })

  // Async path: with `async.enabled=true` the spawn call only acknowledges the
  // job, and the timeout text arrives later inside an `async-result` custom
  // message. `message_end` is the supported completion surface for that, so the
  // closure and snapshot are re-derived from the message itself.
  pi.on("message_end", async (event) => {
    const message = event.message
    if (!message || typeof message !== "object") return
    if (!("customType" in message) || message.customType !== "async-result") return

    const text = messageText(message)
    const parsed = parseTimeout(text, "details" in message ? message.details : undefined)
    if (!parsed) return

    const ids = parsed.agentIds.length > 0 ? parsed.agentIds : ["(unnamed)"]
    for (const agentId of ids) {
      remember({ agentId, maxRuntimeMs: parsed.maxRuntimeMs, closedAt: Date.now() })
    }
    const record = closed.get(ids[0])
    if (!record) return

    pi.sendMessage({
      customType: "subagent-timeout-bound",
      content: buildSnapshot(record, text),
      display: true,
      attribution: "agent",
    })
  })
}

/** Flatten a message's content blocks into plain text. */
function messageText(message: object): string {
  if (!("content" in message)) return ""
  const { content } = message
  if (typeof content === "string") return content
  if (!Array.isArray(content)) return ""
  return content
    .map((chunk) =>
      chunk && typeof chunk === "object" && "text" in chunk && typeof chunk.text === "string"
        ? chunk.text
        : "",
    )
    .filter(Boolean)
    .join("\n")
}
