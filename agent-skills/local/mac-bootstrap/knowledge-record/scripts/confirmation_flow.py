#!/usr/bin/env python3
"""Terminal confirmation flow for knowledge-record suggestions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from suggestion_engine import RecordDraft


@dataclass(frozen=True)
class ConfirmationResult:
    status: str
    draft: RecordDraft | None = None
    saved: object | None = None


def _apply_edit(draft: RecordDraft, action: str) -> RecordDraft:
    field, _, value = action.removeprefix("edit ").partition("=")
    field = field.strip()
    value = value.strip()
    if field not in {"title", "tags", "why_record"}:
        raise ValueError(f"unsupported edit field: {field}")
    if not value:
        raise ValueError(f"edit value is required for {field}")
    return draft.with_update(**{field: value})


def confirm_draft(
    draft: RecordDraft,
    *,
    actions: Iterable[str] | None = None,
    save_callback: Callable[[RecordDraft], object] | None = None,
    regenerate_callback: Callable[[], RecordDraft] | None = None,
    input_func: Callable[[str], str] = input,
    output_func: Callable[[str], None] = print,
) -> ConfirmationResult:
    current = draft
    action_iter = iter(actions) if actions is not None else None

    while True:
        output_func(render_draft(current))
        if action_iter is None:
            action = input_func("Action [accept/cancel/regenerate/edit title=.../edit tags=.../edit why_record=...]: ")
        else:
            action = next(action_iter)
        action = action.strip()

        if action == "accept":
            saved = save_callback(current) if save_callback else None
            return ConfirmationResult(status="accepted", draft=current, saved=saved)
        if action == "cancel":
            return ConfirmationResult(status="canceled", draft=current)
        if action == "regenerate":
            if regenerate_callback is None:
                raise ValueError("regenerate requested but no callback was provided")
            current = regenerate_callback()
            continue
        if action.startswith("edit "):
            current = _apply_edit(current, action)
            continue
        raise ValueError(f"unsupported confirmation action: {action}")


def render_draft(draft: RecordDraft) -> str:
    return "\n".join(
        [
            "Suggested knowledge record:",
            f"type: {draft.record_type}",
            f"title: {draft.title}",
            f"tags: {draft.tags}",
            f"confidence: {draft.confidence:.2f}",
            f"reason: {draft.suggestion_reason}",
            f"why_record: {draft.why_record}",
            f"content: {draft.content}",
        ]
    )
