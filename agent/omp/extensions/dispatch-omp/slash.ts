/**
 * `/dispatch` — the global slash command for the unified dispatch bus.
 *
 * Why a command and not a skill
 * -----------------------------
 * The previous round of this design fixed a defect whose whole cause was
 * hand-quoting: `herdr agent prompt p '\n[NOTIFY] ...'` keeps the backslash-n as
 * two literal characters, so the report rendered as one long line. The fix was
 * to build the text in Python. But the *calling* was still manual — a path, six
 * arguments and a set of newlines the orchestrator had to remember to delegate.
 *
 * A slash command removes the remaining manual part structurally rather than by
 * convention: the host parses `/dispatch --task … --lane-name …` into an argv
 * array, and that array is handed to `spawnSync` with `shell: false`. There is
 * no string for a quote to escape into, so a path with a space in it works and
 * `'\n'` cannot survive as two characters.
 *
 * What this file deliberately does NOT do
 * ---------------------------------------
 * It does not re-implement a single gate. No lint, no claim check, no lane-name
 * validation, no atomicity — all of that lives in `dispatch_plugin.py dispatch`,
 * and this is a thin translation from command-line arguments to argv.
 *
 * That is not just tidiness. The bus's exit codes are the contract an
 * orchestrator programs against: `1` means "your task file is malformed",
 * `2` means "this lane is unsafe". A second implementation here would eventually
 * disagree with the first about which is which, and an orchestrator that
 * learned to trust the code would be trusting the wrong one. So the command
 * **passes the bus's exit code through unchanged** and prints the bus's own
 * stderr rather than paraphrasing it.
 *
 * On a refusal there is nothing to report: the bus refuses before it renames
 * anything, writes state or delivers, so this file has nothing to undo.
 */

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

/**
 * Exit codes, restated here so the behaviour is testable without a bus.
 *
 * `1` — the task contract is malformed. Fix the file.
 * `2` — a rule refused: a bad lane name, a worktree collision, a failed
 *       derivation. Nothing was renamed, written or delivered.
 * `3` — delivery failed *after* the plan committed. The lane is recorded and
 *       holding its claim, so this is the one case where re-running is wrong:
 *       it would collide with the lane this run created. Unwind first.
 *
 * Anything else is the bus breaking, which is not the caller's fault and must
 * not be flattened into any of the above.
 */
export const EXIT_CONTRACT = 1;
export const EXIT_REFUSED = 2;
export const EXIT_DELIVERY_FAILED = 3;

/** Subcommand and script, kept together so they cannot drift apart. */
export const PLUGIN_RELATIVE = path.join(
  "multiplexer",
  "herdr-dispatch",
  "bin",
  "dispatch_plugin.py",
);

/**
 * Locate `dispatch_plugin.py` from a repository root.
 *
 * Walks upward because the command is global — it must work from any workspace,
 * including one nested several directories below the checkout. An env override
 * comes first so a fork or a worktree layout does not need a search that
 * happens to fail.
 */
