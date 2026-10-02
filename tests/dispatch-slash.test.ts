/**
 * Tests for the `/dispatch` slash command — Issue #137.
 *
 * The command exists to remove a manual step, so the property worth testing is
 * structural rather than behavioural: the orchestrator's arguments reach the bus
 * as an argv array with no shell in between, and the bus's exit code comes back
 * unchanged.
 *
 * Both matter because the defect this replaces was a quoting accident. The
 * previous round of the design fixed `'\n[NOTIFY] ...'` rendering as one line by
 * building the text in Python, but the *call* was still a hand-written shell
 * string. If this file ever assembles a command line, that whole fix is one
 * refactor away from being undone.
 */

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { describe, expect, test } from "bun:test";

import dispatchBrain, {
  DISPATCH_DESCRIPTION,
  EXIT_CONTRACT,
  EXIT_DELIVERY_FAILED,
  EXIT_REFUSED,
  describeRefusal,
  findPlugin,
  laneFromSignature,
  parseDispatchArgs,
  registerDispatchCommand,
  runDispatch,
  tokenizeArgs,
} from "../agent/omp/extensions/dispatch-omp/index.ts";

const PLUGIN_ROOT = path.resolve(import.meta.dir, "../multiplexer/herdr-dispatch");
const REPO_ROOT = path.resolve(import.meta.dir, "..");

/** A runner that records what it was asked to execute. */
function makeRunner({ status = 0, stdout = "dispatch: ok\n", stderr = "" } = {}) {
  const calls: Array<{ cmd: string; argv: string[]; options: Record<string, unknown> }> = [];
  return {
    calls,
    runner(cmd, argv, options) {
      calls.push({ cmd, argv: [...argv], options });
      return { status, stdout, stderr, error: undefined };
    },
  };
}

const RESOLVE = () => path.join(PLUGIN_ROOT, "bin", "dispatch_plugin.py");

// --------------------------------------------------------------------------
// Registration
// --------------------------------------------------------------------------

test("/dispatch is registered when the extension loads", () => {
  const commands: Record<string, unknown> = {};
  const pi = {
    registerCommand: (name: string, options: unknown) => {
      commands[name] = options;
    },
    on: () => {},
  };
  dispatchBrain(pi as never);
  expect(Object.keys(commands)).toContain("dispatch");
});

test("registration is a no-op on a host without registerCommand", () => {
  expect(registerDispatchCommand({} as never)).toBe(false);
});

test("a successful dispatch notifies the host projection exactly once", async () => {
  const calls = { refreshed: 0 };
  const pi = {
    registerCommand(_name, def) {
      this.command = def;
    },
  };
  registerDispatchCommand(pi, {
    runner: () => ({ status: 0, stdout: "dispatch: ok\n", stderr: "" }),
    resolvePlugin: () => "/tmp/dispatch_plugin.py",
    onSuccess: () => {
      calls.refreshed += 1;
    },
  });

  await pi.command.handler(
    "--task TASK.md --lane-name 1-3-dispatch --target w3:p9",
    { cwd: "/repo", ui: { notify() {} } },
  );
  expect(calls.refreshed).toBe(1);
});

test("a dispatch failure stays in UI and never creates a model turn", async () => {
  let registered: any = null;
  const modelTurns: string[] = [];
  const notices: Array<[string, string]> = [];
  const pi = {
    registerCommand: (_name: string, options: any) => {
      registered = options;
    },
    sendUserMessage: (text: string) => modelTurns.push(text),
  };
  const { runner } = makeRunner({
    status: EXIT_DELIVERY_FAILED,
    stderr: "delivery not confirmed; retry same dispatch identity",
  });
  expect(registerDispatchCommand(pi as never, { resolvePlugin: RESOLVE, runner })).toBe(true);
  await registered.handler(
    "--task T.md --lane-name 1-3-dispatch --target w3:p9 --callback-target w3:p1",
    { cwd: REPO_ROOT, ui: { notify: (text: string, level: string) => notices.push([text, level]) } },
  );
  expect(modelTurns).toEqual([]);
  expect(notices.some(([text]) => text.includes("retry same dispatch identity"))).toBe(true);
});

test("the description states the minimal call and both exit codes", () => {
  // Discoverability is the point: an orchestrator must be able to use this
  // without reading the README, and the two exit codes mean different actions.
  expect(DISPATCH_DESCRIPTION).toContain("--lane-name");
  expect(DISPATCH_DESCRIPTION).toContain("Exit 1");
  expect(DISPATCH_DESCRIPTION).toContain("Exit 2");
  expect(DISPATCH_DESCRIPTION).toContain("derived");
});

