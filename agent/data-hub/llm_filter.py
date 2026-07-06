from __future__ import annotations

import difflib
import hashlib
import json
import os
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openai

from data_hub_config import get_runtime_config, strip_jsonc_comments


@dataclass
class FilterResult:
    keep: bool
    type_correct: str
    title_summary: str
    confidence: float
    reason: str
    refined_knowledge: str = ""


@dataclass
class BackendRequest:
    prompt: str
    timeout: int = 10


@dataclass
class BackendResponse:
    name: str
    kind: str
    ok: bool
    raw_text: str = ""
    error: str = ""
    elapsed: float = 0.0


def _default_config() -> dict[str, Any]:
    return {
        "backends": [],
        "filter": {"chat_threshold": 0.5, "external_threshold": 0.3, "max_workers": 10},
    }


def _cli_kind(cli_name: str) -> str:
    if cli_name in {"opencode", "codex", "agy", "claude"}:
        return f"{cli_name}_cli"
    return "generic_cli"


def _normalize_backend_config(cfg: dict[str, Any]) -> dict[str, Any]:
    if cfg.get("_normalized"):
        return cfg

    normalized = dict(cfg)
    backends: list[dict[str, Any]] = []
    for backend in normalized.get("backends", []):
        item = dict(backend)
        if "kind" not in item:
            item["kind"] = "openai_api" if "base_url" in item else _cli_kind(str(item.get("name", "")))
        item.setdefault("timeout", 10)
        backends.append(item)

    for cli in normalized.get("cli_fallbacks", []):
        backends.append({"name": cli, "kind": _cli_kind(str(cli)), "timeout": 10})

    normalized["backends"] = backends
    normalized.setdefault("filter", _default_config()["filter"])
    normalized["_normalized"] = True
    return normalized


def load_backends() -> dict[str, Any]:
    """加载 private/agent/data_hub.runtime.jsonc 中的 llm 配置。"""
    default_config = _default_config()
    try:
        cfg = get_runtime_config().llm
        return _normalize_backend_config(cfg) if cfg else default_config
    except Exception as e:
        import sys
        print(f"Error parsing data_hub runtime llm config: {e}", file=sys.stderr)
        return default_config


def deduplicate(candidates: list[dict | sqlite3.Row]) -> list[dict | sqlite3.Row]:
    """使用 content hash 和 title similarity 去重"""
    seen_hashes: set[str] = set()
    seen_titles: list[str] = []
    result = []
    for c in candidates:
        if isinstance(c, sqlite3.Row):
            content = c["content"] or ""
            title = c["title"] or ""
        else:
            content = c.get("content", "")
            title = c.get("title", "")
            
        # 1. Content hash
        h = hashlib.sha1(content.encode("utf-8")).hexdigest()
        if h in seen_hashes:
            continue
        seen_hashes.add(h)

        # 2. Title similarity
        title_prefix = title[:80]
        is_dup = False
        for seen_t in seen_titles:
            if difflib.SequenceMatcher(None, title_prefix, seen_t).ratio() > 0.8:
                is_dup = True
                break
        if is_dup:
            continue
            
        seen_titles.append(title_prefix)
        result.append(c)
    return result


OUTPUT_SCHEMA_INSTRUCTION = """返回 JSON（仅返回 JSON，不要解释）：
{"keep": true, "type_correct": "card", "title_summary": "≤30字摘要", "refined_knowledge": "摘要", "confidence": 0.82, "reason": "一句话说明"}
type_correct 可选值：daily（行动/待办）、adr（架构决策）、card（知识点）"""


def _candidate_value(candidate: dict | sqlite3.Row, key: str, default: str = "") -> str:
    if isinstance(candidate, sqlite3.Row):
        return str(candidate[key] or "") if key in candidate.keys() else default
    return str(candidate.get(key, default) or "")


def _build_chat_prompt_batch(batch: list[dict | sqlite3.Row]) -> str:
    batch_data = []
    for c in batch:
        content = _candidate_value(c, "content")
        background = _candidate_value(c, "context_str", _candidate_value(c, "background_prompt", ""))
        cid = _candidate_value(c, "id", _candidate_value(c, "extracted_item_id", str(id(c))))
        batch_data.append({
            "id": str(cid),
            "background": background[:200],
            "content": content[:800]
        })
    batch_json = json.dumps(batch_data, ensure_ascii=False, indent=2)
    
    from data_hub_config import load_prompt_template
    tmpl = load_prompt_template("chat_review.md")
    if tmpl:
        return tmpl.safe_substitute(batch_json=batch_json)
        
    return f"""# Role: 知识管理专家\n\n输入：\n```json\n{batch_json}\n```\n\n请输出 JSON 数组..."""


