#!/usr/bin/env python3
"""OpenViking MCP stdio bridge via cc15 SSH proxy.

Routes all OpenViking memory & search operations through cc15,
leveraging cc15's stable WireGuard connectivity to the active InstaBox node.
Zero third-party dependencies: Standard Python library only.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
import urllib.parse
from typing import Any

# Logging strictly to stderr for stdio MCP compliance
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("openviking-cc15-bridge")

CC15_OVCLI_CONF = "/opt/dockers/magpie/config/home/.openviking/ovcli.conf"


def run_cc15_python(script: str) -> tuple[int, str, str]:
    import base64
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    full_cmd = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
        "cc15", f"python3 -c 'import base64;exec(base64.b64decode(\"{encoded}\"))'"
    ]
    try:
        proc = subprocess.run(full_cmd, capture_output=True, text=True, timeout=20, check=False)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as e:
        return 500, "", str(e)


def make_cc15_request(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, Any]:
    # Embed the payload as a quoted Python string literal (via repr) so the
    # generated script can safely call .encode("utf-8").
    body_expr = repr(json.dumps(payload)) if payload is not None else "None"
    py_code = f"""
import urllib.request, json
try:
    conf = json.load(open("{CC15_OVCLI_CONF}"))
    url = conf.get("url", "").rstrip("/") + "{path}"
    key = conf.get("api_key", "")
    account = conf.get("account", "default")
    user = conf.get("user", "default")
    headers = {{"X-API-Key": key, "X-OpenViking-Account": account, "X-OpenViking-User": user, "Content-Type": "application/json"}}
    body = {body_expr}.encode("utf-8") if {body_expr} is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method="{method}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(json.dumps({{"status": resp.status, "body": json.loads(resp.read().decode("utf-8"))}}))
except Exception as e:
    print(json.dumps({{"status": 500, "error": str(e)}}))
"""
    code, stdout, stderr = run_cc15_python(py_code)
    if code != 0 or not stdout:
        return 502, f"SSH tunnel error: {stderr or 'connection failed'}"
    try:
        res = json.loads(stdout)
        return res.get("status", 500), res.get("body", res.get("error"))
    except Exception as e:
        return 500, f"Parse error: {e}, output: {stdout}"


# Tool implementations
def tool_search(query: str, top_k: int = 5) -> str:
    status, res = make_cc15_request("POST", "/api/v1/search/find", {"query": query, "top_k": top_k})
    if status != 200 or not isinstance(res, dict):
        return f"🌐 OpenViking 状态：连接异常 ({status})\n\n• 详情: {res}"

    result_data = res.get("result", {})
    memories = result_data.get("memories", [])
    resources = result_data.get("resources", [])
    items = memories if memories else resources

    if not items:
        return f"未找到关于 '{query}' 的相关记忆或资源。"

    lines = [f"### OpenViking 搜索结果 ('{query}'):\n"]
    for i, item in enumerate(items[:top_k], 1):
        uri = item.get("uri", "")
        score = item.get("score", 0.0)
        abstract = item.get("abstract", "") or item.get("overview", "") or "无摘要"
        lines.append(f"{i}. **[{score:.3f}]** `{uri}`\n   > {abstract}\n")

    return "\n".join(lines)


def tool_remember(content: str, category: str = "preferences", name: str | None = None) -> str:
    if category not in ("preferences", "entities", "events"):
        category = "preferences"

    if not name:
        slug = "".join(c if c.isalnum() else "_" for c in content[:20]).strip("_").lower() or "entry"
        name = f"mem_{int(time.time())}_{slug}.md"
    elif not name.endswith(".md"):
        name = f"{name}.md"

    uri = f"viking://user/default/memories/{category}/{name}"
    payload = {
        "uri": uri,
        "content": content,
        "mode": "create",
    }

    status, res = make_cc15_request("POST", "/api/v1/content/write", payload)
    if status == 200:
        return f"✅ 记忆已持久化到 OpenViking:\n- URI: `{uri}`\n- 状态: 已入库，正在执行后台向量索引及摘要生成"
    return f"🌐 OpenViking 状态：连接异常 ({status})\n\n• 记录失败: {res}"


def tool_read(uri: str) -> str:
    status, res = make_cc15_request("GET", f"/api/v1/content/read?uri={urllib.parse.quote(uri)}")
    if status == 200 and isinstance(res, dict):
        data = res.get("result", "")
        content = data.get("content", "") if isinstance(data, dict) else str(data)
        return f"### `{uri}`:\n\n{content}"
    return f"🌐 OpenViking 状态：连接异常 ({status})\n\n• 读取失败: {res}"


def tool_status() -> str:
    py_code = f"""