// --------------------------------------------------------------------------
// Argument forwarding
// --------------------------------------------------------------------------

test("the minimal call becomes a four-argument bus invocation", () => {
  const parsed = parseDispatchArgs(
    "--task .dispatch/TASK.md --lane-name 1-3-dispatch --target w3:p9",
  );
  expect(parsed.ok).toBe(true);
  if (!parsed.ok) return;
  expect(parsed.argv).toEqual([
    "dispatch",
    "--task",
    ".dispatch/TASK.md",
    "--lane-name",
    "1-3-dispatch",
    "--target",
    "w3:p9",
  ]);
});

test("a missing required argument names the minimal call", () => {
  const parsed = parseDispatchArgs("--task TASK.md");
  expect(parsed.ok).toBe(false);
  if (parsed.ok) return;
  expect(parsed.reason).toContain("--lane-name");
  expect(parsed.reason).toContain("--target");
});

test("an unknown option is refused rather than forwarded", () => {
  // Forwarding it would make the bus's own argparse the only thing standing
  // between a typo and a dispatch with a mis-parsed argument.
  const parsed = parseDispatchArgs(
    "--task T.md --lane-name 1-3-dispatch --target w3:p9 --lan 1-3",
  );
  expect(parsed.ok).toBe(false);
  if (parsed.ok) return;
  expect(parsed.reason).toContain("--lan");
});

test("an option without a value is refused", () => {
  const parsed = parseDispatchArgs("--task");
  expect(parsed.ok).toBe(false);
  if (parsed.ok) return;
  expect(parsed.reason).toContain("needs a value");
});

test("--repo precedes the subcommand", () => {
  // `--repo` is a plugin-level option, so putting it after `dispatch` would
  // reach the bus as an unknown flag and fail with a confusing message.
  const parsed = parseDispatchArgs(
    "--repo /tmp/repo --task T.md --lane-name 1-3-dispatch --target w3:p9",
  );
  expect(parsed.ok).toBe(true);
  if (!parsed.ok) return;
  expect(parsed.argv.slice(0, 2)).toEqual(["--repo", "/tmp/repo"]);
  expect(parsed.argv[2]).toBe("dispatch");
});

test("repeated --highlight flags survive as separate arguments", () => {
  const parsed = parseDispatchArgs(
    "--task T.md --lane-name 1-3-dispatch --target w3:p9 --highlight a --highlight b",
  );
  expect(parsed.ok).toBe(true);
  if (!parsed.ok) return;
  expect(parsed.argv.filter((a) => a === "--highlight")).toHaveLength(2);
  expect(parsed.argv).toContain("b");
});

test("a single-valued flag given twice is refused", () => {
  const parsed = parseDispatchArgs(
    "--task A.md --task B.md --lane-name 1-3-dispatch --target w3:p9",
  );
  expect(parsed.ok).toBe(false);
});

test("--flag=value is accepted", () => {
  const parsed = parseDispatchArgs(
    "--task=T.md --lane-name=1-3-dispatch --target=w3:p9",
  );
  expect(parsed.ok).toBe(true);
  if (!parsed.ok) return;
  expect(parsed.argv).toContain("T.md");
});

// --------------------------------------------------------------------------
// The command reaches the bus as an argv array, never a shell string
// --------------------------------------------------------------------------

test("the bus is invoked with an argv array and no shell", () => {
  const { calls, runner } = makeRunner();
  runDispatch("--task T.md --lane-name 1-3-dispatch --target w3:p9", {
    resolvePlugin: RESOLVE,
    runner,
  });
  expect(calls).toHaveLength(1);
  // `shell: false` is the load-bearing assertion. With it, a path containing a
  // space or a quote reaches git as one argument instead of being re-split.
  expect(calls[0].options.shell).toBe(false);
  expect(Array.isArray(calls[0].argv)).toBe(true);
});

test("the located bus script leads the argv", () => {
  // Found by walking up, then named explicitly. A locator whose result never
  // reached the argv would make every failure look like a Python error about a
  // missing file rather than a dispatch problem.
  const { calls, runner } = makeRunner();
  runDispatch("--task T.md --lane-name 1-3-dispatch --target w3:p9", {
    resolvePlugin: RESOLVE,
    runner,
  });
  expect(calls[0].argv[0]).toBe(path.join(PLUGIN_ROOT, "bin", "dispatch_plugin.py"));
  expect(calls[0].argv[1]).toBe("dispatch");
});

