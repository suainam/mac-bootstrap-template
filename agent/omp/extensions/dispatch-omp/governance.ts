/**
 * Context and memory governance — multi-agent memory safety.
 *
 * The failure this exists to prevent
 * ----------------------------------
 * A long agent caches terminal output, diffs and tool results in process
 * memory. Past roughly 300-500k context tokens a single Node/Bun/Python agent
 * commonly sits at 1.5-3 GB RSS. Four of those in parallel is 6-12 GB of host
 * memory before any of them does useful work, and on a 16 GB machine the
 * kernel reclaims it with SIGKILL mid-task. The task looks like an agent
 * failure; it is a host-pressure failure.
 *
 * Four defences, each pure so it can be tested without a session.
 *
 * 1. **Append-only pruning.** At a stage boundary most of the recent context is
 *    spent: build errors already triaged, greps already answered. Dropping it
 *    keeps a stage's resident context at 30-50k tokens instead of growing
 *    without bound.
 *
 * 2. **Session rollover.** Past a hard ceiling the worker checkpoints to disk
 *    and continues in a fresh, small session. Resuming from a checkpoint is
 *    cheap; being OOM-killed at 400k tokens is not.
 *
 * 3. **Phase-aware model downgrading.** Waiting for a build or tailing a log
 *    does not need the biggest model. Dropping to a light one cuts both token
 *    spend and the runtime heap that holds it.
 *
 * 4. **Host memory pressure.** The watchdog watches host headroom and stops
 *    admitting new heavyweight agents below a floor, rather than discovering the
 *    limit by being killed.
 *
 * Everything here is policy. Applying it is the host's job, and applying it
 * wrongly (pruning too eagerly, rolling over too often, downgrading a lane that
 * needed the big model) costs more than the memory it saves, so the defaults
 * are conservative and every threshold is overridable.
 */

import { execFileSync } from "node:child_process";

/** Soft ceiling: prune stage noise before the context becomes expensive. */
export const DEFAULT_PRUNE_THRESHOLD_TOKENS = 120_000;

/** Hard ceiling: checkpoint and start a fresh session past this. */
export const DEFAULT_ROLLOVER_THRESHOLD_TOKENS = 200_000;

/** Resident context a stage should settle back to after pruning. */
export const TARGET_STAGE_TOKENS = 50_000;

/** Fresh-session budget after a rollover. */
export const TARGET_FRESH_SESSION_TOKENS = 20_000;

/** Below this fraction of host memory free, stop admitting heavy agents. */
export const DEFAULT_MEMORY_PRESSURE_FLOOR = 0.20;

/** Below this, stop admitting *any* new agent, not just heavy ones. */
export const CRITICAL_MEMORY_PRESSURE_FLOOR = 0.10;

/**
 * Stages where a light model is sufficient.
 *
 * These are phases where the work is waiting, watching or mechanically
 * transforming output — not reasoning. "verify" and "review" are absent on
 * purpose: downgrading those would quietly trade correctness for memory.
 */
export const DOWNGRADE_SAFE_STAGES = Object.freeze([
  "planning",
  "waiting",
  "polling",
  "collecting",
  "rolling_log",
  "applying",
]);

/** Default thresholds, overridable from the plugin config directory. */
export const DEFAULT_LIMITS = Object.freeze({
  pruneThresholdTokens: DEFAULT_PRUNE_THRESHOLD_TOKENS,
  rolloverThresholdTokens: DEFAULT_ROLLOVER_THRESHOLD_TOKENS,
  targetStageTokens: TARGET_STAGE_TOKENS,
  memoryPressureFloor: DEFAULT_MEMORY_PRESSURE_FLOOR,
  criticalPressureFloor: CRITICAL_MEMORY_PRESSURE_FLOOR,
});

// --------------------------------------------------------------------------
// 1. Pruning
// --------------------------------------------------------------------------

/**
 * Decide whether to prune, and what must survive.
 *
 * @param {number} tokens current context size
 * @param {{limits?: object, atStageBoundary?: boolean}} options
 */
export function planPrune(tokens, options = {}) {
  const limits = { ...DEFAULT_LIMITS, ...(options.limits ?? {}) };
  const atBoundary = options.atStageBoundary !== false;

  if (!Number.isFinite(tokens)) {
    // Unknown size is not a licence to prune; pruning blind loses work.
    return { prune: false, reason: "context size unknown" };
  }
  if (tokens < limits.pruneThresholdTokens) {
    return { prune: false, reason: "below threshold", tokens };
  }
  if (!atBoundary) {
    // Mid-stage the recent tool output is still being reasoned over.
    return { prune: false, reason: "not at a stage boundary", tokens };
  }
  return {
    prune: true,
    reason: "stage boundary above prune threshold",
    tokens,
    // What pruning must never remove: the conclusions and pointers a later
    // stage needs. Dropping these is how a "memory fix" loses the work.
    retain: ["conclusions", "file_pointers", "open_questions", "contract", "lane_plan"],
  };
}

// --------------------------------------------------------------------------
// 2. Session rollover
// --------------------------------------------------------------------------

/**
 * Decide whether to roll the session over.
 *
 * Rollover is deliberately expensive — it costs a process restart and a
 * checkpoint — so it fires on a hard ceiling rather than on the same signal as
 * pruning.
 */
