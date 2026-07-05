from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch, MagicMock

import pytest

import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR.parent / "agent" / "data-hub"))

from llm_filter import (
    FilterResult,
    load_backends,
    deduplicate,
    _parse_llm_response,
    _call_llm,
    score_one,
    filter_candidates_batch,
)


def test_deduplicate_empty_list():
    assert deduplicate([]) == []


def test_deduplicate_single_item():
    c = {"content": "hello", "title": "hello"}
    assert deduplicate([c]) == [c]


def test_deduplicate_removes_exact_content_duplicates():
    c1 = {"content": "hello", "title": "title1"}
    c2 = {"content": "hello", "title": "title2"}
    assert deduplicate([c1, c2]) == [c1]


def test_deduplicate_removes_similar_title_duplicates():
    c1 = {"content": "hello", "title": "this is a very long title about a topic"}
    c2 = {"content": "world", "title": "this is a very long title about a topic (edited)"}
    res = deduplicate([c1, c2])
    assert len(res) == 1
    assert res[0] == c1


def test_deduplicate_keeps_distinct_candidates():
    c1 = {"content": "hello", "title": "first topic for testing"}
    c2 = {"content": "world", "title": "second topic completely different"}
    assert deduplicate([c1, c2]) == [c1, c2]


def test_load_backends_missing_file_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = load_backends()
    assert "backends" in cfg
    assert cfg["cli_fallbacks"] == ["codex", "agy", "opencode", "claude"]


def test_load_backends_strips_comment_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    p = tmp_path / "work/config/mac-bootstrap/private/agent"
    p.mkdir(parents=True)
    f = p / "llm_backends.jsonc"
    f.write_text('{\n// comment\n"backends": []\n}')
    cfg = load_backends()
    assert cfg["backends"] == []


def test_load_backends_valid_jsonc(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    p = tmp_path / "work/config/mac-bootstrap/private/agent"
    p.mkdir(parents=True)
    f = p / "llm_backends.jsonc"
    f.write_text('{"backends": [{"name": "test"}], "cli_fallbacks": ["cli1"]}')
    cfg = load_backends()
    assert cfg["backends"][0]["name"] == "test"
    assert cfg["cli_fallbacks"] == ["cli1"]


def test_parse_llm_response_valid_json_keep_true():
    raw = '{"keep": true, "type_correct": "card", "title_summary": "test", "confidence": 0.8, "reason": "ok"}'
    res = _parse_llm_response(raw)
    assert res.keep is True
    assert res.type_correct == "card"
    assert res.title_summary == "test"
    assert res.confidence == 0.8


def test_parse_llm_response_valid_json_keep_false():
    raw = '{"keep": false}'
    res = _parse_llm_response(raw)
    assert res.keep is False


def test_parse_llm_response_invalid_json_defaults_to_keep():
    raw = 'not json'
    res = _parse_llm_response(raw, default_keep=True)
    assert res.keep is True
    assert res.reason == "parse_error"


def test_parse_llm_response_missing_fields_uses_defaults():
    raw = '{"keep": true}'
    res = _parse_llm_response(raw)
    assert res.title_summary == ""
    assert res.confidence == 0.5


@patch("openai.OpenAI")
def test_call_llm_first_backend_succeeds(mock_openai):
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    mock_client.chat.completions.create.return_value.choices[0].message.content = "result"
    
    cfg = {"backends": [{"base_url": "url", "model": "model"}], "cli_fallbacks": []}
    assert _call_llm("prompt", cfg) == "result"


@patch("subprocess.run")
@patch("openai.OpenAI")
def test_call_llm_all_backends_fail_tries_cli(mock_openai, mock_run):
    mock_openai.side_effect = Exception("fail")
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "cli_result"
    mock_run.return_value = mock_res
    
    cfg = {"backends": [{"base_url": "url", "model": "model"}], "cli_fallbacks": ["cli1"]}
    assert _call_llm("prompt", cfg) == "cli_result"


@patch("llm_filter._call_llm")
def test_score_one_chat_keep_true(mock_call):
    mock_call.return_value = '{"keep": true, "confidence": 0.9}'
    cfg = {"filter": {"chat_threshold": 0.5}}
    res = score_one({"content": "hi", "context_str": ""}, "chat_response", cfg)
    assert res.keep is True


@patch("llm_filter._call_llm")
def test_score_one_below_threshold_dropped(mock_call):
    mock_call.return_value = '{"keep": true, "confidence": 0.3}'
    cfg = {"filter": {"chat_threshold": 0.5}}
    res = score_one({"content": "hi", "context_str": ""}, "chat_response", cfg)
    assert res.keep is False
    assert "dropped" in res.reason


@patch("llm_filter._call_llm")
def test_score_one_llm_failure_keeps_candidate(mock_call):
    mock_call.return_value = ''
    cfg = {"filter": {"chat_threshold": 0.5}}
    res = score_one({"content": "hi", "context_str": ""}, "chat_response", cfg)
    assert res.keep is True  # fail-open
    assert res.reason == "empty_response"


@patch("llm_filter.score_one")
def test_filter_candidates_batch_all_kept(mock_score):
    mock_score.return_value = FilterResult(keep=True, type_correct="", title_summary="", confidence=0.8, reason="")
    c = {"content": "hi", "title": "hi"}
    res = filter_candidates_batch([c], "chat", cfg={"filter": {"max_workers": 1}})
    assert len(res) == 1
    assert res[0][0] == c


@patch("llm_filter.score_one")
def test_filter_candidates_batch_some_dropped(mock_score):
    def side_effect(c, *args):
        if c["content"] == "drop":
            return FilterResult(keep=False, type_correct="", title_summary="", confidence=0, reason="")
        return FilterResult(keep=True, type_correct="", title_summary="", confidence=1, reason="")
    mock_score.side_effect = side_effect
    
    c1 = {"content": "keep", "title": "1"}
    c2 = {"content": "drop", "title": "2"}
    res = filter_candidates_batch([c1, c2], "chat", cfg={"filter": {"max_workers": 1}})
    assert len(res) == 1
    assert res[0][0] == c1
