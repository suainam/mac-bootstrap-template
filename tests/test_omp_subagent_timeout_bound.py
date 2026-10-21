"""Behavioural tests for the managed `subagent-timeout-bound` OMP extension.

The extension's job is mechanical: when a `task` subagent hits
`task.maxRuntimeMs`, capture a bounded snapshot and refuse a resume that keeps
exploring. These tests drive the real factory with synthetic ExtensionAPI
events — no source-text assertions, no live model calls.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXTENSION = REPO_ROOT / "agent" / "omp" / "extensions" / "subagent-timeout-bound.ts"
MANIFEST = REPO_ROOT / "agent" / "omp" / "extensions.json"

pytestmark = pytest.mark.skipif(
    shutil.which("bun") is None,
    reason="bun is required to execute the TypeScript extension",
)

HARNESS = r"""
import ext, { buildSnapshot, parseTimeout } from "__EXT__"

type Handler = (event: Record<string, unknown>) => Promise<unknown>
type FactoryApi = Parameters<typeof ext>[0]

const handlers = new Map<string, Handler>()
const sent: Array<Record<string, unknown>> = []
const api = {
  on: ((name: string, fn: Handler) => {
    handlers.set(name, fn)
  }) as FactoryApi["on"],
  sendMessage: ((message: Record<string, unknown>) => {
    sent.push(message)
  }) as FactoryApi["sendMessage"],
}
ext(api as FactoryApi)

const HOST_TIMEOUT_TEXT = [
  "Subagent runtime limit exceeded (task.maxRuntimeMs=3000)",
  "Partial evidence: modified template/agent/omp/extensions.json",
].join("\n")

const out: Record<string, unknown> = {}
out.sync = await handlers.get("tool_result")!({
  toolName: "task",
  isError: true,
  content: [{ type: "text", text: HOST_TIMEOUT_TEXT }],
  details: { results: [{ id: "Task-2", exitCode: 1 }] },
})
out.resume = await handlers.get("tool_call")!({
  toolName: "task",
  input: { context: "x", tasks: [{ task: "resume Task-2 and keep exploring" }] },
})
out.writeBlocked = await handlers.get("tool_call")!({
  toolName: "write",
  input: { path: "agent://Task-2", content: "continue work" },
})
out.writeAllowed = (await handlers.get("tool_call")!({
  toolName: "write",
  input: { path: "notes.txt", content: "hello" },
})) ?? null
out.fresh = (await handlers.get("tool_call")!({
  toolName: "task",
  input: { context: "x", tasks: [{ task: "narrow task on another file" }] },
})) ?? null
await handlers.get("message_end")!({
  message: {
    role: "custom",
    customType: "async-result",
    content: [{ type: "text", text: `[async-result] Task-3\n${HOST_TIMEOUT_TEXT}` }],
    details: { jobs: [{ jobId: "Task-3" }] },
  },
})
out.asyncMessage = sent.at(-1) ?? null
const beforeQuiet = sent.length
await handlers.get("message_end")!({
  message: { role: "custom", customType: "async-result", content: "job finished fine" },
})
out.quietEmitted = sent.length - beforeQuiet
out.nonTimeout = parseTimeout("Subagent exited 1: boom")
out.boundedLength = buildSnapshot(
  { agentId: "A", maxRuntimeMs: 1000, closedAt: 0 },
  "x".repeat(9000),
).length
console.log(JSON.stringify(out))
"""


def _run_harness() -> dict[str, object]:
    harness = HARNESS.replace("__EXT__", str(EXTENSION))
    result = subprocess.run(
        ["bun", "run", "-"],
        input=harness,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def harness() -> dict[str, object]:
    return _run_harness()


def test_timeout_result_emits_bounded_snapshot(harness: dict[str, object]) -> None:
    sync = harness["sync"]
    assert isinstance(sync, dict)
    context = sync["additionalContext"]
    assert isinstance(context, str)
    assert context.startswith("SUBAGENT CLOSED FOR EXPLORATION")
    assert "agent: Task-2" in context
    assert "task.maxRuntimeMs=3000ms exceeded" in context
    assert "modified template/agent/omp/extensions.json" in context
    assert "Do not resume or re-spawn this agent" in context


def test_resume_of_closed_agent_is_blocked(harness: dict[str, object]) -> None:
    resume = harness["resume"]
    assert isinstance(resume, dict)
    assert resume["block"] is True
    reason = resume["reason"]
    assert isinstance(reason, str)
    assert "Task-2" in reason
    assert "closed for exploration" in reason
    assert "spawn a new agent" in reason


def test_write_resume_of_closed_agent_is_blocked(harness: dict[str, object]) -> None:
    write_blocked = harness["writeBlocked"]
    assert isinstance(write_blocked, dict)
    assert write_blocked["block"] is True
    reason = write_blocked["reason"]
    assert isinstance(reason, str)
    assert "Task-2" in reason
    assert "closed for exploration" in reason
    assert "Messaging/resuming this agent is disabled" in reason


def test_unrelated_write_is_not_blocked(harness: dict[str, object]) -> None:
    assert harness["writeAllowed"] is None

def test_unrelated_spawn_is_not_blocked(harness: dict[str, object]) -> None:
    assert harness["fresh"] is None


def test_async_result_message_emits_snapshot(harness: dict[str, object]) -> None:
    message = harness["asyncMessage"]
    assert isinstance(message, dict)
    assert message["customType"] == "subagent-timeout-bound"
    content = message["content"]
    assert isinstance(content, str)
    assert content.startswith("SUBAGENT CLOSED FOR EXPLORATION")
    assert "Task-3" in content


def test_non_timeout_async_result_is_ignored(harness: dict[str, object]) -> None:
    assert harness["quietEmitted"] == 0


def test_non_timeout_text_is_not_matched(harness: dict[str, object]) -> None:
    assert harness["nonTimeout"] is None


def test_snapshot_is_bounded(harness: dict[str, object]) -> None:
    length = harness["boundedLength"]
    assert isinstance(length, int)
    # 1500-byte tail plus fixed scaffolding; never proportional to input size.
    assert length < 2500


def test_manifest_registers_local_extension() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    locals_ = [entry for entry in manifest["extensions"] if entry.get("kind") == "local"]
    assert {
        "kind": "local",
        "package": "agent/omp/extensions/subagent-timeout-bound.ts",
        "target": "subagent-timeout-bound.ts",
    } in locals_
    # The pinned registry entry must survive alongside it.
    assert any(
        entry.get("package") == "@narumitw/pi-typesafe" and entry.get("version") == "0.1.1"
        for entry in manifest["extensions"]
    )
