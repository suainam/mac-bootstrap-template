"""MCP stdio server for the local agent prompt library.

Implements the MCP prompts capability and a small read-only search tool. stdio
output is restricted to newline-delimited JSON-RPC messages.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


def load_prompt_index_module():
    path = Path(__file__).with_name("agent-prompt-index.py")
    spec = importlib.util.spec_from_file_location("agent_prompt_index", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


prompt_index = load_prompt_index_module()


LATEST_PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS = {"2025-06-18", LATEST_PROTOCOL_VERSION}
PAGE_SIZE = 100


def load_index(index_file: Path | None = None) -> dict[str, Any]:
    config = prompt_index.load_sources(prompt_index.DEFAULT_SOURCES)
    return prompt_index.load_index(index_file or prompt_index.index_path(config))


def compact_record(record: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "source",
        "title",
        "format",
        "license",
        "repo",
        "preview",
        "source_file",
        "start_line",
        "end_line",
        "entrypoint",
    )
    return {key: record[key] for key in keys if key in record}


def search_prompts(data: dict[str, Any], query: str = "", limit: int = 20) -> list[dict[str, Any]]:
    prompts = data.get("prompts", [])
    if query:
        prompts = [record for record in prompts if prompt_index.record_matches(record, query)]
    return [compact_record(record) for record in prompts[:limit]]


def get_prompt(data: dict[str, Any], prompt_id: str) -> dict[str, Any]:
    record = prompt_index.find_record(data, prompt_id)
    content = prompt_index.show_record(data, record)
    return {"record": compact_record(record), "content": content}


def prompt_definition(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": record["id"],
        "title": record.get("title", record["id"]),
        "description": record.get("preview") or f"{record.get('source', 'local')} prompt",
        "arguments": [
            {
                "name": "input",
                "description": "Optional user input appended after the stored prompt template.",
                "required": False,
            }
        ],
    }


def list_prompt_definitions(data: dict[str, Any], cursor: str | None = None) -> dict[str, Any]:
    prompts = data.get("prompts", [])
    start = int(cursor or 0)
    end = start + PAGE_SIZE
    result: dict[str, Any] = {
        "prompts": [prompt_definition(record) for record in prompts[start:end]]
    }
    if end < len(prompts):
        result["nextCursor"] = str(end)
    return result


def prompt_messages(data: dict[str, Any], name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = get_prompt(data, name)
    text = payload["content"].rstrip()
    user_input = (arguments or {}).get("input")
    if user_input:
        text = f"{text}\n\n# User Input\n\n{user_input}"
    record = payload["record"]
    return {
        "description": record.get("preview") or record.get("title") or name,
        "messages": [
            {
                "role": "user",
                "content": {"type": "text", "text": text},
            }
        ],
    }


def list_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "search_prompts",
            "title": "Search Prompts",
            "description": "Search the local agent prompt-library index by id, title, source, format, or preview.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "default": ""},
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                },
            },
        },
    ]


def text_content(payload: Any) -> list[dict[str, str]]:
    return [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}]


class PromptMcpServer:
    def __init__(self, index_file: Path | None = None) -> None:
        self.index_file = index_file

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method")
        request_id = request.get("id")

        try:
            result = self.dispatch(method, request.get("params") or {})
            if request_id is None:
                return None
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except NotImplementedError as exc:
            if request_id is None:
                return None
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": str(exc)},
            }
        except KeyError as exc:
            if request_id is None:
                return None
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": f"Missing parameter: {exc.args[0]}"},
            }
        except ValueError as exc:
            if request_id is None:
                return None
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": str(exc)},
            }
        except Exception as exc:  # MCP clients expect JSON-RPC errors, not stderr tracebacks.
            if request_id is None:
                return None
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": str(exc)},
            }

    def dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            requested = params.get("protocolVersion")
            protocol_version = (
                requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
            )
            return {
                "protocolVersion": protocol_version,
                "capabilities": {
                    "prompts": {"listChanged": False},
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": "agent-prompt-library",
                    "title": "Agent Prompt Library",
                    "version": "0.1.0",
                },
                "instructions": "Use prompts/list and prompts/get to select stored prompt templates. Use search_prompts only to discover candidate prompt names.",
            }
        if method == "prompts/list":
            data = load_index(self.index_file)
            return list_prompt_definitions(data, params.get("cursor"))
        if method == "prompts/get":
            data = load_index(self.index_file)
            return prompt_messages(data, str(params["name"]), params.get("arguments") or {})
        if method == "tools/list":
            return {"tools": list_tools()}
        if method == "tools/call":
            return self.call_tool(params)
        if method in {"notifications/initialized", "$/cancelRequest"}:
            return {}
        raise NotImplementedError(f"Method not found: {method}")

    def call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        args = params.get("arguments") or {}
        data = load_index(self.index_file)

        if name == "search_prompts":
            payload = search_prompts(data, str(args.get("query", "")), int(args.get("limit", 20)))
        else:
            raise ValueError(f"Unknown tool: {name}")

        return {"content": text_content(payload), "isError": False}

    def serve(self) -> int:
        for line in sys.stdin:
            if not line.strip():
                continue
            response = self.handle(json.loads(line))
            if response is not None:
                print(json.dumps(response, ensure_ascii=False), flush=True)
        return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--index", type=Path, default=None)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return PromptMcpServer(index_file=args.index).serve()


if __name__ == "__main__":
    raise SystemExit(main())