def _build_chat_prompt(candidate: dict | sqlite3.Row) -> str:
    return _build_chat_prompt_batch([candidate])


def _build_meeting_prompt(candidate: dict | sqlite3.Row) -> str:
    content = _candidate_value(candidate, "content")
    title = _candidate_value(candidate, "title")
    return f"""以下内容来自会议纪要（{title}）。请判断是否应沉淀为长期知识或待办。

内容：{content[:500]}

判断标准：
- keep=true：会议结论、决策依据、行动项、风险、负责人/时间约束、可复用沟通背景
- keep=false：寒暄、重复议程、无明确含义的片段
- 行动项用 daily，架构/策略决策用 adr，稳定背景知识用 card

要求：在 `refined_knowledge` 中，请直接陈述具体的行动项、决策或知识点，禁止使用“该内容描述了...”这种元评论。

{OUTPUT_SCHEMA_INSTRUCTION}"""


def _build_mind_map_prompt(candidate: dict | sqlite3.Row) -> str:
    content = _candidate_value(candidate, "content")
    title = _candidate_value(candidate, "title")
    return f"""以下内容来自思维导图（{title}）。请判断是否应沉淀为结构化知识。

内容：{content[:500]}

判断标准：
- keep=true：主题层级、分类框架、策略结构、关键问题、可复用分析路径
- keep=false：孤立词、无上下文节点、重复节点
- 后续任务用 daily，策略/结构决策用 adr，知识框架用 card

要求：在 `refined_knowledge` 中，请结合标题和内容，将其展开为一个连贯的知识框架解释，禁止使用“该节点属于...”这种元评论，必须直接陈述框架或知识本身。

{OUTPUT_SCHEMA_INSTRUCTION}"""


def _build_wiki_prompt(candidate: dict | sqlite3.Row) -> str:
    content = _candidate_value(candidate, "content")
    title = _candidate_value(candidate, "title")
    source_type = _candidate_value(candidate, "source_type")
    return f"""以下内容来自 {source_type}（{title}）。请判断是否应沉淀为稳定文档知识。

内容：{content[:500]}

判断标准：
- keep=true：稳定流程、技术约束、配置规则、产品说明、操作规范、可复用背景知识
- keep=false：页眉页脚、目录碎片、版权/导航噪音、缺上下文片段
- 操作待办用 daily，重要方案/约束决策用 adr，说明性知识用 card

要求：在 `refined_knowledge` 中，直接总结或重写这部分技术内容/业务规则，禁止使用元评论，提取出能够独立存在的知识卡片。

{OUTPUT_SCHEMA_INSTRUCTION}"""


def _build_external_prompt(candidate: dict | sqlite3.Row) -> str:
    content = _candidate_value(candidate, "content")
    source_type = _candidate_value(candidate, "source_type")
    title = _candidate_value(candidate, "title")
    return f"""以下是从 {source_type}（{title}）提取的知识条目，请修正类型并生成简短标题。

内容：{content[:500]}

规则：外部材料默认保留（keep=true），除非内容明显无意义或纯噪音。在 `refined_knowledge` 中，直接重写核心知识点，禁止使用“这部分描述了...”之类的套话。
{OUTPUT_SCHEMA_INSTRUCTION}"""


def build_prompt(candidate: dict | sqlite3.Row, source_kind: str) -> str:
    return PromptRegistry().build(candidate, source_kind)


class PromptRegistry:
    def build(self, candidate: dict | sqlite3.Row, source_kind: str) -> str:
        source_type = _candidate_value(candidate, "source_type", source_kind)
        if source_kind == "chat_response" or source_type == "chat_response":
            return _build_chat_prompt(candidate)
        if source_type == "meeting_note":
            return _build_meeting_prompt(candidate)
        if source_type == "mind_map":
            return _build_mind_map_prompt(candidate)
        if source_type in {"wiki_page", "wiki_pdf", "wiki_html", "import_doc"}:
            return _build_wiki_prompt(candidate)
        return _build_external_prompt(candidate)


class LLMBackend:
    kind = "base"

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.name = str(cfg.get("name", self.kind))
        self.timeout = int(cfg.get("timeout", 10))

    def generate(self, request: BackendRequest) -> BackendResponse:
        raise NotImplementedError

    def _response(self, ok: bool, raw_text: str = "", error: str = "", elapsed: float = 0.0) -> BackendResponse:
        return BackendResponse(
            name=self.name,
            kind=self.kind,
            ok=ok,
            raw_text=raw_text,
            error=error,
            elapsed=elapsed,
        )


