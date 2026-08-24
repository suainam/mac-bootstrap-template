#!/usr/bin/env python3
"""Launch the DataWorks MCP server with credentials from the private runtime file.

Mirrors scripts/context7-mcp-bridge.py: read private/agent/dataworks.runtime.jsonc
(mode 0600), inject ALIBABA_CLOUD_ACCESS_KEY_ID / _SECRET and REGION into the child
environment, then exec the npx DataWorks MCP server. No secret is ever echoed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unicodedata

import importlib.util

_BRIDGE_PATH = Path(__file__).resolve().parent / "context7-mcp-bridge.py"
_spec = importlib.util.spec_from_file_location("context7_mcp_bridge", _BRIDGE_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["context7_mcp_bridge"] = _mod
_spec.loader.exec_module(_mod)

from context7_mcp_bridge import InvalidPrivateConfigError, launch, strip_jsonc


def dataworks_config_path() -> Path:
    private_dir = os.environ.get("MAC_BOOTSTRAP_PRIVATE_DIR")
    if private_dir:
        return Path(private_dir).expanduser() / "agent/dataworks.runtime.jsonc"
    return (
        Path(__file__).resolve().parents[2] / "private/agent/dataworks.runtime.jsonc"
    )


def load_private_credentials(path: Path) -> dict[str, str]:
    """Return {access_key_id, access_key_secret, region} or raise."""
    if not path.exists():
        raise InvalidPrivateConfigError(f"missing private config: {path}")
    try:
        path.chmod(0o600)
        data = json.loads(strip_jsonc(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        raise InvalidPrivateConfigError from None
    if not isinstance(data, dict):
        raise InvalidPrivateConfigError

    resolved: dict[str, str] = {}
    for field in ("access_key_id", "access_key_secret", "region"):
        value = data.get(field)
        if (
            not isinstance(value, str)
            or not value
            or any(unicodedata.category(char) == "Cc" for char in value)
        ):
            raise InvalidPrivateConfigError(f"invalid field: {field}")
        resolved[field] = value
    return resolved


def main() -> int:
    try:
        creds = load_private_credentials(dataworks_config_path())
    except InvalidPrivateConfigError:
        print("DataWorks private config invalid", file=sys.stderr)
        return 2

    if sys.argv[1:] == ["--validate-private-config"]:
        return 0

    environment = os.environ.copy()
    environment.pop("ALIBABA_CLOUD_ACCESS_KEY_ID", None)
    environment.pop("ALIBABA_CLOUD_ACCESS_KEY_SECRET", None)
    environment["ALIBABA_CLOUD_ACCESS_KEY_ID"] = creds["access_key_id"]
    environment["ALIBABA_CLOUD_ACCESS_KEY_SECRET"] = creds["access_key_secret"]
    environment["REGION"] = creds["region"]

    # The server fetches its tool catalog over HTTP with node-fetch, which
    # only honors proxy env vars when NODE_USE_ENV_PROXY=1.
    if any(environment.get(v) for v in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")):
        environment.setdefault("NODE_USE_ENV_PROXY", "1")

    # Read-only tool subset (names must exist in the remote POP MCP tool
    # catalog at dataworks.data.aliyun.com/pop-mcp-tools; e.g. GetFile and
    # ListDeployments are NOT in the catalog). Override via DATAWORKS_TOOL_NAMES.
    if "DATAWORKS_TOOL_NAMES" not in environment:
        environment["TOOL_NAMES"] = (
            "ListLineages,GetLineageRelationship,ListLineageRelationships,"
            "ListNodes,ListNodeDependencies,GetNode,"
            "ListUpstreamTasks,ListDownstreamTasks,"
            "ListWorkflowDefinitions,GetWorkflowDefinition"
        )

    launch("npx", ["-y", "alibabacloud-dataworks-mcp-server", *sys.argv[1:]], environment)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