test("a quoted path with a space reaches the bus as one argument", () => {
  const { calls, runner } = makeRunner();
  runDispatch(`--task "my tasks/TASK.md" --lane-name 1-3-dispatch --target w3:p9`, {
    resolvePlugin: RESOLVE,
    runner,
  });
  const taskAt = calls[0].argv.indexOf("--task");
  expect(taskAt).toBeGreaterThan(-1);
  // Quotes consumed, one argument, spaces intact. Asserting the *value* rather
  // than just its type is what makes this falsifiable: a tokenizer that left
  // the quotes in place would satisfy `typeof === "string"`.
  expect(calls[0].argv[taskAt + 1]).toBe("my tasks/TASK.md");
  expect(calls[0].argv).not.toContain("my");
});

test("an escaped space reaches the bus as one argument", () => {
  // A backslash-escaped space is the other spelling of the same path.
  const parsed = parseDispatchArgs(
    "--task my\\ tasks/TASK.md --lane-name 1-3-dispatch --target w3:p9",
  );
  expect(parsed.ok).toBe(true);
  if (!parsed.ok) return;
  expect(parsed.argv[2]).toBe("my tasks/TASK.md");
});

// --------------------------------------------------------------------------
// Tokenising — the component whose failure mode is a silently mis-split path
// --------------------------------------------------------------------------

// --------------------------------------------------------------------------
// Signature attribution — the prefix is the lane, and the two parsers must agree
// --------------------------------------------------------------------------

/**
 * One table, asserted on both sides.
 *
 * `dispatch_bus.signature_lane` (Python) and `laneFromSignature` (TypeScript)
 * are two implementations of one rule, split across the language boundary. They
 * are the write and the read of the same field, so a disagreement is silent in
 * the worst way: the bus writes a signature the extension cannot attribute, and
 * the park never opens. `test_dispatch_param_derivation.py` asserts the same
 * table against the Python half; if these two ever list different cases, one of
 * the tests is wrong and the pairing has broken.
 */
const SIGNATURE_TABLE: Array<[string, string]> = [
  ["1-3_opencode_repo", "1-3"],
  ["w3:p9_opencode_repo", "w3:p9"],
  ["2-10_w9:p2_codex", "2-10"],
  ["no-underscore", ""],
  ["1-3-dispatch", ""],
  ["", ""],
];

describe("laneFromSignature", () => {
  for (const [signature, lane] of SIGNATURE_TABLE) {
    test(`${JSON.stringify(signature)} -> ${JSON.stringify(lane)}`, () => {
      expect(laneFromSignature(signature)).toBe(lane);
    });
  }
  test("undefined is not a lane", () => {
    expect(laneFromSignature(undefined)).toBe("");
  });
});

// --------------------------------------------------------------------------
// A flag never eats the next flag
// --------------------------------------------------------------------------

describe("an option never swallows the following option", () => {
  test("--highlight --risk is refused rather than consuming --risk", () => {
    // The original defect: `--highlight` took `--risk` as its value, so the
    // --risk option vanished entirely and the surviving bullet was the literal
    // text "--risk". The omission is invisible in the argv.
    const parsed = parseDispatchArgs(
      "--task T.md --lane-name 1-3-dispatch --target w3:p9 --highlight --risk x",
    );
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.reason).toContain("--highlight");
    expect(parsed.reason).toContain("--risk");
  });

  test("the refusal explains both ways to supply a value", () => {
    const parsed = parseDispatchArgs("--task --lane-name 1-3-dispatch");
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.reason).toContain("--task=<value>");
  });

  test("a single-dash value is still accepted", () => {
    // Only a leading "--" is refused. `-` is a legitimate argument elsewhere in
    // this CLI (`--handoff -` means stdin), so refusing it would be a new way
    // to reject valid input.
    const parsed = parseDispatchArgs(
      "--task T.md --lane-name 1-3-dispatch --target w3:p9 --worktree -",
    );
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.argv[parsed.argv.indexOf("--worktree") + 1]).toBe("-");
  });

  test("the inline form still works, so the refusal has an escape hatch", () => {
    // A value that genuinely starts with "--" must remain expressible.
    const parsed = parseDispatchArgs(
      "--task=T.md --lane-name=1-3-dispatch --target=w3:p9 --worktree=--weird",
    );
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.argv).toContain("--weird");
  });

  test("a trailing flag with no value at all is still caught", () => {
    const parsed = parseDispatchArgs("--task T.md --lane-name 1-3-dispatch --target");
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.reason).toContain("needs a value");
  });
});

