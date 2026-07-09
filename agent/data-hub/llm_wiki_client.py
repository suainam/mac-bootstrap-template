from __future__ import annotations

import json
import os
from typing import Any
from urllib import parse, request


class LlmWikiClient:
    def __init__(self, api_base: str, project_id: str, token_env: str, token: str = ""):
        self.api_base = api_base.rstrip("/")
        self.project_id = project_id
        self.token_env = token_env
        self.token = token

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        token = os.environ.get(self.token_env, self.token)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(f"{self.api_base}{path}", data=body, headers=headers, method=method)
        with request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8")
        return json.loads(text or "{}")

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/health")

    def list_projects(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/projects").get("projects", [])

    def search(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        return self._request(
            "POST",
            f"/api/v1/projects/{self.project_id}/search",
            {"query": query, "limit": limit},
        ).get("results", [])

    def read_file(self, path: str) -> str:
        quoted = parse.quote(path, safe="/")
        data = self._request("GET", f"/api/v1/projects/{self.project_id}/files/content?path={quoted}")
        return str(data.get("content", ""))

    def graph(self, path: str | None = None) -> dict[str, Any]:
        suffix = ""
        if path:
            suffix = f"?path={parse.quote(path, safe='/')}"
        return self._request("GET", f"/api/v1/projects/{self.project_id}/graph{suffix}")

    def reviews(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            f"/api/v1/projects/{self.project_id}/reviews?status=unresolved&limit={limit}",
        ).get("reviews", [])