import urllib.request, json
try:
    conf = json.load(open("{CC15_OVCLI_CONF}"))
    url = conf.get("url", "").rstrip("/") + "/api/v1/system/status"
    key = conf.get("api_key", "")
    req = urllib.request.Request(url, headers={{"X-API-Key": key}})
    with urllib.request.urlopen(req, timeout=5) as resp:
        print(json.dumps({{"status": resp.status, "url": conf.get("url"), "body": json.loads(resp.read().decode())}}))
except Exception as e:
    print(json.dumps({{"status": 500, "error": str(e)}}))
"""
    code, stdout, stderr = run_cc15_python(py_code)
    if code == 0 and stdout:
        try:
            res = json.loads(stdout)
            if res.get("status") == 200:
                return (
                    f"### OpenViking 集群状态 (via cc15):\n"
                    f"- 活跃 Endpoint: `{res.get('url')}`\n"
                    f"- 服务健康状态: **HEALTHY**\n"
                    f"- 详情: {res.get('body')}"
                )
        except Exception:
            pass
    return f"🌐 OpenViking 状态：连接异常 (via cc15 proxy failed: {stderr or stdout})"


TOOLS = [
    {
        "name": "openviking_search",
        "description": "在 OpenViking 知识库与长期记忆中执行语义搜索，检索先前的技术偏好、决策或实体记录。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词或语义提问"},
                "top_k": {"type": "integer", "description": "返回条目上限，默认 5", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "openviking_remember",
        "description": "向 OpenViking 存储一条长期记忆、用户偏好或决策事实，自动入库并触发后台向量索引。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "记忆的完整文本内容"},
                "category": {
                    "type": "string",
                    "enum": ["preferences", "entities", "events"],
                    "description": "记忆分类：preferences(偏好), entities(技术实体/人/项目), events(事件/决策里程碑)",
                    "default": "preferences",
                },
                "name": {"type": "string", "description": "可选的条目文件标识符 (如 db_preference)"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "openviking_read",
        "description": "读取 OpenViking 中指定 URI (viking://...) 的具体文档内容。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "uri": {"type": "string", "description": "OpenViking 资源完整 URI"},
            },
            "required": ["uri"],
        },
    },
    {
        "name": "openviking_status",
        "description": "检查当前 OpenViking 节点连通性、cc15 代理状态以及三节点轮换目标。",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def handle_rpc(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "openviking-cc15-bridge", "version": "2.0.0"},
            },
        }

    if method == "notifications/initialized":
        return None

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    if method == "tools/call":
        params = request.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})

        try:
            if name == "openviking_search":
                res_text = tool_search(args["query"], args.get("top_k", 5))
            elif name == "openviking_remember":
                res_text = tool_remember(args["content"], args.get("category", "preferences"), args.get("name"))
            elif name == "openviking_read":
                res_text = tool_read(args["uri"])
            elif name == "openviking_status":
                res_text = tool_status()
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Tool '{name}' not found"},
                }

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": res_text}],
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error executing {name}: {e}"}],
                    "isError": True,
                },
            }

    if req_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method '{method}' not implemented"},
        }
    return None


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        resp = handle_rpc(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