describe("tokenizeArgs", () => {
  test("splits on whitespace", () => {
    expect(tokenizeArgs("a b  c")).toEqual(["a", "b", "c"]);
  });

  test("keeps a double-quoted run together", () => {
    expect(tokenizeArgs(`--task "a b/T.md"`)).toEqual(["--task", "a b/T.md"]);
  });

  test("keeps a single-quoted run together", () => {
    expect(tokenizeArgs(`--task 'a b/T.md'`)).toEqual(["--task", "a b/T.md"]);
  });

  test("an empty quoted argument is still an argument", () => {
    // Otherwise `--task ""` collapses away and the flag appears to be missing,
    // producing a different error than the one the caller caused.
    expect(tokenizeArgs(`--task "" --lane-name 1-3-dispatch`)).toEqual([
      "--task",
      "",
      "--lane-name",
      "1-3-dispatch",
    ]);
  });

  test("an unbalanced quote is refused rather than truncated", () => {
    // Half a path is never the right answer to a quoted argument.
    expect(tokenizeArgs(`--task "a b`)).toBeNull();
    expect(tokenizeArgs(`--task 'a b`)).toBeNull();
  });

  test("empty and blank input yields no tokens", () => {
    expect(tokenizeArgs("")).toEqual([]);
    expect(tokenizeArgs("   ")).toEqual([]);
    expect(tokenizeArgs(undefined)).toEqual([]);
  });

  test("a backslash-escaped space is one token", () => {
    expect(tokenizeArgs("a\\ b")).toEqual(["a b"]);
  });
});

test("no backslash ever enters the arguments the bus receives", () => {
  // The original defect: `'\n[NOTIFY] ...'` delivered literal escape sequences.
  // Nothing in this command should be able to reintroduce them, because the
  // report text is built in Python and never travels through an argument.
  const { calls, runner } = makeRunner();
  runDispatch(`--task T.md --lane-name 1-3-dispatch --target w3:p9`, {
    resolvePlugin: RESOLVE,
    runner,
  });
  expect(calls[0].argv.some((a) => a.includes("\\"))).toBe(false);
  expect(calls[0].argv.some((a) => a.includes("\n"))).toBe(false);
});

// --------------------------------------------------------------------------
// Exit-code pass-through
// --------------------------------------------------------------------------

test("exit 1 stays exit 1 and says the contract is the problem", () => {
  const { runner } = makeRunner({ status: 1, stderr: "dispatch: contract lint refused" });
  const result = runDispatch("--task T.md --lane-name 1-3-dispatch --target w3:p9", {
    resolvePlugin: RESOLVE,
    runner,
  });
  expect(result.ok).toBe(false);
  expect(result.code).toBe(EXIT_CONTRACT);
  expect(result.reason).toContain("contract");
});

test("exit 2 stays exit 2 and says a rule refused", () => {
  const { runner } = makeRunner({ status: 2, stderr: "dispatch: worktree already claimed" });
  const result = runDispatch("--task T.md --lane-name 1-3-dispatch --target w3:p9", {
    resolvePlugin: RESOLVE,
    runner,
  });
  expect(result.code).toBe(EXIT_REFUSED);
  expect(result.reason).toContain("rule refused");
});

test("the bus's own stderr survives into the reason", () => {
  const { runner } = makeRunner({ status: 2, stderr: "lane '1-1' already claims /tmp/wt" });
  const result = runDispatch("--task T.md --lane-name 1-3-dispatch --target w3:p9", {
    resolvePlugin: RESOLVE,
    runner,
  });
  // The bus names the colliding lane. Paraphrasing that away would send the
  // orchestrator looking somewhere other than where the collision is.
  expect(result.reason).toContain("1-1");
});

test("the two refusals are never flattened into one generic failure", () => {
  expect(describeRefusal(EXIT_CONTRACT, "x")).toContain("contract file");
  expect(describeRefusal(EXIT_REFUSED, "x")).toContain("nothing was renamed");
  expect(describeRefusal(EXIT_CONTRACT, "x")).not.toBe(describeRefusal(EXIT_REFUSED, "x"));
});

