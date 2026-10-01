/**
 * Context and memory governance tests.
 *
 * The failure being defended against is a SIGKILL, so the tests care less about
 * "does it prune" than about the two ways a memory fix goes wrong: pruning too
 * eagerly (which loses work) and never firing (which loses the host).
 */

import { describe, expect, test } from "bun:test";

import {
  CRITICAL_MEMORY_PRESSURE_FLOOR,
  DEFAULT_MEMORY_PRESSURE_FLOOR,
  DEFAULT_PRUNE_THRESHOLD_TOKENS,
  DEFAULT_ROLLOVER_THRESHOLD_TOKENS,
  admitAgent,
  buildCheckpoint,
  classifyPressure,
  memoryFreeFraction,
  planDowngrade,
  planPrune,
  planRollover,
  readHostMemory,
} from "../agent/omp/extensions/dispatch-omp/governance.ts";

describe("pruning", () => {
  test("prunes at a stage boundary past the soft ceiling", () => {
    const plan = planPrune(DEFAULT_PRUNE_THRESHOLD_TOKENS + 1, { atStageBoundary: true });
    expect(plan.prune).toBe(true);
  });

  test("does not prune below the soft ceiling", () => {
    expect(planPrune(DEFAULT_PRUNE_THRESHOLD_TOKENS - 1).prune).toBe(false);
  });

  test("does not prune mid-stage", () => {
    // The recent output is still being reasoned over; pruning here loses the
    // very evidence the current stage needs.
    const plan = planPrune(300_000, { atStageBoundary: false });
    expect(plan.prune).toBe(false);
    expect(plan.reason).toContain("stage boundary");
  });

  test("does not prune blind when the size is unknown", () => {
    // Unknown is not a licence to discard context.
    expect(planPrune(Number.NaN).prune).toBe(false);
    expect(planPrune(undefined).prune).toBe(false);
  });

  test("names what pruning must retain", () => {
    const plan = planPrune(400_000, { atStageBoundary: true });
    expect(plan.retain).toContain("conclusions");
    expect(plan.retain).toContain("file_pointers");
    expect(plan.retain).toContain("contract");
  });

  test("honours an overridden threshold", () => {
    const limits = { pruneThresholdTokens: 1_000 };
    expect(planPrune(2_000, { limits, atStageBoundary: true }).prune).toBe(true);
    expect(planPrune(500, { limits, atStageBoundary: true }).prune).toBe(false);
  });
});

describe("session rollover", () => {
  test("rolls over past the hard ceiling", () => {
    const plan = planRollover(DEFAULT_ROLLOVER_THRESHOLD_TOKENS + 1);
    expect(plan.rollover).toBe(true);
    expect(plan.checkpointPath).toBe(".dispatch/CHECKPOINT.json");
    // The old session is retired, not destroyed.
    expect(plan.retireOldSession).toBe(true);
  });

  test("does not roll over below the hard ceiling", () => {
    expect(planRollover(DEFAULT_ROLLOVER_THRESHOLD_TOKENS - 1).rollover).toBe(false);
  });

  test("rollover is a later trigger than pruning", () => {
    const between = DEFAULT_PRUNE_THRESHOLD_TOKENS + 1_000;
    expect(planPrune(between, { atStageBoundary: true }).prune).toBe(true);
    // Restarting a process is expensive; pruning must carry the middle range.
    expect(planRollover(between).rollover).toBe(false);
  });

  test("an unknown size does not trigger a restart", () => {
    expect(planRollover(Number.NaN).rollover).toBe(false);
  });

  test("a checkpoint carries conclusions, not the transcript", () => {
    const checkpoint = buildCheckpoint({
      lane: "1-1",
      stage: "verifying",
      tokens: 220_000,
      findings: ["gate passes"],
      nextSteps: ["handoff"],
    });
    expect(checkpoint.findings).toEqual(["gate passes"]);
    expect(checkpoint.next_steps).toEqual(["handoff"]);
    expect(checkpoint.tokens_at_rollover).toBe(220_000);
  });
});

