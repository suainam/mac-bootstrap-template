from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch, MagicMock

import pytest

import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR.parent / "data-hub"))

import data_hub_config
from llm_filter import (
    FilterResult,
    BackendResponse,
    load_backends,
    build_prompt,
    deduplicate,
    _extract_json_payload,
    _parse_llm_response,
    _parse_llm_response_strict,
    _build_chat_prompt_batch,
    _call_llm,
    call_llm_raw,
    score_one,
    filter_candidates_batch,
)


def configure_runtime_files(monkeypatch, tmp_path, runtime_text: str | None = None, legacy_text: str | None = None):
    private = tmp_path / "private" / "agent"
    private.mkdir(parents=True)
    runtime = private / "data_hub.runtime.jsonc"
    monkeypatch.setattr(data_hub_config, "RUNTIME_CONFIG", runtime)
    if runtime_text is not None:
        runtime.write_text(runtime_text)
    return runtime


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
    configure_runtime_files(monkeypatch, tmp_path)
    cfg = load_backends()
    assert "backends" in cfg
    assert cfg["backends"] == []


def test_load_backends_strips_comment_lines(tmp_path, monkeypatch):
    configure_runtime_files(monkeypatch, tmp_path, runtime_text='{\n// comment\n"llm": {"backends": []}\n}')
    cfg = load_backends()
    assert cfg["backends"] == []


def test_load_backends_valid_jsonc(tmp_path, monkeypatch):
    configure_runtime_files(
        monkeypatch,
        tmp_path,
        runtime_text='{"llm": {"backends": [{"name": "test", "kind": "opencode_cli"}]}}',
    )
    cfg = load_backends()
    assert cfg["backends"][0]["name"] == "test"
    assert cfg["backends"][0]["kind"] == "opencode_cli"


def test_load_backends_runtime_cli_backends_are_ordered(tmp_path, monkeypatch):
    configure_runtime_files(
        monkeypatch,
        tmp_path,
        runtime_text='{"llm": {"backends": [{"name": "api", "kind": "openai_api", "base_url": "url", "model": "model"}, {"name": "opencode", "kind": "opencode_cli"}]}}',
    )
    cfg = load_backends()
    assert [b["name"] for b in cfg["backends"]] == ["api", "opencode"]
    assert [b["kind"] for b in cfg["backends"]] == ["openai_api", "opencode_cli"]


def test_parse_llm_response_invalid_json():
    raw = "I am an AI. keep=true"
    res = _parse_llm_response(raw)
    assert res.keep is True
    assert "parse_error" in res.reason


def test_parse_llm_response_valid_json():
    raw = '{"keep": false, "type_correct": "adr", "title_summary": "Test ADR", "confidence": 0.9, "reason": "Because I say so", "refined_knowledge": "Test Summary"}'
    res = _parse_llm_response(raw)
    assert res.keep is False
    assert res.type_correct == "adr"
    assert res.title_summary == "Test ADR"
    assert res.confidence == 0.9
    assert res.reason == "Because I say so"
    assert res.refined_knowledge == "Test Summary"


def test_parse_llm_response_string_false():
    raw = '{"keep": "false", "type_correct": "daily", "title_summary": "Test Daily", "confidence": 0.8, "reason": "string false", "refined_knowledge": "Summary"}'
    res = _parse_llm_response(raw)
    assert res.keep is False


def test_parse_llm_response_valid_json_keep_false():
    raw = '{"keep": false}'
    res = _parse_llm_response(raw)
    assert res.keep is False


def test_parse_llm_response_invalid_json_defaults_to_keep():
    raw = 'not json'
    res = _parse_llm_response(raw, default_keep=True)
    assert res.keep is True
    assert "parse_error" in res.reason


def test_parse_llm_response_missing_fields_uses_defaults():
    raw = '{"keep": true}'
    res = _parse_llm_response(raw)
    assert res.title_summary == ""
    assert res.confidence == 0.5


def test_parse_llm_response_strict_rejects_missing_fields():
    assert _parse_llm_response_strict('{"keep": true}') is None


def test_prompt_contains_few_shot_examples():
    prompt = _build_chat_prompt_batch([{"id": "1", "content": "hello", "context_str": "world"}])
    assert "keep" in prompt
    assert "type_correct" in prompt


def test_parse_llm_response_strict_accepts_complete_schema():
    raw = '{"keep": true, "type_correct": "card", "title_summary": "test", "confidence": 0.8, "reason": "ok"}'
    res = _parse_llm_response_strict(raw)
    assert res is not None
    assert res.keep is True
    assert res.type_correct == "card"


def test_extract_json_payload_from_noisy_cli_output():
    raw = '\x1b[0m\n> build · model\nlogs\n{"keep": true, "type_correct": "card", "title_summary": "ok", "confidence": 0.8, "reason": "ok"}\n'
    payload = _extract_json_payload(raw)
    assert json.loads(payload)["title_summary"] == "ok"