test("exit 3 is not reported as 'nothing was changed'", () => {
  // The whole point of the third code. Delivery can fail *after* the plan
  // commits, so the lane is recorded and holding its claim — telling the caller
  // nothing was written would be false.
  const reason = describeRefusal(EXIT_DELIVERY_FAILED, "worker pane is gone");
  expect(reason).not.toContain("nothing was renamed, written or delivered");
  expect(reason).toContain("worker pane is gone");
});

test("exit 3 preserves the existing dispatch identity", () => {
  const reason = describeRefusal(EXIT_DELIVERY_FAILED, "x");
  expect(reason).toContain("retry that exact delivery");
  expect(reason).toContain("do not mint a new lane or timestamp");
  expect(reason).not.toContain("NEW timestamp");
});

test("exit 3 passes through runDispatch unchanged", () => {
  const { runner } = makeRunner({ status: 3, stderr: "delivery failed after commit" });
  const result = runDispatch("--task T.md --lane-name 1-3-dispatch --target w3:p9", {
    resolvePlugin: RESOLVE,
    runner,
  });
  expect(result.code).toBe(EXIT_DELIVERY_FAILED);
  expect(result.reason).toContain("dispatch identity");
});

test("a killed bus is reported as broken, not as a refusal", () => {
  // status === null means a signal, not an exit. Reporting it as 2 would claim
  // "nothing was renamed, written or delivered" about a process that died
  // mid-flight, which is exactly when nothing is knowable.
  const result = runDispatch("--task T.md --lane-name 1-3-dispatch --target w3:p9", {
    resolvePlugin: RESOLVE,
    runner: () => ({ status: null, signal: "SIGKILL", stdout: "", stderr: "" }),
  });
  expect(result.ok).toBe(false);
  expect(result.phase).toBe("killed");
  expect(result.reason).toContain("SIGKILL");
  expect(result.reason).not.toContain("nothing was renamed");
});

test("an unexpected exit code is reported as the bus breaking", () => {
  expect(describeRefusal(127, "no such file")).toContain("unexpectedly");
});

test("a spawn failure is reported rather than thrown", () => {
  const result = runDispatch("--task T.md --lane-name 1-3-dispatch --target w3:p9", {
    resolvePlugin: RESOLVE,
    runner: () => ({ status: null, stdout: "", stderr: "", error: new Error("ENOENT") }),
  });
  expect(result.ok).toBe(false);
  expect(result.phase).toBe("spawn");
});

// --------------------------------------------------------------------------
// Plugin discovery — the command is global, so it must find its own bus
// --------------------------------------------------------------------------

test("the bus is found by walking up from a nested workspace", () => {
  const dir = mkdtempSync(path.join(tmpdir(), "dispatch-find-"));
  const nested = path.join(dir, "a", "b", "c");
  mkdirSync(nested, { recursive: true });
  const script = path.join(dir, "multiplexer", "herdr-dispatch", "bin", "dispatch_plugin.py");
  mkdirSync(path.dirname(script), { recursive: true });
  writeFileSync(script, "# stub\n");

  expect(findPlugin(nested)).toBe(script);
});

test("the bus is found when template is a submodule under parent checkout", () => {
  const dir = mkdtempSync(path.join(tmpdir(), "dispatch-parent-"));
  const script = path.join(dir, "template", "multiplexer", "herdr-dispatch", "bin", "dispatch_plugin.py");
  mkdirSync(path.dirname(script), { recursive: true });
  writeFileSync(script, "# stub\n");

  expect(findPlugin(dir)).toBe(script);
});

test("HERDR_DISPATCH_PLUGIN overrides the search", () => {
  const dir = mkdtempSync(path.join(tmpdir(), "dispatch-override-"));
  const script = path.join(dir, "custom_plugin.py");
  writeFileSync(script, "# stub\n");
  const previous = process.env.HERDR_DISPATCH_PLUGIN;
  process.env.HERDR_DISPATCH_PLUGIN = script;
  try {
    expect(findPlugin(tmpdir())).toBe(script);
  } finally {
    if (previous === undefined) delete process.env.HERDR_DISPATCH_PLUGIN;
    else process.env.HERDR_DISPATCH_PLUGIN = previous;
  }
});

test("a missing bus is reported with a remedy, not a stack trace", () => {
  const result = runDispatch("--task T.md --lane-name 1-3-dispatch --target w3:p9", {
    repoRoot: tmpdir(),
    resolvePlugin: () => null,
  });
  expect(result.ok).toBe(false);
  expect(result.phase).toBe("locate");
  expect(result.reason).toContain("HERDR_DISPATCH_PLUGIN");
});

