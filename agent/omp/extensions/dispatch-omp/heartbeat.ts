/**
 * Stage heartbeat contract — TB-05 / TB-06.
 *
 * The difference between a heartbeat and a report is the whole point of this
 * file:
 *
 * - `[HEARTBEAT]` proves a worker is *alive and located*. It never ends the
 *   orchestrator's park and never advances the brain. It is absorbed silently.
 * - `[NOTIFY]` carries a *result*. It is the only thing that ends the park.
 *
 * Without the distinction, a long lane either looks frozen because nothing says
 * otherwise, or an impatient orchestrator mistakes "still working" for
 * "finished" and either takes the work over or re-runs it. A heartbeat is
 * cheap liveness evidence that resolves both without inventing progress.
 *
 * Canonical form:
 *
 *     [HEARTBEAT] [w3:p6_opencode_mac-bootstrap]
 *     STAGE: Stage 4 Deploying on target
 *     STATUS: past the submodule gate, running the playbook directly
 *     PROGRESS: 4/7
 *
 * Parsing is total: every input yields a verdict or a reason, never a throw. A
 * malformed heartbeat must be inert, not disruptive.
 */

import { laneFromSignature } from "./notify.ts";

/** The marker that opens every heartbeat. */
export const HEARTBEAT_MARKER = "[HEARTBEAT]";

/** Fields a heartbeat may carry. All are optional except the signature. */
export const HEARTBEAT_FIELDS = Object.freeze(["stage", "status", "progress"]);

/** Progress values that mean "I could not express a number". */
const UNKNOWN_PROGRESS = Object.freeze(["", "?", "unknown", "n/a", "-"]);

/**
 * Parse a stage heartbeat.
 *
 * @returns {{ok: true, beat: object} | {ok: false, reason: string}}
 */
export function parseHeartbeat(text) {
  if (typeof text !== "string" || text.trim() === "") {
    return { ok: false, reason: "empty heartbeat" };
  }

  const markerAt = text.indexOf(HEARTBEAT_MARKER);
  if (markerAt < 0) {
    return { ok: false, reason: "no [HEARTBEAT] marker" };
  }

  const body = text.slice(markerAt).split(/\n\s*\n/, 1)[0];

  const signatureMatch = body.match(/\[HEARTBEAT\]\s*\[([^\]]+)\]/);
  if (!signatureMatch) {
    return { ok: false, reason: "missing signature" };
  }
  const signature = signatureMatch[1].trim();
  if (signature === "") {
    return { ok: false, reason: "empty signature" };
  }

  const beat = {
    signature,
    lane: laneFromSignature(signature),
    stage: "",
    status: "",
    progress: null,
    raw: body,
  };

  const stageMatch = body.match(/^STAGE:\s*(.+)$/m);
  if (stageMatch) beat.stage = stageMatch[1].trim();

  const statusMatch = body.match(/^STATUS:\s*(.+)$/m);
  if (statusMatch) beat.status = statusMatch[1].trim();

  const progressMatch = body.match(/^PROGRESS:\s*(.+)$/m);
  if (progressMatch) {
    const raw = progressMatch[1].trim();
    if (!UNKNOWN_PROGRESS.includes(raw.toLowerCase())) {
      const percent = raw.match(/(\d{1,3})\s*%/);
      if (percent) {
        beat.progress = Math.min(100, Number(percent[1]));
      } else {
        const fraction = raw.match(/^(\d+)\s*\/\s*(\d+)$/);
        if (fraction) {
          const [, done, total] = fraction;
          beat.progress = total > 0 ? Math.round((Number(done) / Number(total)) * 100) : null;
        } else if (/^\d+$/.test(raw)) {
          beat.progress = Math.min(100, Number(raw));
        }
      }
    }
  }

  // A heartbeat with no substance is noise. STAGE is the minimum: it says where
  // the worker is, which is the entire reason a heartbeat exists.
  if (beat.stage === "" && beat.status === "" && beat.progress === null) {
    return { ok: false, reason: "no STAGE, STATUS or PROGRESS payload" };
  }

  return { ok: true, beat };
}

/**
 * Render a heartbeat for the sidebar.
 *
 * Sidebar tokens are capped at 80 characters, so the stage is compacted to
 * something a human can read at a glance (`Stage 4 Deploying on target` becomes
 * `dep@hk216`) rather than truncated mid-word into noise.
 */
export function displayStage(stage) {
  const text = String(stage ?? "").trim();
  if (text === "") return "";

  const stageNumber = text.match(/^stage\s*(\d+)/i);
  const prefix = stageNumber ? `s${stageNumber[1]}` : "s";

  // Prefer the last path-like or code-like token, which is the part that
  // actually identifies the work: "Stage 4 Deploying on hk216" -> "s4@hk216".
  const distinctive = text.match(/([A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*@[A-Za-z0-9._-]+)|(?:\bof\s+([A-Za-z0-9._-]{2,}))|(?:\bon\s+([A-Za-z0-9._-]{2,}))|(?:\bto\s+([A-Za-z0-9._-]{2,}))|(?:\bin\s+([A-Za-z0-9._-]{2,}))/i);
  if (distinctive) {
    const target = distinctive[1] ?? distinctive[2] ?? distinctive[3] ?? distinctive[4] ?? distinctive[5];
    return `${prefix}@${target}`.slice(0, 80);
  }

  const words = text.replace(/^stage\s*\d+\s*/i, "").split(/\s+/).filter(Boolean);
  if (words.length === 0) return prefix;
  return `${prefix}${words[0]}`.slice(0, 80);
}

/**
 * Fields to fold into a lane record.
 *
 * Kept separate from the writer so the caller decides which partition it is
 * writing; the partition check is what stops a heartbeat from silently
 * overwriting plugin-owned presentation fields.
 */
export function heartbeatFields(beat, nowMs) {
  const fields = {};
  if (beat.stage) fields.current_stage = beat.stage.slice(0, 200);
  if (beat.status) fields.last_status = beat.status.slice(0, 200);
  if (beat.progress !== null) fields.progress_pct = beat.progress;
  fields.last_heartbeat = nowMs;
  return fields;
}

/** Has enough time passed to be worth a heartbeat? */
export function heartbeatDue(lastBeatMs, nowMs, intervalMs) {
  if (!Number.isFinite(lastBeatMs)) return true;
  return nowMs - lastBeatMs >= intervalMs;
}