def test_build_prompt_routes_chat_meeting_mind_map_and_wiki():
    chat = build_prompt({"content": "done", "context_str": "q"}, "chat_response")
    meeting = build_prompt({"content": "action", "title": "m", "source_type": "meeting_note"}, "external")
    mind_map = build_prompt({"content": "topic", "title": "x", "source_type": "mind_map"}, "external")
    wiki = build_prompt({"content": "rule", "title": "w", "source_type": "wiki_pdf"}, "external")
    assert "助手回复" in chat
    assert "会议纪要" in meeting
    assert "思维导图" in mind_map
    assert "稳定文档知识" in wiki


@patch("openai.OpenAI")
def test_call_llm_first_backend_succeeds(mock_openai):
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    raw = '{"keep": true, "type_correct": "card", "title_summary": "test", "confidence": 0.8, "reason": "ok"}'
    mock_client.chat.completions.create.return_value.choices[0].message.content = raw
    
    cfg = {"backends": [{"base_url": "url", "model": "model"}]}
    assert _call_llm("prompt", cfg) == raw


@patch("subprocess.run")
@patch("openai.OpenAI")
def test_call_llm_all_backends_fail_tries_cli(mock_openai, mock_run):
    mock_openai.side_effect = Exception("fail")
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = '{"keep": true, "type_correct": "card", "title_summary": "cli", "confidence": 0.7, "reason": "ok"}'
    mock_run.return_value = mock_res
    
    cfg = {"backends": [{"base_url": "url", "model": "model"}], "cli_fallbacks": ["cli1"]}
    assert _call_llm("prompt", cfg) == mock_res.stdout


@patch("subprocess.run")
@patch("openai.OpenAI")
def test_call_llm_invalid_backend_response_falls_back_to_cli(mock_openai, mock_run):
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    mock_client.chat.completions.create.return_value.choices[0].message.content = "<html>bad gateway</html>"
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = '{"keep": true, "type_correct": "card", "title_summary": "cli", "confidence": 0.7, "reason": "ok"}'
    mock_run.return_value = mock_res

    cfg = {"backends": [{"name": "huang-gpt", "base_url": "url", "model": "model"}], "cli_fallbacks": ["cli1"]}
    assert _call_llm("prompt", cfg) == mock_res.stdout


@patch("subprocess.run")
def test_call_llm_opencode_extracts_json_from_noisy_output(mock_run):
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = '\x1b[0m\n> build · model\n{"keep": true, "type_correct": "card", "title_summary": "cli", "confidence": 0.7, "reason": "ok"}'
    mock_res.stderr = ""
    mock_run.return_value = mock_res

    cfg = {"backends": [{"name": "opencode", "kind": "opencode_cli", "timeout": 10}]}
    assert json.loads(_call_llm("prompt", cfg))["title_summary"] == "cli"


@patch("subprocess.run")
def test_call_llm_agy_empty_stdout_fails_open(mock_run):
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = ""
    mock_res.stderr = ""
    mock_run.return_value = mock_res

    cfg = {"backends": [{"name": "agy", "kind": "agy_cli", "timeout": 10}]}
    assert _call_llm("prompt", cfg) == ""


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
    assert "empty_response" in res.reason


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
    assert len(res) == 2
    by_content = {item["content"]: result.keep for item, result in res}
    assert by_content == {"keep": True, "drop": False}


def make_fake_backend_config() -> dict:
    return {"backends": [{"name": "fake_cli", "kind": "generic_cli", "timeout": 5}], "_normalized": True}


def test_call_llm_raw_returns_first_nonempty(monkeypatch):
    class FakeBackend:
        def __init__(self, _cfg):
            self.name = "fake_cli"
            self.timeout = 5
        def generate(self, request):
            return BackendResponse(name="fake_cli", kind="generic_cli", ok=True, raw_text="hello world")

    monkeypatch.setattr("llm_filter.BACKEND_CLASSES", {"generic_cli": lambda cfg: FakeBackend(cfg)})
    result = call_llm_raw("test prompt", make_fake_backend_config())
    assert result == "hello world"


def test_call_llm_raw_empty_on_all_fail(monkeypatch):
    class FailingBackend:
        def __init__(self, _cfg):
            self.name = "failing"
            self.timeout = 5
        def generate(self, request):
            return BackendResponse(name="failing", kind="generic_cli", ok=False, raw_text="", error="fail")

    monkeypatch.setattr("llm_filter.BACKEND_CLASSES", {"generic_cli": lambda cfg: FailingBackend(cfg)})
    result = call_llm_raw("test", make_fake_backend_config())
    assert result == ""


def test_call_llm_raw_uses_default_cfg_when_none(monkeypatch):
    calls = []
    def mock_load():
        calls.append("called")
        return {"backends": [], "_normalized": True}
    monkeypatch.setattr("llm_filter.load_backends", mock_load)
    result = call_llm_raw("test")
    assert calls == ["called"]
    assert result == ""
