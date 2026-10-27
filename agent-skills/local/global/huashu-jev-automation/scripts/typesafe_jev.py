#!/usr/bin/env python3
"""TypeSafe Jev client with primary/fallback API keys (mirrors OMP judge routing).

Reads tokens from the OMP env file (default ~/.omp/agent/.env) like the OMP
catalog does:

    primary   TYPESAFE_JEV_TOKEN   (== TYPESAFE_API_KEY)
    fallback  TYPESAFE_JEV_TOKEN1

Order: try primary, on any failure (HTTP/network/parse) try fallback. The label
of the key that answered is returned so callers can log it. Optional third-hop
OpenRouter fallback mirrors OMP's chain (trial-1 -> trial-2 -> openrouter).

Usage (Python):
    from typesafe_jev import send_jev
    resp, key_label = send_jev(
        questions={"ok": {"type": "noul", "instructions": "…"}},
        state="…",
        model="jev-latest",
        images=None,            # {"shot": ("shot.png", <bytes>, "image/png")}
        openrouter_fallback=False,
    )

Facts (docs.typesafe.ai, verified 2026-10-27):
  - Images/Box need header "TypeSafe-Danger-Zone-Images: true".
  - Image format PNG/JPEG only; longest side <=1568, shortest >=280.
  - Images bill as input tokens ($0.042/Mtok), output free.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Optional

import urllib.error
import urllib.request

DEFAULT_ENV = Path(os.environ.get("OMP_AGENT_ENV", "~/.omp/agent/.env")).expanduser()
ZONE_HEADER = "TypeSafe-Danger-Zone-Images"
BASE = "https://api.typesafe.ai"
OPENROUTER_BASE = "https://openrouter.ai/api/alpha"
OPENROUTER_PATH = "/decisions"


def _env_value(env_path: Path, name: str) -> Optional[str]:
    """Read one key from an .env-style file; never logs the value."""
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == name:
            return v.strip()
    return None


def _key_pairs(env_path: Path) -> list[tuple[str, str]]:
    """(key, label) pairs: primary then fallback, deduped."""
    primary = _env_value(env_path, "TYPESAFE_JEV_TOKEN") or _env_value(
        env_path, "TYPESAFE_API_KEY"
    )
    fallback = _env_value(env_path, "TYPESAFE_JEV_TOKEN1")
    pairs: list[tuple[str, str]] = []
    for key, label in ((primary, "primary"), (fallback, "fallback")):
        if key and key not in [p[0] for p in pairs]:
            pairs.append((key, label))
    return pairs


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _multipart(body: dict, images: dict) -> tuple[bytes, str]:
    """Build multipart/form-data: first part 'request'=JSON, then image parts."""
    boundary = "----tsj" + uuid.uuid4().hex
    chunks: list[bytes] = []
    chunks.append(
        (
            f'--{boundary}\r\n'
            'Content-Disposition: form-data; name="request"\r\n'
            'Content-Type: application/json\r\n\r\n'
            f'{json.dumps(body)}\r\n'
        ).encode("utf-8")
    )
    for ref, (_fname, blob, mime) in images.items():
        chunks.append(
            (
                f'--{boundary}\r\n'
                'Content-Disposition: form-data; name='
                f'"{ref}"; filename="{_fname or ref}"\r\n'
                f'Content-Type: {mime}\r\n\r\n'
            ).encode("utf-8")
        )
        chunks.append(blob)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), boundary


def _post(url: str, key: str, body: dict, images: Optional[dict]) -> tuple[int, str]:
    headers = {"Authorization": f"Bearer {key}"}
    if images:
        headers[ZONE_HEADER] = "true"
        data, boundary = _multipart(body, images)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    else:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=120) as resp:
            return 200, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def send_jev(
    questions: dict[str, Any],
    state: Any = None,
    model: str = "jev-latest",
    images: Optional[dict[str, tuple]] = None,
    openrouter_fallback: bool = False,
    env_path: Path = DEFAULT_ENV,
    openrouter_key_env: str = "OPENROUTER_API_KEY",
) -> tuple[dict, str]:
    """Send a System One request, walking primary -> fallback keys.

    Returns (response_json, key_label): key_label is "primary", "fallback",
    or "openrouter". Raises RuntimeError if all keys fail.
    """
    pairs = _key_pairs(env_path)
    if not pairs:
        raise RuntimeError("no TYPESAFE_JEV_TOKEN/TYPESAFE_JEV_TOKEN1 in env")
    body: dict[str, Any] = {"model": model, "questions": questions}
    if state is not None:
        body["state"] = state

    last_err: Optional[Exception] = None
    for key, label in pairs:
        try:
            code, text = _post(f"{BASE}/v1/systemone", key, body, images)
            if code == 200:
                return json.loads(text), label
            last_err = RuntimeError(f"HTTP {code}: {text[:200]}")
        except Exception as exc:  # noqa: BLE001 - retry next key
            last_err = exc

    if openrouter_fallback:
        or_key = _env_value(env_path, openrouter_key_env)
        if or_key:
            try:
                code, text = _post(f"{OPENROUTER_BASE}{OPENROUTER_PATH}", or_key, body, images)
                if code == 200:
                    return json.loads(text), "openrouter"
                last_err = RuntimeError(f"openrouter HTTP {code}: {text[:200]}")
            except Exception as exc:  # noqa: BLE001
                last_err = exc

    raise RuntimeError(f"all jev keys failed: {last_err}")


if __name__ == "__main__":
    resp, label = send_jev(
        {"ok": {"type": "noul", "instructions": "Is a reachable system one request?"}},
        state="smoke test",
        model="jev-latest",
    )
    print(json.dumps({"key": label, "model": resp.get("model")}, ensure_ascii=False))
