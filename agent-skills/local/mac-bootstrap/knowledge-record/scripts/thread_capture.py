#!/usr/bin/env python3
"""Current-thread capture helpers for knowledge-record suggest."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Mapping


@dataclass(frozen=True)
class ThreadMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ThreadPacket:
    messages: list[ThreadMessage]

    def combined_text(self) -> str:
        return "\n".join(f"{message.role}: {message.content}" for message in self.messages)


def _packet_from_json(source: str) -> ThreadPacket:
    data = json.loads(source)
    messages = [
        ThreadMessage(role=str(item["role"]).strip(), content=str(item["content"]).strip())
        for item in data
        if str(item.get("content", "")).strip()
    ]
    if not messages:
        raise RuntimeError("knowledge-record suggest requires non-empty current agent thread data")
    return ThreadPacket(messages=messages)


def _packet_from_summary(summary: str) -> ThreadPacket:
    cleaned = summary.strip()
    if not cleaned:
        raise RuntimeError("knowledge-record suggest requires non-empty current agent thread data")
    return ThreadPacket(
        messages=[
            ThreadMessage(role="user", content="要求记录当前 agent 会话。"),
            ThreadMessage(role="assistant", content=cleaned),
        ]
    )


def capture_current_thread(
    env: Mapping[str, str] | None = None,
    *,
    thread_json: str | None = None,
    thread_summary: str | None = None,
) -> ThreadPacket:
    """Capture current agent thread from runtime-provided JSON.

    Agent runtimes should provide either:
    - thread_json / KNOWLEDGE_RECORD_THREAD_JSON as JSON list of {role, content}
    - thread_summary / KNOWLEDGE_RECORD_THREAD_SUMMARY as a concise current-thread summary
    """
    runtime_env = env or os.environ
    source = thread_json or runtime_env.get("KNOWLEDGE_RECORD_THREAD_JSON", "")
    if source.strip():
        return _packet_from_json(source)

    summary = thread_summary or runtime_env.get("KNOWLEDGE_RECORD_THREAD_SUMMARY", "")
    if summary.strip():
        return _packet_from_summary(summary)

    raise RuntimeError("knowledge-record suggest requires current agent thread data")