class OpenAIAPIBackend(LLMBackend):
    kind = "openai_api"

    def __init__(self, cfg: dict[str, Any]):
        super().__init__(cfg)
        self.base_url = cfg["base_url"]
        self.api_key = cfg.get("api_key", "sk-placeholder")
        self.model = cfg["model"]

    def generate(self, request: BackendRequest) -> BackendResponse:
        import sys
        import time
        start_time = time.time()
        try:
            client = openai.OpenAI(base_url=self.base_url, api_key=self.api_key, max_retries=0)
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": request.prompt}],
                response_format={"type": "json_object"},
                timeout=request.timeout,
            )
            elapsed = time.time() - start_time
            print(f"[telemetry] backend={self.name} status=success time={elapsed:.2f}s", file=sys.stderr)
            if isinstance(resp, str):
                return self._response(True, raw_text=resp, elapsed=elapsed)
            return self._response(True, raw_text=resp.choices[0].message.content or "", elapsed=elapsed)
        except openai.OpenAIError as e:
            elapsed = time.time() - start_time
            print(f"[telemetry] backend={self.name} status=error time={elapsed:.2f}s error={e}", file=sys.stderr)
            return self._response(False, error=str(e), elapsed=elapsed)


class CLIBackend(LLMBackend):
    kind = "generic_cli"

    def build_command(self, prompt: str) -> tuple[list[str], str | None]:
        return [self.name, "-p", prompt], None

    def extract_text(self, stdout: str) -> str:
        return _extract_json_payload(stdout)

    def generate(self, request: BackendRequest) -> BackendResponse:
        import sys
        import time

        start_time = time.time()
        cmd, input_data = self.build_command(request.prompt)
        try:
            res = subprocess.run(cmd, input=input_data, capture_output=True, text=True, timeout=request.timeout)
            elapsed = time.time() - start_time
            raw_text = self.extract_text(res.stdout)
            if res.returncode == 0 and raw_text.strip():
                print(f"[telemetry] backend=cli_{self.name} status=success time={elapsed:.2f}s", file=sys.stderr)
                return self._response(True, raw_text=raw_text, elapsed=elapsed)
            print(f"[telemetry] backend=cli_{self.name} status=failed returncode={res.returncode} time={elapsed:.2f}s", file=sys.stderr)
            return self._response(False, error=res.stderr.strip() or f"returncode={res.returncode}", elapsed=elapsed)
        except subprocess.SubprocessError as e:
            elapsed = time.time() - start_time
            print(f"[telemetry] backend=cli_{self.name} status=error time={elapsed:.2f}s error={e}", file=sys.stderr)
            return self._response(False, error=str(e), elapsed=elapsed)
        except OSError as e:
            elapsed = time.time() - start_time
            print(f"[telemetry] backend=cli_{self.name} status=error time={elapsed:.2f}s error=os_error_{e}", file=sys.stderr)
            return self._response(False, error=f"os_error_{e}", elapsed=elapsed)


class OpenCodeCLIBackend(CLIBackend):
    kind = "opencode_cli"

    def build_command(self, prompt: str) -> tuple[list[str], str | None]:
        return ["opencode", "run", prompt], None