export function planRollover(tokens, options = {}) {
  const limits = { ...DEFAULT_LIMITS, ...(options.limits ?? {}) };

  if (!Number.isFinite(tokens)) return { rollover: false, reason: "context size unknown" };
  if (tokens < limits.rolloverThresholdTokens) {
    return { rollover: false, reason: "below rollover ceiling", tokens };
  }
  return {
    rollover: true,
    reason: "above rollover ceiling",
    tokens,
    checkpointPath: ".dispatch/CHECKPOINT.json",
    freshSessionBudget: limits.targetStageTokens,
    // The old session is retired, not deleted: an operator may still want to
    // read what happened before the rollover.
    retireOldSession: true,
  };
}

/** Build the checkpoint payload a rollover depends on. */
export function buildCheckpoint({ lane, stage, tokens, findings = [], nextSteps = [] }) {
  return {
    version: 1,
    lane,
    stage,
    tokens_at_rollover: tokens,
    // Findings and next steps are the compact form of the context: the bulky
    // transcript is replaced by what it concluded.
    findings,
    next_steps: nextSteps,
  };
}

// --------------------------------------------------------------------------
// 3. Phase-aware model downgrading
// --------------------------------------------------------------------------

/**
 * Should this lane drop to a lighter model for its current stage?
 *
 * @returns {{downgrade: boolean, reason: string}}
 */
export function planDowngrade(stage, options = {}) {
  const key = String(stage ?? "").trim().toLowerCase();
  if (key === "") return { downgrade: false, reason: "no stage" };

  // Match on the leading stage word so "Stage 4 Deploying" and "deploying"
  // classify the same way.
  const head = key.replace(/^stage\s*\d+\s*/, "").split(/[\s:_-]+/)[0];
  const match = DOWNGRADE_SAFE_STAGES.includes(key) || DOWNGRADE_SAFE_STAGES.includes(head);

  if (options.hostPressure === "critical") {
    // Checked before the reasoning-stage refusal: under real pressure even a
    // reasoning stage yields, and that is precisely when the check matters.
    return { downgrade: true, reason: `host memory critical; stage "${key}" downgraded anyway` };
  }
  if (!match) {
    return { downgrade: false, reason: `stage "${key}" needs full reasoning` };
  }
  return { downgrade: true, reason: `stage "${key}" is mechanical` };
}

// --------------------------------------------------------------------------
// 4. Host memory pressure
// --------------------------------------------------------------------------

/**
 * Parse host memory headroom into a 0..1 fraction free.
 *
 * @param {{totalBytes: number, freeBytes: number}} usage
 */
export function memoryFreeFraction(usage) {
  const total = Number(usage?.totalBytes);
  const free = Number(usage?.freeBytes);
  if (!Number.isFinite(total) || !Number.isFinite(free) || total <= 0) return null;
  return Math.max(0, Math.min(1, free / total));
}

/**
 * Classify host pressure.
 *
 * @returns {"ok" | "elevated" | "critical"}
 */
export function classifyPressure(fraction, options = {}) {
  const limits = { ...DEFAULT_LIMITS, ...(options.limits ?? {}) };
  if (fraction === null) return "ok"; // unknown pressure is not a reason to stop
  if (fraction < limits.criticalPressureFloor) return "critical";
  if (fraction < limits.memoryPressureFloor) return "elevated";
  return "ok";
}

/**
 * May another agent of this weight be admitted right now?
 *
 * `heavy` agents are the memory hogs; light ones are allowed through at
 * elevated pressure so a full stop does not strand the orchestrator with no
 * way to make progress.
 */
export function admitAgent(pressure, weight = "heavy", options = {}) {
  if (pressure === "critical") return false;
  if (pressure === "elevated" && weight === "heavy") return false;
  return true;
}

/**
 * Read host memory usage.
 *
 * Returns null rather than guessing when the platform call fails, so callers
 * degrade to "no opinion" instead of inventing pressure.
 */
export function readHostMemory(platform = process.platform, exec = execFileSync) {
  try {
    if (platform === "darwin") {
      const out = exec("vm_stat", { encoding: "utf8" });
      const pageSize = Number(out.match(/page size of\s+(\d+)/i)?.[1] ?? NaN);
      if (!Number.isFinite(pageSize) || pageSize <= 0) return null;
      const free = Number(out.match(/Pages free:\s*(\d+)/)?.[1] ?? NaN) * pageSize;
      const inactive = Number(out.match(/Pages inactive:\s*(\d+)/)?.[1] ?? NaN) * pageSize;
      const spec = Number(out.match(/Pages speculative:\s*(\d+)/)?.[1] ?? NaN) * pageSize;
      const total = Number(exec("sysctl", ["-n", "hw.memsize"], { encoding: "utf8" }).trim());
      const freeBytes = free + inactive + spec;
      if (!Number.isFinite(freeBytes) || !Number.isFinite(total)) return null;
      return { totalBytes: total, freeBytes };
    }
    if (platform === "linux") {
      const out = exec("free", ["-b"], { encoding: "utf8" });
      const lines = out.trim().split("\n");
      const header = lines[0].trim().split(/\s+/);
      const memLine = lines.find((line) => /^Mem:\s/.test(line.trim()));
      if (!memLine) return null;
      const values = memLine.trim().split(/\s+/);
      // Read by header name: column positions shift between free(1) versions
      // and platforms, and guessing an index silently reports the wrong number.
      // The data row carries a leading "Mem:" label the header does not.
      const aligned =
        values.length === header.length + 1 ? values.slice(1) : values;
      const pick = (name: string) => {
        const i = header.indexOf(name);
        return i < 0 ? Number.NaN : Number(aligned[i]);
      };
      const total = pick("total");
      const available = pick("available");
      if (!Number.isFinite(total) || !Number.isFinite(available)) return null;
      return { totalBytes: total, freeBytes: available };
    }
  } catch {
    return null;
  }
  return null;
}