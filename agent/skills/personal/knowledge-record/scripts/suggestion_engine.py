#!/usr/bin/env python3
"""Rule-guided record suggestion engine."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from argparse import Namespace
from dataclasses import dataclass, replace
from typing import Any, Mapping

from evidence_collect import EvidencePacket
from thread_capture import ThreadPacket


CARD_SIGNALS = ("可复用", "规则", "方法", "模式", "经验", "沉淀", "流程")
ADR_SIGNALS = ("决定", "决策", "边界", "取舍", "方案", "架构", "owner", "委托")
DAILY_SIGNALS = ("完成", "实现", "测试", "验证", "推进", "总结")


@dataclass(frozen=True)
class RecordDraft:
    record_type: str
    title: str
    content: str
    background: str | None
    tags: str
    why_record: str
    references: str | None
    agent_type: str
    suggestion_reason: str
    confidence: float

    def with_update(self, **changes: str) -> "RecordDraft":
        return replace(self, **changes)

    def to_record_args(
        self,
        *,
        date: str | None = None,
        db_path: str | None = None,
        project_path: str | None = None,
    ) -> Namespace:
        return Namespace(
            type=self.record_type,
            title=self.title,
            content=self.content,
            background=self.background,
            tags=self.tags,
            impact=None,
            is_actionable=False,
            references=self.references,
            project=None,
            expires_at=None,
            why_record=self.why_record,
            agent=self.agent_type,
            session_id=None,
            message_id=None,
            project_path=project_path,
            date=date,
            db_path=db_path,
            dry_run=False,
            no_vault_init=False,
        )


def _has_any(text: str, signals: tuple[str, ...]) -> bool:
    return any(signal in text for signal in signals)


def _classification_text(thread: ThreadPacket) -> str:
    assistant_text = "\n".join(
        message.content for message in thread.messages if message.role == "assistant"
    ).strip()
    return assistant_text or thread.combined_text()


def choose_record_type(thread: ThreadPacket, evidence: EvidencePacket) -> tuple[str, str, float]:
    text = _classification_text(thread)
    if _has_any(text, CARD_SIGNALS):
        return ("card", "命中可复用规则、方法或流程信号，按优先级选择知识卡片。", 0.86)
    if _has_any(text, ADR_SIGNALS):
        return ("adr", "命中决策、边界或取舍信号，选择架构决策记录。", 0.8)
    return ("daily", "主要体现本次会话完成事项，选择会话总结记录。", 0.68)


def _clip(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    return compact[:limit]


def _chinese_excerpt(text: str, limit: int = 160, *, preserve_technical: bool = False) -> str:
    compact = _clip(text, limit)
    cjk_count = sum(1 for char in compact if "\u4e00" <= char <= "\u9fff")
    latin_count = sum(1 for char in compact if char.isascii() and char.isalpha())
    if cjk_count > 0 and (cjk_count >= latin_count or (preserve_technical and cjk_count * 2 >= latin_count)):
        return compact.strip(" ，。；：、")

    allowed = []
    for char in text:
        if "\u4e00" <= char <= "\u9fff" or char.isdigit() or char in "，。；：、（）":
            allowed.append(char)
        elif char.isspace() and allowed and allowed[-1] != " ":
            allowed.append(" ")
    excerpt = "".join(allowed).strip(" ，。；：、")
    return excerpt[:limit] or "本次会话形成了可沉淀内容"


def _deterministic_draft(
    thread: ThreadPacket,
    evidence: EvidencePacket,
    *,
    agent_type: str,
) -> RecordDraft:
    record_type, reason, confidence = choose_record_type(thread, evidence)
    thread_summary = _chinese_excerpt(thread.combined_text(), limit=320, preserve_technical=True)
    evidence_summary = _chinese_excerpt(evidence.combined_text(), limit=120)
    refs = ";".join(evidence.references) if evidence.references else None

    if record_type == "card":
        return RecordDraft(
            record_type="card",
            title="沉淀本次会话的可复用知识",
            content=f"本次会话提炼出可复用做法：{thread_summary}。结合仓库证据：{evidence_summary}。",
            background=f"当前线程围绕可复用规则、方法或流程沉淀展开。{evidence_summary}",
            tags="知识管理,记录生成,可复用知识",
            why_record="需要把本次会话中的可复用知识沉淀为后续可检索记录。",
            references=refs,
            agent_type=agent_type,
            suggestion_reason=reason,
            confidence=confidence,
        )
    if record_type == "adr":
        return RecordDraft(
            record_type="adr",
            title="记录本次会话形成的决策边界",
            content=f"本次会话形成了明确决策：{thread_summary}。相关仓库证据：{evidence_summary}。",
            background=f"当前线程涉及决策、边界或取舍，需要保留上下文。{thread_summary}",
            tags="知识管理,架构决策,记录契约",
            why_record="需要保留本次会话形成的决策边界，避免后续重复讨论或误用入口。",
            references=refs or "当前会话和工作区证据",
            agent_type=agent_type,
            suggestion_reason=reason,
            confidence=confidence,
        )
    return RecordDraft(
        record_type="daily",
        title="总结本次会话完成事项",
        content=f"本次会话完成了以下事项：{thread_summary}。验证和命令证据：{evidence_summary}。",
        background=None,
        tags="知识管理,会话总结,工作记录",
        why_record="需要保留本次会话完成事项，便于后续日报或工作回顾复用。",
        references=refs,
        agent_type=agent_type,
        suggestion_reason=reason,
        confidence=confidence,
    )


def build_draft_prompt(
    thread: ThreadPacket,
    evidence: EvidencePacket,
    *,
    fallback: RecordDraft,
) -> str:
    """Build a compact JSON-only prompt for an optional drafting backend."""
    return "\n".join(
        [
            "你是 knowledge-record 的中文知识沉淀起草器。",
            "请只输出 JSON，不要 Markdown，不要解释。",
            f"固定 record_type: {fallback.record_type}",
            f"固定 agent_type: {fallback.agent_type}",
            "字段必须包含：title, content, background, tags, why_record, references。",
            "要求：标题、正文、标签、why_record 必须使用中文；tags 用英文逗号分隔；不要编造证据。",
            "",
            "当前会话：",
            _clip(thread.combined_text(), 1200),
            "",
            "仓库证据：",
            _clip(evidence.combined_text(), 800),
            "",
            "默认草稿，可在不丢信息的前提下改写：",
            json.dumps(
                {
                    "title": fallback.title,
                    "content": fallback.content,
                    "background": fallback.background,
                    "tags": fallback.tags,
                    "why_record": fallback.why_record,
                    "references": fallback.references,
                },
                ensure_ascii=False,
            ),
        ]
    )


def _extract_json_object(raw: str) -> dict[str, Any]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("LLM draft must be a JSON object")
    return parsed


def _coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _parse_llm_draft(raw: str, fallback: RecordDraft) -> RecordDraft:
    parsed = _extract_json_object(raw)
    title = _coerce_text(parsed.get("title"))
    content = _coerce_text(parsed.get("content"))
    tags = _coerce_text(parsed.get("tags"))
    why_record = _coerce_text(parsed.get("why_record"))
    if not title or not content or not tags or not why_record:
        raise ValueError("LLM draft missing required fields")
    return RecordDraft(
        record_type=fallback.record_type,
        title=title,
        content=content,
        background=_coerce_text(parsed.get("background")),
        tags=tags,
        why_record=why_record,
        references=_coerce_text(parsed.get("references")) or fallback.references,
        agent_type=fallback.agent_type,
        suggestion_reason=f"{fallback.suggestion_reason} 已使用可选 LLM 起草层润色。",
        confidence=min(0.95, fallback.confidence + 0.04),
    )


def _run_optional_llm(
    prompt: str,
    *,
    env: Mapping[str, str],
    runner: Any,
) -> str | None:
    command = env.get("KNOWLEDGE_RECORD_LLM_CMD", "").strip()
    if not command:
        return None
    try:
        result = runner(
            shlex.split(command),
            input=prompt,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    stdout = getattr(result, "stdout", "")
    return stdout.strip() or None


def suggest_record(
    thread: ThreadPacket,
    evidence: EvidencePacket,
    *,
    agent_type: str,
    env: Mapping[str, str] | None = None,
    runner: Any = subprocess.run,
) -> RecordDraft:
    fallback = _deterministic_draft(thread, evidence, agent_type=agent_type)
    llm_output = _run_optional_llm(
        build_draft_prompt(thread, evidence, fallback=fallback),
        env=env or os.environ,
        runner=runner,
    )
    if not llm_output:
        return fallback
    try:
        return _parse_llm_draft(llm_output, fallback)
    except (json.JSONDecodeError, ValueError, TypeError):
        return fallback
