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
from typing import Any, Sequence

import openai


@dataclass
class FilterResult:
    keep: bool
    type_correct: str
    title_summary: str
    confidence: float
    reason: str


def load_backends() -> dict[str, Any]:
    """加载 private/agent/llm_backends.jsonc"""
    path = Path.home() / "work/config/mac-bootstrap/private/agent/llm_backends.jsonc"
    default_config = {
        "backends": [],
        "cli_fallbacks": ["codex", "agy", "opencode", "claude"],
        "filter": {"chat_threshold": 0.5, "external_threshold": 0.3, "max_workers": 10},
    }
    if not path.exists():
        return default_config
    try:
        lines = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped.startswith("//"):
                lines.append(line)
        cfg = json.loads("\n".join(lines))
        return cfg
    except Exception as e:
        import sys
        print(f"Error parsing llm_backends.jsonc: {e}", file=sys.stderr)
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


def _build_chat_prompt(candidate: dict | sqlite3.Row) -> str:
    content = candidate["content"] if isinstance(candidate, sqlite3.Row) else candidate.get("content", "")
    background = candidate["context_str"] if isinstance(candidate, sqlite3.Row) else candidate.get("context_str", "")
    return f"""你是知识管理助手。判断以下 AI 助手回复是否包含值得长期沉淀的知识。

背景问题：{background[:200]}
助手回复：{content[:500]}

判断标准：
- keep=true：通用原则、架构决策、踩坑经验、可复用方案建议
- keep=false：工作状态汇报（"先切分支"/"测试已补"/"下一步我来"）、单次任务操作步骤、对话过程确认、重复状态报告

返回 JSON（仅返回 JSON，不要解释）：
{{"keep": true, "type_correct": "daily", "title_summary": "≤30字摘要", "confidence": 0.82, "reason": "一句话说明"}}
type_correct 可选值：daily（行动/待办）、adr（架构决策）、card（知识点）"""


def _build_external_prompt(candidate: dict | sqlite3.Row) -> str:
    content = candidate["content"] if isinstance(candidate, sqlite3.Row) else candidate.get("content", "")
    source_type = candidate["source_type"] if isinstance(candidate, sqlite3.Row) else candidate.get("source_type", "")
    title = candidate["title"] if isinstance(candidate, sqlite3.Row) else candidate.get("title", "")
    return f"""以下是从 {source_type}（{title}）提取的知识条目，请修正类型并生成简短标题。

内容：{content[:300]}

规则：外部材料默认保留（keep=true），除非内容明显无意义或纯噪音。
返回 JSON（仅返回 JSON）：
{{"keep": true, "type_correct": "card", "title_summary": "≤30字摘要", "confidence": 0.75, "reason": ""}}
type_correct 可选值：daily（行动/待办）、adr（架构决策）、card（知识点）"""


def _call_llm(prompt: str, cfg: dict[str, Any]) -> str:
    import sys
    # Try API backends
    for backend in cfg.get("backends", []):
        try:
            client = openai.OpenAI(
                base_url=backend["base_url"],
                api_key=backend.get("api_key", "sk-placeholder"),
            )
            resp = client.chat.completions.create(
                model=backend["model"],
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                timeout=backend.get("timeout", 30),
            )
            return resp.choices[0].message.content or ""
        except openai.OpenAIError as e:
            print(f"OpenAI error with backend {backend.get('name')}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"Unexpected error with backend {backend.get('name')}: {e}", file=sys.stderr)
            
    # Try CLI fallbacks
    for cli in cfg.get("cli_fallbacks", ["codex", "agy", "opencode", "claude"]):
        try:
            if cli == "codex":
                cmd = ["codex", "exec", prompt]
            elif cli == "opencode":
                cmd = ["opencode", "run", prompt]
            elif cli == "agy":
                cmd = ["agy", "-p", prompt]
            elif cli == "claude":
                cmd = ["claude", "-p", prompt]
            else:
                cmd = [cli, "-p", prompt]
                
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except subprocess.SubprocessError as e:
            print(f"Subprocess error with cli {cli}: {e}", file=sys.stderr)
        except OSError as e:
            # Command not found, etc.
            pass
        except Exception as e:
            print(f"Unexpected error with cli {cli}: {e}", file=sys.stderr)
            
    return ""


def _parse_llm_response(raw: str, default_keep: bool = True) -> FilterResult:
    if not raw.strip():
        return FilterResult(keep=default_keep, type_correct="", title_summary="", confidence=0.5, reason="empty_response")
    try:
        # Sometimes LLMs wrap json in markdown
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0]
            
        data = json.loads(raw)
        return FilterResult(
            keep=bool(data.get("keep", default_keep)),
            type_correct=str(data.get("type_correct", "")),
            title_summary=str(data.get("title_summary", "")),
            confidence=float(data.get("confidence", 0.5)),
            reason=str(data.get("reason", "")),
        )
    except json.JSONDecodeError:
        return FilterResult(keep=default_keep, type_correct="", title_summary="", confidence=0.5, reason="parse_error")
    except Exception:
        return FilterResult(keep=default_keep, type_correct="", title_summary="", confidence=0.5, reason="unexpected_error")


def score_one(candidate: dict | sqlite3.Row, source_kind: str, cfg: dict[str, Any]) -> FilterResult:
    if source_kind == "chat_response":
        prompt = _build_chat_prompt(candidate)
        default_keep = True # Fail-open
        threshold = cfg.get("filter", {}).get("chat_threshold", 0.5)
    else:
        prompt = _build_external_prompt(candidate)
        default_keep = True
        threshold = cfg.get("filter", {}).get("external_threshold", 0.3)
        
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
    max_workers = cfg.get("filter", {}).get("max_workers", 10)
    
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
                if res.keep:
                    results.append((c, res))
            except Exception as e:
                import sys
                print(f"Error scoring candidate: {e}", file=sys.stderr)
                # fail-open
                results.append((c, FilterResult(keep=True, type_correct="", title_summary="", confidence=0.5, reason=f"error: {e}")))
                
    # keep order of original candidates if possible, or just return results
    # thread pool output is unordered. Let's return as is.
    return results
