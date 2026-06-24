"""Tests for the prompt-library MCP stdio server implementation."""

import importlib.util
import json
import os
import sys
from pathlib import Path

from helpers import TEMPLATE


def load_module(name: str, rel_path: str):
    path = Path(TEMPLATE) / rel_path
    sys.path.insert(0, str(Path(TEMPLATE) / "scripts"))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


prompt_mcp = load_module("agent_prompt_mcp", "scripts/agent-prompt-mcp.py")


def write_prompt_fixture(tmp_path):
    upstream = tmp_path / "upstream"
    prompt_root = tmp_path / "prompts"
    index_file = prompt_root / "index.json"

    pattern = upstream / "fabric" / "data" / "patterns" / "extract_wisdom"
    pattern.mkdir(parents=True)
    (pattern / "system.md").write_text("Extract wisdom from notes.\n", encoding="utf-8")

    index_file.parent.mkdir(parents=True)
    index_file.write_text(
        json.dumps(
            {
                "version": 1,
                "upstream_root": str(upstream),
                "prompt_root": str(prompt_root),
                "sources": {
                    "fabric": {
                        "repo": "https://example.invalid/fabric.git",
                        "upstream_dir": "fabric",
                        "mode": "fabric-patterns",
                        "patterns_path": "data/patterns",
                        "license": "MIT",
                    }
                },
                "prompts": [
                    {
                        "id": "fabric:extract_wisdom",
                        "source": "fabric",
                        "title": "extract_wisdom",
                        "format": "fabric-pattern",
                        "entrypoint": "data/patterns/extract_wisdom",
                        "files": [{"role": "system", "path": "data/patterns/extract_wisdom/system.md"}],
                        "license": "MIT",
                        "repo": "https://example.invalid/fabric.git",
                        "preview": "Extract wisdom from notes.",
                    }
                ],
                "issues": [],
            }
        ),
        encoding="utf-8",
    )
    return index_file


def request(server, method, params=None, request_id=1):
    response = server.handle({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
    assert response is not None
    assert "error" not in response
    return response["result"]


def test_mcp_initialize_declares_prompts_capability(tmp_path):
    index = write_prompt_fixture(tmp_path)
    server = prompt_mcp.PromptMcpServer(index_file=index)

    result = request(server, "initialize", {"protocolVersion": "2025-11-25"})

    assert result["protocolVersion"] == "2025-11-25"
    assert "prompts" in result["capabilities"]
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == "agent-prompt-library"


def test_mcp_initialize_keeps_older_supported_protocol(tmp_path):
    index = write_prompt_fixture(tmp_path)
    server = prompt_mcp.PromptMcpServer(index_file=index)

    result = request(server, "initialize", {"protocolVersion": "2025-06-18"})

    assert result["protocolVersion"] == "2025-06-18"


def test_mcp_initialize_falls_back_to_latest_protocol(tmp_path):
    index = write_prompt_fixture(tmp_path)
    server = prompt_mcp.PromptMcpServer(index_file=index)

    result = request(server, "initialize", {"protocolVersion": "2024-11-05"})

    assert result["protocolVersion"] == "2025-11-25"


def test_mcp_prompts_list_and_get_return_prompt_messages(tmp_path):
    index = write_prompt_fixture(tmp_path)
    server = prompt_mcp.PromptMcpServer(index_file=index)

    listed = request(server, "prompts/list")
    assert listed["prompts"][0]["name"] == "fabric:extract_wisdom"

    fetched = request(
        server,
        "prompts/get",
        {"name": "fabric:extract_wisdom", "arguments": {"input": "meeting notes"}},
    )
    assert fetched["messages"][0]["role"] == "user"
    assert fetched["messages"][0]["content"]["type"] == "text"
    assert "Extract wisdom from notes" in fetched["messages"][0]["content"]["text"]
    assert "meeting notes" in fetched["messages"][0]["content"]["text"]


def test_mcp_search_prompts_tool(tmp_path):
    index = write_prompt_fixture(tmp_path)
    server = prompt_mcp.PromptMcpServer(index_file=index)

    tools = request(server, "tools/list")
    assert [tool["name"] for tool in tools["tools"]] == ["search_prompts"]

    called = request(
        server,
        "tools/call",
        {"name": "search_prompts", "arguments": {"query": "wisdom", "limit": 5}},
    )
    payload = json.loads(called["content"][0]["text"])
    assert payload[0]["id"] == "fabric:extract_wisdom"
    assert called["isError"] is False


def test_mcp_unknown_method_uses_json_rpc_method_not_found(tmp_path):
    index = write_prompt_fixture(tmp_path)
    server = prompt_mcp.PromptMcpServer(index_file=index)

    response = server.handle({"jsonrpc": "2.0", "id": 7, "method": "unknown/method", "params": {}})

    assert response["error"]["code"] == -32601


def test_manifest_documents_prompt_mcp_server():
    manifest = json.loads(open(os.path.join(TEMPLATE, "agent", "agent-manifest.json")).read())
    server = manifest["mcp_servers"]["agent-prompt-library"]
    assert server["command"] == "agent-prompt-mcp"
    assert "prompts/list" in server["capabilities"]
    assert "prompts/get" in server["capabilities"]