class CodexCLIBackend(CLIBackend):
    kind = "codex_cli"

    def build_command(self, prompt: str) -> tuple[list[str], str | None]:
        return ["codex", "exec", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only", prompt], None


class AgyCLIBackend(CLIBackend):
    kind = "agy_cli"

    def build_command(self, prompt: str) -> tuple[list[str], str | None]:
        return ["agy", "--print-timeout", f"{self.timeout}s", "--print", prompt], None


class ClaudeCLIBackend(CLIBackend):
    kind = "claude_cli"

    def build_command(self, prompt: str) -> tuple[list[str], str | None]:
        return ["claude", "--print", "--no-session-persistence", "--output-format", "text", prompt], None


BACKEND_CLASSES: dict[str, type[LLMBackend]] = {
    "openai_api": OpenAIAPIBackend,
    "generic_cli": CLIBackend,
    "opencode_cli": OpenCodeCLIBackend,
    "codex_cli": CodexCLIBackend,
    "agy_cli": AgyCLIBackend,
    "claude_cli": ClaudeCLIBackend,
}


class LLMBackendRegistry:
    def __init__(self, backend_classes: dict[str, type[LLMBackend]] | None = None):
        self.backend_classes = backend_classes or BACKEND_CLASSES

    def build(self, backend_cfg: dict[str, Any]) -> LLMBackend | None:
        import sys
        kind = str(backend_cfg.get("kind", ""))
        backend_class = self.backend_classes.get(kind)
        if backend_class is None:
            print(f"[telemetry] backend={backend_cfg.get('name', '<unknown>')} status=config_error error=unknown_kind_{kind}", file=sys.stderr)
            return None
        return backend_class(backend_cfg)


def _call_llm(prompt: str, cfg: dict[str, Any]) -> str:
    import sys
    backends: list[LLMBackend] = []
    normalized_cfg = _normalize_backend_config(cfg)
    registry = LLMBackendRegistry()
    for backend_cfg in normalized_cfg.get("backends", []):
        backend = registry.build(backend_cfg)
        if backend is not None:
            backends.append(backend)

    for backend in backends:
        try:
            response = backend.generate(BackendRequest(prompt=prompt, timeout=backend.timeout))
            if response.raw_text and _parse_llm_response_strict(response.raw_text) is not None:
                return response.raw_text
            if response.raw_text:
                print(f"[telemetry] backend={backend.name} status=invalid_json_schema", file=sys.stderr)
        except Exception as e:
            print(f"Unexpected error with backend {backend.name}: {e}", file=sys.stderr)
            
    return ""


def call_llm_raw(prompt: str, cfg: dict[str, Any] | None = None) -> str:
    """遍历 backends 返回第一个非空文本（不做 FilterResult schema 校验）。

    供 daily_summary / weekly_summary 等自由文本调用使用。
    失败返回空字符串。
    """
    import sys
    if cfg is None:
        cfg = load_backends()
    normalized_cfg = _normalize_backend_config(cfg)
    registry = LLMBackendRegistry()
    for backend_cfg in normalized_cfg.get("backends", []):
        backend = registry.build(backend_cfg)
        if backend is None:
            continue
        try:
            response = backend.generate(BackendRequest(prompt=prompt, timeout=backend.timeout))
            if response.ok and response.raw_text.strip():
                return response.raw_text.strip()
        except Exception as e:
            print(f"[call_llm_raw] backend={backend.name} error={e}", file=sys.stderr)
    return ""


def _extract_json_payload(raw: str) -> str:
    raw = _strip_ansi(raw)
    if "```json" in raw:
        return raw.split("```json")[1].split("```")[0].strip()
    if "```" in raw:
        return raw.split("```")[1].split("```")[0].strip()
    stripped = raw.strip()
    try:
        json.loads(stripped)
        return stripped
    except json.JSONDecodeError:
        candidate = _extract_last_json_object(stripped)
        return candidate if candidate is not None else stripped


def _strip_ansi(text: str) -> str:
    import re
    return re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", text)


def _extract_last_json_object(text: str) -> str | None:
    decoder = json.JSONDecoder()
    last_obj: str | None = None
    for idx, char in enumerate(text):
        if char != "{":
            continue
        try:
            _, end = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError:
            continue
        last_obj = text[idx:idx + end]
    return last_obj


def _parse_llm_response_strict(raw: str) -> FilterResult | list[FilterResult] | None:
    if not raw.strip():
        return None

    try:
        data = json.loads(_extract_json_payload(raw))
    except json.JSONDecodeError:
        return None

    if isinstance(data, list):
        results = []
        for item in data:
            if not isinstance(item, dict): continue
            try:
                confidence = float(item.get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5
            keep = item.get("keep", True)
            if isinstance(keep, str): keep = keep.lower() == "true"
            results.append(FilterResult(
                keep=bool(keep),
                type_correct=str(item.get("type_correct", "")),
                title_summary=str(item.get("title_summary", "")),
                confidence=confidence,
                reason=str(item.get("reason", "")),
                refined_knowledge=str(item.get("refined_knowledge", ""))
            ))
        return results if results else None

    required_keys = {"keep", "type_correct", "title_summary", "confidence", "reason"}
    if not required_keys.issubset(data):
        return None

    if not isinstance(data["keep"], bool):
        return None
    if data["type_correct"] not in {"daily", "adr", "card", ""}:
        return None
    if not isinstance(data["title_summary"], str):
        return None
    if not isinstance(data["reason"], str):
        return None
    try:
        confidence = float(data["confidence"])
    except (TypeError, ValueError):
        return None
    if not 0 <= confidence <= 1:
        return None

    return FilterResult(
        keep=data["keep"],
        type_correct=data["type_correct"],
        title_summary=data["title_summary"],
        confidence=confidence,
        reason=data["reason"],
    )


def _parse_llm_response(raw: str, default_keep: bool = True) -> FilterResult | list[FilterResult]:
    if not raw.strip():
        return FilterResult(keep=default_keep, type_correct="", title_summary="", confidence=0.5, reason="[LLM Failed] empty_response")
    try:
        data = json.loads(_extract_json_payload(raw))
        if isinstance(data, list):
            results = []
            for item in data:
                if not isinstance(item, dict): continue
                keep_val = item.get("keep", default_keep)
                if isinstance(keep_val, str):
                    keep = keep_val.lower() == "true"
                else:
                    keep = bool(keep_val)
                results.append(FilterResult(
                    keep=keep,
                    type_correct=str(item.get("type_correct", "")),
                    title_summary=str(item.get("title_summary", "")),
                    confidence=float(item.get("confidence", 0.5)),
                    reason=str(item.get("reason", "")),
                    refined_knowledge=str(item.get("refined_knowledge", ""))
                ))
            return results
        
        keep_val = data.get("keep", default_keep)
        if isinstance(keep_val, str):
            keep = keep_val.lower() == "true"
        else:
            keep = bool(keep_val)
        return FilterResult(
            keep=keep,
            type_correct=str(data.get("type_correct", "")),
            title_summary=str(data.get("title_summary", "")),
            confidence=float(data.get("confidence", 0.5)),
            reason=str(data.get("reason", "")),
            refined_knowledge=str(data.get("refined_knowledge", ""))
        )
    except Exception as e:
        return FilterResult(keep=default_keep, type_correct="", title_summary="", confidence=0.5, reason=f"[LLM Failed] parse_error: {str(e)}")


def score_one(candidate: dict | sqlite3.Row, source_kind: str, cfg: dict[str, Any]) -> FilterResult:
    if source_kind == "chat_response":
        default_keep = True # Fail-open
        threshold = cfg.get("filter", {}).get("chat_threshold", 0.5)
    else:
        default_keep = True
        threshold = cfg.get("filter", {}).get("external_threshold", 0.3)
        
    prompt = build_prompt(candidate, source_kind)
    raw_response = _call_llm(prompt, cfg)
    result = _parse_llm_response(raw_response, default_keep=default_keep)
    
    if result.keep and result.confidence < threshold:
        result.keep = False
        result.reason += f" (dropped: confidence {result.confidence} < {threshold})"
        
    return result


def filter_candidates_batch(
    candidates: list[dict | sqlite3.Row], 
    source_kind: str, 
    cfg: dict[str, Any] | None = None
) -> list[tuple[dict | sqlite3.Row, FilterResult]]:
    if not candidates:
        return []
        
    if cfg is None:
        cfg = load_backends()
        
    deduped = deduplicate(candidates)
    
    if source_kind == "chat_response":
        threshold = cfg.get("filter", {}).get("chat_threshold", 0.5)
        # Batching for chat responses
        batch_size = 20
        batches = [deduped[i:i + batch_size] for i in range(0, len(deduped), batch_size)]
        
        results = []
        max_workers = cfg.get("filter", {}).get("max_workers", 2)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_batch = {
                executor.submit(_call_llm, _build_chat_prompt_batch(batch), cfg): batch
                for batch in batches
            }
            for future in as_completed(future_to_batch):
                batch = future_to_batch[future]
                try:
                    raw_response = future.result()
                    parsed = _parse_llm_response(raw_response, default_keep=True)
                    parsed_list = parsed if isinstance(parsed, list) else [parsed]
                    
                    for idx, c in enumerate(batch):
                        res = parsed_list[idx] if idx < len(parsed_list) else FilterResult(keep=True, type_correct="", title_summary="", confidence=0.5, reason="[LLM Failed] missing_in_batch")
                        if res.keep and res.confidence < threshold:
                            res.keep = False
                            res.reason += f" (dropped: confidence {res.confidence} < {threshold})"
                        results.append((c, res))
                except Exception as e:
                    import sys
                    print(f"Error scoring batch: {e}", file=sys.stderr)
                    for c in batch:
                        results.append((c, FilterResult(keep=True, type_correct="", title_summary="", confidence=0.5, reason=f"error: {e}")))
        return results
    else:
        # For non-chat, we keep the concurrent individual scoring but don't drop keep=False items
        max_workers = cfg.get("filter", {}).get("max_workers", 2)
        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_cand = {
                executor.submit(score_one, c, source_kind, cfg): c
                for c in deduped
            }
            for future in as_completed(future_to_cand):
                c = future_to_cand[future]
                try:
                    res = future.result()
                    results.append((c, res))
                except Exception as e:
                    import sys
                    print(f"Error scoring candidate: {e}", file=sys.stderr)
                    # fail-open
                    results.append((c, FilterResult(keep=True, type_correct="", title_summary="", confidence=0.5, reason=f"error: {e}")))
        return results