export function findPlugin(repoRoot) {
  const override = process.env.HERDR_DISPATCH_PLUGIN;
  if (override && existsSync(override)) return override;

  let dir = path.resolve(repoRoot ?? process.cwd());
  for (;;) {
    const candidate = path.join(dir, PLUGIN_RELATIVE);
    if (existsSync(candidate)) return candidate;
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

/**
 * Split a command's argument string into tokens, honouring quotes.
 *
 * The host already parses `/dispatch <args>`, but it hands the remainder over as
 * one string and does not promise to have stripped quotes. Splitting on
 * whitespace alone would turn `--task "my tasks/TASK.md"` into three tokens and
 * dispatch the wrong file — so quotes are handled here rather than assumed.
 *
 * Unterminated quotes are a refusal, not a silent truncation: half a path is
 * never the right answer to a quoted argument.
 */
export function tokenizeArgs(raw) {
  const text = String(raw ?? "");
  const tokens = [];
  let current = "";
  let quote = null;
  let started = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (quote) {
      if (char === quote) {
        quote = null;
      } else if (char === "\\" && text[i + 1] === quote) {
        // An escaped quote inside a quoted run is a literal quote, not a
        // terminator; otherwise a path containing one truncates silently.
        current += quote;
        i += 1;
      } else {
        current += char;
      }
      continue;
    }
    if (char === '"' || char === "'") {
      quote = char;
      // An empty quoted string is still a supplied argument, so mark it started
      // rather than letting it collapse to nothing.
      started = true;
      continue;
    }
    if (char === "\\" && text[i + 1] !== undefined && /\s/.test(text[i + 1])) {
      // An escaped space is one token, not a separator.
      current += text[i + 1];
      started = true;
      i += 1;
      continue;
    }
    if (/\s/.test(char)) {
      if (started) tokens.push(current);
      current = "";
      started = false;
      continue;
    }
    current += char;
    started = true;
  }

  if (quote) return null;
  if (started) tokens.push(current);
  return tokens;
}

/**
 * Parse `/dispatch` arguments into a bus argv.
 *
 * Returns argv rather than an object for one reason: the bus is an argv-shaped
 * interface, and turning its arguments into a structured object only to map
 * them straight back would be a place for a field to be dropped.
 *
 * `--task`, `--lane-name` and `--target` are the required minimum. Everything
 * else the bus understands is passed through untouched — including `--repo`,
 * which has to precede the subcommand, hence the reordering.
 *
 * @returns {{ok: true, argv: string[]} | {ok: false, reason: string}}
 */
export function parseDispatchArgs(raw) {
  const tokens = tokenizeArgs(raw);
  if (tokens === null) {
    return { ok: false, reason: "unbalanced quote in the arguments" };
  }

  const known = new Set([
    "--task",
    "--lane-name",
    "--target",
    "--signature",
    "--lane",
    "--worktree",
    "--branch",
    "--highlight",
    "--risk",
    "--repo",
  ]);
  // Repeatable flags: passing one twice must not collapse to the last value.
  const repeatable = new Set(["--highlight", "--risk"]);

  const values = new Map();
  const repeated = new Map();

  for (let i = 0; i < tokens.length; i += 1) {
    const token = tokens[i];
    const eq = token.indexOf("=");
    const flag = eq > 0 ? token.slice(0, eq) : token;
    let value = eq > 0 ? token.slice(eq + 1) : null;

    if (!known.has(flag)) {
      return {
        ok: false,
        reason:
          `unknown option ${flag}. /dispatch accepts ` +
          `--task, --lane-name, --target, and optionally --signature, --lane, ` +
          `--worktree, --branch, --highlight, --risk, --repo. ` +
          `Anything else belongs to the task contract, not the bus.`,
      };
    }

    if (value === null) {
      i += 1;
      value = tokens[i];
      if (value === undefined) {
        return { ok: false, reason: `${flag} needs a value` };
      }
    }

    if (repeatable.has(flag)) {
      const list = repeated.get(flag) ?? [];
      list.push(value);
      repeated.set(flag, list);
    } else if (values.has(flag)) {
      return { ok: false, reason: `${flag} given more than once` };
    } else {
      values.set(flag, value);
    }
  }

  const missing = ["--task", "--lane-name", "--target"].filter(
    (flag) => !values.has(flag),
  );
  if (missing.length > 0) {
    return {
      ok: false,
      reason:
        `missing ${missing.join(", ")}. The minimal call is\n` +
        `  /dispatch --task .dispatch/TASK.md --lane-name 1-3-dispatch --target w3:p9\n` +
        `The lane id, worktree, branch and report bullets are all derived.`,
    };
  }

  // `--repo` is a plugin-level option, so it must come before the subcommand.
  // Everything else belongs to `dispatch`.
  const argv = [];
  if (values.has("--repo")) argv.push("--repo", values.get("--repo"));
  argv.push("dispatch");
  for (const flag of ["--task", "--lane-name", "--target", "--signature", "--lane", "--worktree", "--branch"]) {
    if (values.has(flag)) argv.push(flag, values.get(flag));
  }
  for (const flag of ["--highlight", "--risk"]) {
    for (const value of repeated.get(flag) ?? []) argv.push(flag, value);
  }
  return { ok: true, argv };
}

/**
 * Run the bus and hand back its verdict unaltered.
 *
 * `spawnSync` with an argv array and `shell: false` is the load-bearing part of
 * this file. A shell string here would reintroduce exactly the class of defect
 * the command exists to remove.
 *
 * Injection points (`runner`, `resolvePlugin`) exist so the tests can exercise
 * argument forwarding and exit-code pass-through without a live Herdr.
 */
export function runDispatch(raw, { repoRoot, python, runner, resolvePlugin } = {}) {
  const parsed = parseDispatchArgs(raw);
  if (!parsed.ok) return { ok: false, phase: "args", reason: parsed.reason };

  const plugin = (resolvePlugin ?? findPlugin)(repoRoot);
  if (!plugin) {
    return {
      ok: false,
      phase: "locate",
      reason:
        `could not find ${PLUGIN_RELATIVE} above ${repoRoot ?? process.cwd()}. ` +
        "Set HERDR_DISPATCH_PLUGIN to its absolute path, or run /dispatch from " +
        "inside the checkout.",
    };
  }

  const exec = runner ?? spawnSync;
  const result = exec(
    python ?? process.env.HERDR_DISPATCH_PYTHON ?? "python3",
    [plugin, ...parsed.argv],
    {
      cwd: repoRoot ?? process.cwd(),
      encoding: "utf8",
      shell: false,
    },
  );

  if (result.error) {
    return { ok: false, phase: "spawn", reason: `dispatch bus did not run: ${result.error.message}` };
  }

  const stdout = String(result.stdout ?? "");
  const stderr = String(result.stderr ?? "").trim();

  // A null status means the bus was killed by a signal rather than exiting.
  // Reporting that as exit 2 would claim "nothing was renamed, written or
  // delivered" — a promise no one can make about a process that was killed
  // mid-flight — so it is reported as the bus breaking instead.
  if (typeof result.status !== "number") {
    return {
      ok: false,
      phase: "killed",
      signal: result.signal ?? null,
      reason:
        `the dispatch bus was killed by signal ${result.signal ?? "unknown"} ` +
        "rather than exiting. Its state is unknown — run " +
        "`dispatch_plugin.py status` before retrying, because a retry may " +
        "collide with a lane the killed run had already recorded.",
      stdout,
      stderr,
    };
  }

  const code = result.status;

  if (code === 0) return { ok: true, phase: "dispatch", code, stdout, stderr };

  // Pass the code through rather than remapping it. Exit 1 and exit 2 mean
  // different things to the caller, and collapsing them into one "failed" is
  // how an orchestrator ends up editing a correct task file because a lane
  // collided.
  return {
    ok: false,
    phase: "refused",
    code,
    reason: describeRefusal(code, stderr),
    stdout,
    stderr,
  };
}

/** Turn a bus exit code into a reason the caller can act on. */
export function describeRefusal(code, stderr) {
  const detail = String(stderr ?? "").trim();
  switch (code) {
    case EXIT_CONTRACT:
      return `the task contract was refused (exit 1) — fix the contract file.\n${detail}`;
    case EXIT_REFUSED:
      return `a dispatch rule refused (exit 2) — nothing was renamed, written or delivered.\n${detail}`;
    case EXIT_DELIVERY_FAILED:
      // The one case where "just run it again" is the wrong advice. The plan
      // committed before delivery, so the lane holds its own claim.
      return (
        `delivery failed after the dispatch was committed (exit 3) — the lane is ` +
        `recorded as working and holds its worktree, but nothing was sent.\n${detail}\n` +
        "Do NOT re-run /dispatch: the claim gate will refuse it, because the " +
        "claim is held by the lane this run created. Re-deliver by hand, or " +
        "close the lane out first."
      );
    default:
      return `the dispatch bus failed unexpectedly (exit ${code}).\n${detail}`;
  }
}

/** One-line description shown in the command palette. */
export const DISPATCH_DESCRIPTION = [
  "Dispatch a lane through the unified bus: lint, claim, rename, timestamp, state flush, deliver.",
  "",
  "Usage: /dispatch --task TASK.md --lane-name 1-3-dispatch --target w3:p9",
  "",
  "Required: --task, --lane-name, --target.",
  "Optional: --signature, --lane, --worktree, --branch, --highlight, --risk, --repo.",
  "",
  "The lane id, worktree, branch and report bullets are derived, not typed.",
  "Exit 1 = the contract is malformed; fix the file.",
  "Exit 2 = a rule refused; nothing was changed.",
  "Exit 3 = delivery failed after commit; the lane holds its own claim, so unwind before retrying.",
].join("\n");

/**
 * Register `/dispatch` on an omp ExtensionAPI.
 *
 * The only thing this adds to the bus is a way to reach it. Every gate, every
 * exit code and all of the atomicity stay inside `dispatch_plugin.py`.
 */
export function registerDispatchCommand(pi, options = {}) {
  if (typeof pi?.registerCommand !== "function") return false;

  pi.registerCommand("dispatch", {
    description: DISPATCH_DESCRIPTION,
    handler: async (args, ctx) => {
      const result = runDispatch(args, {
        repoRoot: ctx?.cwd ?? options.repoRoot,
        python: options.python,
        runner: options.runner,
        resolvePlugin: options.resolvePlugin,
      });

      if (result.ok) {
        ctx?.ui?.notify?.("dispatch: lane dispatched", "info");
        // Surface the receipt. The bus prints the worktree, branch and handoff
        // it actually committed to, which is the only record of what was
        // derived on the caller's behalf.
        ctx?.ui?.notify?.(result.stdout.trim() || "dispatch: lane dispatched", "info");
        return;
      }

      // A refusal reason is worth an aside, not just a toast: the bus names the
      // colliding lane or the failed derivation, and losing that to a truncated
      // notification would send the orchestrator looking in the wrong place.
      const reason = result.reason ?? "dispatch refused";
      ctx?.ui?.notify?.(reason.split("\n")[0], "error");
      // What to do next differs per exit code, so it is not a fixed string.
      // Telling someone to re-run after a post-commit delivery failure is how
      // a lane ends up wedged against its own claim.
      const next =
        result.code === EXIT_DELIVERY_FAILED
          ? "Do NOT re-run /dispatch — the lane this run created holds its own claim. Unwind first."
          : "Nothing was renamed, no state was written and no prompt was delivered. " +
            "Fix the cause above and re-run /dispatch.";
      try {
        pi.sendUserMessage?.(
          `Dispatch refused (${result.phase}${result.code ? `, exit ${result.code}` : ""}).\n\n${reason}\n\n` +
            next,
          { deliverAs: "aside", attribution: "agent" },
        );
      } catch {
        // A refused steer must never break the command.
      }
    },
  });

  return true;
}