test("the checked-in bus is where findPlugin says it is", () => {
  // Guards against a rename of the plugin landing without updating the
  // extension's idea of where to reach it.
  expect(findPlugin(REPO_ROOT)).toBe(path.join(PLUGIN_ROOT, "bin", "dispatch_plugin.py"));
});

// --------------------------------------------------------------------------
// The command adds no gates of its own
// --------------------------------------------------------------------------

test("the command re-implements no gate, no delivery and no state write", () => {
  // The rule: `/dispatch` is an argv hand-off. Every gate the bus owns must not
  // appear here, because two implementations would eventually disagree about
  // which exit code a given refusal produces — and the caller has no way to
  // tell which one it just talked to.
  //
  // Scanned against the TypeScript *identifier space*, not against raw text.
  // A substring grep for `claim_lane` could never fire in a TypeScript file,
  // which would make this test unfalsifiable; parsing the imports instead means
  // the assertion fails the moment someone imports the module directly.
  const source = readFileSync(
    path.join(REPO_ROOT, "agent", "omp", "extensions", "dispatch-omp", "slash.ts"),
    "utf8",
  );
  // Only import *statements*, not every `from "…"` in the file: a quoted
  // sentence like "run /dispatch from …" is prose, not a dependency.
  const imports = [...source.matchAll(/^\s*import\s.*?from\s+"([^"]+)"/gm)].map((m) => m[1]);

  // The file may reach node builtins, and nothing else. Importing a plugin
  // module would mean reaching for a policy decision this command must not
  // make for itself.
  expect(imports.length).toBeGreaterThan(0);
  for (const specifier of imports) {
    expect(specifier.startsWith("node:") || specifier.startsWith(".")).toBe(true);
  }

  const calls = [...source.matchAll(/\b([A-Za-z_$][\w$]*)\s*\(/g)].map((m) => m[1]);
  const busOwned = [
    "lint_task_contract",
    "audit_claim",
    "claim_lane",
    "assert_prompt_compliant",
    "validate_prompt",
    "build_notify",
    "buildLaneTokens",
  ];
  for (const name of busOwned) {
    expect(calls).not.toContain(name);
  }

  // Delivery and state writes belong to the bus. A direct `agent prompt` here
  // would open a second send path, which is what the bus exists to prevent.
  expect(calls).not.toContain("report_lane_metadata");
  expect(calls).not.toContain("notify");
  expect(source).not.toContain("ORCHESTRATOR_STATE");
  expect(source).not.toContain("update_lane");
});

test("the command never builds a shell command string", () => {
  const source = readFileSync(
    path.join(REPO_ROOT, "agent", "omp", "extensions", "dispatch-omp", "slash.ts"),
    "utf8",
  );
  // `exec`/`execSync` interpolate a string into a shell; `spawnSync` with an
  // argv array and `shell: false` does not. The import is the honest place to
  // check — a local variable also named `exec` is not a shell.
  const childProcessImport = [...source.matchAll(/import\s*\{([^}]*)\}\s*from\s*"node:child_process"/g)]
    .flatMap((m) => m[1].split(",").map((name) => name.trim()));
  expect(childProcessImport).toEqual(["spawnSync"]);

  // And the one spawn it does make passes an array with the shell off.
  expect(source).toContain("spawnSync");
  expect(source).toContain("shell: false");
  // The argv is built by spreading, never by joining into a string. A `.join(" ")`
  // here would put every value back through a tokeniser, which is the quoting
  // bug this command exists to remove.
  expect(/parsed\.argv\.join|argv\.join\(/.test(source)).toBe(false);
});

// --------------------------------------------------------------------------
// End to end against the real bus: no literal escapes reach the pane
// --------------------------------------------------------------------------

function resolvePython(): string {
  const candidates = [
    process.env.DISPATCH_TEST_PYTHON,
    path.resolve(REPO_ROOT, ".venv/bin/python"),
    "python3.13",
    "python3.12",
    "python3",
  ].filter(Boolean) as string[];
  for (const candidate of candidates) {
    try {
      const out = execFileSync(candidate, ["-c", "import sys; print(sys.version_info >= (3, 10))"], {
        encoding: "utf8",
      });
      if (out.trim() === "True") return candidate;
    } catch {
      // Try the next candidate.
    }
  }
  return "python3";
}

/**
 * A real repo, a real contract file and a real `herdr` on PATH.
 *
 * The whole point of the command is the bytes on the wire, so this drives the
 * actual Python bus with a stub Herdr rather than asserting on a mock's return
 * value. A test that only checked the argv could not tell whether the delivered
 * text had real newlines.
 */
function makeDispatchEnv() {
  const dir = mkdtempSync(path.join(tmpdir(), "dispatch-slash-"));
  const repo = path.join(dir, "repo");
  mkdirSync(repo, { recursive: true });
  execFileSync("git", ["init", "-q", repo]);
  execFileSync("git", ["-C", repo, "checkout", "-q", "-b", "feat/1-3"]);
  // A commit, because the branch is derived from `rev-parse --abbrev-ref HEAD`
  // and an unborn HEAD names no branch. That refusal is correct behaviour and
  // has its own test; here the fixture needs a real branch to derive.
  writeFileSync(path.join(repo, ".gitignore"), "*.md\n");
  execFileSync("git", ["-C", repo, "add", ".gitignore"]);
  execFileSync("git", ["-C", repo, "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-q", "-m", "init"]);

  // The bus reads the pane's cwd to derive the worktree, so the stub answers
  // `pane get` with this repo and records whatever it is asked to deliver.
  //
  // `HERDR_BIN_PATH` rather than PATH: the client prefers the path Herdr
  // injects so it reaches the *running* server's binary. Under a test that
  // injection points at a real server, so the override has to be explicit or
  // these tests would silently talk to whatever session ran them.
  const stub = path.join(dir, "herdr");
  writeFileSync(
    stub,
    [
      "#!/usr/bin/env python3",
      "import json, sys",
      "argv = sys.argv[1:]",
      "if argv[:2] == ['pane', 'get']:",
      `    print(json.dumps({'result': {'pane': {'pane_id': argv[2], 'cwd': ${JSON.stringify(repo)}}}}))`,
      "elif argv[:2] == ['agent', 'prompt']:",
      `    open(${JSON.stringify(path.join(dir, "delivered.txt"))}, 'a').write(argv[3] + '\\n')`,
      "else:",
      "    print('{}')",
      "",
    ].join("\n"),
  );
  execFileSync("chmod", ["+x", stub]);

  writeFileSync(
    path.join(repo, "TASK.md"),
    [
      "# 目标 (Outcome)",
      "实施总线参数精简并通过全量测试。",
      "",
      "# 验证 (Verification)",
      "pytest tests/",
      "",
      "# 约束 (Constraints)",
      "不得写入任何凭证。",
      "",
      "# 边界 (Boundaries)",
      "仅修改插件目录。",
      "",
      "# 迭代策略 (Iteration Policy)",
      "使用 rtk 控制输出, 走 to-spec 与 implement-spec",
      "",
      "# 完成条件 (Stop when)",
      "全部测试通过。",
      "",
      "# 暂停条件 (Pause if)",
      "遇到跨平台路径歧义立即暂停。",
      "",
    ].join("\n"),
  );

  return { dir, repo, stub, deliveredFile: path.join(dir, "delivered.txt") };
}

/**
 * Point the bus at the stub Herdr.
 *
 * Saved and restored per test rather than set once in `beforeAll`, because
 * `HERDR_BIN_PATH` is read by a subprocess: a leaked override would make every
 * later test in the file talk to a stub instead of a real server.
 */
function withStubHerdr<T>(env: { dir: string; stub: string }, body: () => T): T {
  const restore: Record<string, string | undefined> = {};
  const set = (key: string, value: string | undefined) => {
    restore[key] = process.env[key];
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  };

  set("HERDR_BIN_PATH", env.stub);
  // PATH too, so a `herdr` resolved by name finds the same stub.
  set("PATH", `${env.dir}:${process.env.PATH}`);
  // The socket must go: a stale path would let the client prefer the running
  // server over the stub binary the override just pointed at.
  set("HERDR_SOCKET_PATH", undefined);
  set("HERDR_PANE_ID", "w3:pB");
  // These tests dispatch from a temp repo, which has no checkout above it, so
  // the bus has to be named explicitly. This is the same escape hatch an
  // operator gets for a fork or a worktree layout.
  set("HERDR_DISPATCH_PLUGIN", path.join(PLUGIN_ROOT, "bin", "dispatch_plugin.py"));

  try {
    return body();
  } finally {
    for (const [key, value] of Object.entries(restore)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

describe("against the real bus", () => {
  test("a minimal /dispatch reaches the bus and delivers real newlines", () => {
    const env = makeDispatchEnv();
    withStubHerdr(env, () => {
      const result = runDispatch(
        `--task ${env.repo}/TASK.md --lane-name 1-3-dispatch --target w3:p9`,
        { repoRoot: env.repo, python: resolvePython() },
      );
      expect(result.ok).toBe(true);

      const delivered = readFileSync(env.deliveredFile, "utf8");
      // The defect this whole design chain exists to prevent.
      expect(delivered).not.toContain("\\n");
      expect(delivered).toContain("[DISPATCH]");
      // And the derived values actually landed, rather than being left blank.
      expect(result.stdout).toContain("feat/1-3");
      expect(delivered).toContain("Task: ");
      expect(delivered).toContain("/repo/TASK.md");
    });
  });

  test("a bad lane name exits 2 and delivers nothing", () => {
    const env = makeDispatchEnv();
    withStubHerdr(env, () => {
      const result = runDispatch(
        `--task ${env.repo}/TASK.md --lane-name research-agy --target w3:p9`,
        { repoRoot: env.repo, python: resolvePython() },
      );
      expect(result.ok).toBe(false);
      expect(result.code).toBe(EXIT_REFUSED);
      // Zero side effects: the bus refuses before it renames or persists, so
      // nothing was ever written to the delivery file.
      expect(existsSync(env.deliveredFile)).toBe(false);
    });
  });

  test("a malformed contract exits 1, not 2", () => {
    const env = makeDispatchEnv();
    writeFileSync(path.join(env.repo, "BAD.md"), "# 目标\n做点事\n");
    withStubHerdr(env, () => {
      const result = runDispatch(
        `--task ${env.repo}/BAD.md --lane-name 1-3-dispatch --target w3:p9`,
        { repoRoot: env.repo, python: resolvePython() },
      );
      expect(result.code).toBe(EXIT_CONTRACT);
      expect(existsSync(env.deliveredFile)).toBe(false);
    });
  });

  test("a delivery failure after commit is exit 3, not exit 2", () => {
    // The asymmetry the third code exists for. Commit succeeds, delivery fails:
    // the lane is recorded as working and holds its claim. Reporting exit 2
    // would say "nothing was renamed, written or delivered", which is false,
    // and would tell the operator to re-run — into a claim collision with the
    // lane they just created.
    const env = makeDispatchEnv();
    writeFileSync(
      env.stub,
      [
        "#!/usr/bin/env python3",
        "import json, sys",
        "argv = sys.argv[1:]",
        "if argv[:2] == ['pane', 'get']:",
        `    print(json.dumps({'result': {'pane': {'pane_id': argv[2], 'cwd': ${JSON.stringify(env.repo)}}}}))`,
        "elif argv[:2] == ['agent', 'prompt']:",
        "    print('pane is gone', file=sys.stderr)",
        "    sys.exit(1)",
        "else:",
        "    print('{}')",
        "",
      ].join("\n"),
    );
    withStubHerdr(env, () => {
      const result = runDispatch(
        `--task ${env.repo}/TASK.md --lane-name 1-3-dispatch --target w3:p9`,
        { repoRoot: env.repo, python: resolvePython() },
      );
      expect(result.ok).toBe(false);
      expect(result.code).not.toBe(EXIT_REFUSED);
      // Lost confirmation is not proof that nothing was sent. The same
      // dispatch identity must be retried rather than minting a second task.
      expect(result.reason).toContain("not confirmed");
      expect(result.reason).toContain("exact delivery");
      expect(result.reason).not.toContain("NEW timestamp");
    });
  });

  test("a pane the bus cannot read refuses at exit 2 rather than dispatching unclaimed", () => {
    // The derivation the whole simplification rests on. If it silently produced
    // an empty worktree, the claim gate would not run and two lanes would be
    // free to share one directory.
    const env = makeDispatchEnv();
    writeFileSync(
      env.stub,
      [
        "#!/usr/bin/env python3",
        "import json, sys",
        "argv = sys.argv[1:]",
        "if argv[:2] == ['pane', 'get']:",
        "    print(json.dumps({'error': {'code': 'pane_not_found'}}))",
        "else:",
        "    print('{}')",
        "",
      ].join("\n"),
    );
    withStubHerdr(env, () => {
      const result = runDispatch(
        `--task ${env.repo}/TASK.md --lane-name 1-3-dispatch --target w3:p9`,
        { repoRoot: env.repo, python: resolvePython() },
      );
      expect(result.code).toBe(EXIT_REFUSED);
      expect(existsSync(env.deliveredFile)).toBe(false);
    });
  });
});