describe("phase-aware downgrading", () => {
  test("mechanical stages downgrade", () => {
    for (const stage of ["waiting", "polling", "rolling_log", "applying"]) {
      expect(planDowngrade(stage).downgrade).toBe(true);
    }
  });

  test("reasoning stages never downgrade", () => {
    // This is the point of the whole rule: memory pressure must not quietly
    // trade correctness away.
    for (const stage of ["verifying", "review", "skeptic", "deciding"]) {
      expect(planDowngrade(stage).downgrade).toBe(false);
    }
  });

  test("stage numbering does not change the classification", () => {
    expect(planDowngrade("Stage 4 waiting on build").downgrade).toBe(true);
    expect(planDowngrade("Stage 9 verifying").downgrade).toBe(false);
  });

  test("critical host pressure downgrades even a reasoning stage", () => {
    const plan = planDowngrade("verifying", { hostPressure: "critical" });
    expect(plan.downgrade).toBe(true);
    expect(plan.reason).toContain("critical");
  });

  test("an unknown stage is left alone", () => {
    expect(planDowngrade("").downgrade).toBe(false);
    expect(planDowngrade(undefined).downgrade).toBe(false);
  });
});

describe("host memory pressure", () => {
  test("computes a free fraction", () => {
    expect(memoryFreeFraction({ totalBytes: 1000, freeBytes: 250 })).toBe(0.25);
  });

  test("clamps and rejects nonsense", () => {
    expect(memoryFreeFraction({ totalBytes: 1000, freeBytes: 5000 })).toBe(1);
    expect(memoryFreeFraction({ totalBytes: 1000, freeBytes: -5 })).toBe(0);
    expect(memoryFreeFraction({ totalBytes: 0, freeBytes: 5 })).toBeNull();
    expect(memoryFreeFraction(null)).toBeNull();
  });

  test("classifies at the documented floors", () => {
    expect(classifyPressure(0.8)).toBe("ok");
    expect(classifyPressure(DEFAULT_MEMORY_PRESSURE_FLOOR + 0.01)).toBe("ok");
    expect(classifyPressure(DEFAULT_MEMORY_PRESSURE_FLOOR - 0.01)).toBe("elevated");
    expect(classifyPressure(CRITICAL_MEMORY_PRESSURE_FLOOR - 0.01)).toBe("critical");
  });

  test("unknown pressure is not treated as pressure", () => {
    // Guessing "critical" here would freeze every lane on a machine where the
    // probe simply failed.
    expect(classifyPressure(null)).toBe("ok");
  });

  test("elevated pressure blocks heavy agents but not light ones", () => {
    expect(admitAgent("elevated", "heavy")).toBe(false);
    // A total stop would strand the orchestrator with no way to progress.
    expect(admitAgent("elevated", "light")).toBe(true);
  });

  test("critical pressure blocks everything new", () => {
    expect(admitAgent("critical", "heavy")).toBe(false);
    expect(admitAgent("critical", "light")).toBe(false);
  });

  test("normal pressure admits everything", () => {
    expect(admitAgent("ok", "heavy")).toBe(true);
  });
});

describe("host memory probing", () => {
  test("parses macOS vm_stat", () => {
    const fake = (cmd: string) =>
      cmd === "vm_stat"
        ? "Mach Virtual Memory Statistics: (page size of 4096)\nPages free:                             100000.\nPages inactive:                          200000.\nPages speculative:                       50000.\n"
        : "17179869184\n";
    const usage = readHostMemory("darwin", fake as never);
    expect(usage?.totalBytes).toBe(17179869184);
    // free + inactive + speculative reclaimable.
    expect(usage?.freeBytes).toBe(350_000 * 4096);
  });

  test("parses Linux free", () => {
    const fake = () =>
      "              total        used        free      shared  buff/cache   available\nMem:     16777216     8000000     4000000      100000     2000000     8777716\n";
    const usage = readHostMemory("linux", fake as never);
    expect(usage?.totalBytes).toBe(16777216);
    expect(usage?.freeBytes).toBe(8777716);
  });

  test("a failed probe yields no opinion rather than a guess", () => {
    const boom = () => {
      throw new Error("not available");
    };
    expect(readHostMemory("darwin", boom as never)).toBeNull();
    expect(readHostMemory("linux", boom as never)).toBeNull();
  });

  test("an unsupported platform yields null", () => {
    expect(readHostMemory("win32", (() => "") as never)).toBeNull();
  });

  test("garbled output yields null", () => {
    const garbage = () => "not a memory report";
    expect(readHostMemory("darwin", garbage as never)).toBeNull();
  });
});