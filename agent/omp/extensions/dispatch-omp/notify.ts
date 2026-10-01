/**
 * Notify contract — TB-05.
 *
 * Workers report back with a small, machine-parseable signature rather than
 * prose. That is the whole point: the orchestrator has to decide *whether* to
 * leave its park from something it can read, not from a paragraph it has to
 * interpret. A reminder is not a report, and a report from the wrong lane is
 * not this lane's report.
 *
 * Canonical form:
 *
 *     [NOTIFY] [w3:p6_opencode_mac-bootstrap]
 *     DONE: dispatch plugin TB-03/TB-04 landed
 *     Handoff: ~/Documents/handoffs/...-20261001_120500.md
 *
 * Parsing is deliberately strict and total: every input yields either a parsed
 * notification or a reason string, never an exception. A malformed report must
 * not be able to crash the wake path, and it must never be mistaken for a
 * valid one.
 */

/** The marker that opens every worker report. */
export const NOTIFY_MARKER = "[NOTIFY]";

/** Signature the parser accepts. */
export const NOTIFY_FIELDS = Object.freeze(["signature", "done", "handoff"]);

/**
 * Parse a worker report.
 *
 * @returns {{ok: true, notify: object} | {ok: false, reason: string}}
 */
export function parseNotify(text) {
  if (typeof text !== "string" || text.trim() === "") {
    return { ok: false, reason: "empty notification" };
  }

  const markerAt = text.indexOf(NOTIFY_MARKER);
  if (markerAt < 0) {
    return { ok: false, reason: "no [NOTIFY] marker" };
  }

  // Everything before the marker is preamble; a report may arrive embedded in
  // a larger steer. Take the marker onwards and stop at the first blank line
  // so trailing chatter cannot be mistaken for fields.
  const body = text.slice(markerAt).split(/\n\s*\n/, 1)[0];

  const notify = { signature: "", done: "", handoff: "", lane: "", raw: body };

  const signatureMatch = body.match(/\[NOTIFY\]\s*\[([^\]]+)\]/);
  if (!signatureMatch) {
    return { ok: false, reason: "missing signature" };
  }
  notify.signature = signatureMatch[1].trim();
  if (notify.signature === "") {
    return { ok: false, reason: "empty signature" };
  }

  const doneMatch = body.match(/^DONE:\s*(.+)$/m);
  if (doneMatch) notify.done = doneMatch[1].trim();

  const handoffMatch = body.match(/^Handoff:\s*(.+)$/m);
  if (handoffMatch) notify.handoff = handoffMatch[1].trim();

  // A report with neither a conclusion nor a handoff is a ping, not a result.
  // Accepting it would wake the orchestrator for nothing and restart the very
  // loop the park exists to avoid.
  if (notify.done === "" && notify.handoff === "") {
    return { ok: false, reason: "no DONE or Handoff payload" };
  }

  return { ok: true, notify };
}

/**
 * Extract the lane id from a signature.
 *
 * Signatures look like `<pane>_<agentKind>_<repoSlug>`, e.g.
 * `w3:p6_opencode_mac-bootstrap`. The pane is the part before the first
 * underscore, which is what lets a wake be attributed to exactly one lane.
 */
export function laneFromSignature(signature) {
  const match = String(signature ?? "").match(/^([A-Za-z0-9]+:[A-Za-z0-9]+)_/);
  return match ? match[1] : "";
}

/** Does this report belong to the given lane? An empty lane matches nothing. */
export function isForLane(notify, lane) {
  if (!notify || !lane) return false;
  return notify.lane === lane || laneFromSignature(notify.signature) === lane;
}

/**
 * Wake reason for a report.
 *
 * Only these signals may move the orchestrator out of its park. A todo
 * reminder is deliberately absent: it is not evidence that a worker finished,
 * and treating it as such is exactly the false-busywork loop the park exists
 * to prevent.
 */
export function wakeSignalFor(notify) {
  return notify && notify.ok === false ? null : "notify";
}

/** Human-readable reason a report was rejected, for surfacing in a steer. */
export function rejectionReason(result) {
  return result && result.ok === false ? result.reason : "";
}