#!/usr/bin/env python3

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import unicodedata
from typing import NoReturn


class InvalidPrivateConfigError(Exception):
    pass


def strip_jsonc(text: str) -> str:
    output: list[str] = []
    in_string = False
    escaped = False
    line_comment = False
    block_comment = False
    index = 0
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
                output.append(char)
            else:
                output.append(" ")
        elif block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                output.extend((" ", " "))
                index += 1
            else:
                output.append("\n" if char == "\n" else " ")
        elif in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            output.append(char)
        elif char == "/" and next_char == "/":
            line_comment = True
            output.extend((" ", " "))
            index += 1
        elif char == "/" and next_char == "*":
            block_comment = True
            output.extend((" ", " "))
            index += 1
        else:
            output.append(char)
        index += 1
    return "".join(output)


def config_path() -> Path:
    private_dir = os.environ.get("MAC_BOOTSTRAP_PRIVATE_DIR")
    if private_dir:
        return Path(private_dir).expanduser() / "agent/context7.runtime.jsonc"
    return Path(__file__).resolve().parents[2] / "private/agent/context7.runtime.jsonc"


def load_private_key(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        path.chmod(0o600)
        data = json.loads(strip_jsonc(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        raise InvalidPrivateConfigError from None
    if not isinstance(data, dict):
        raise InvalidPrivateConfigError
    key = data.get("api_key")
    if key is None:
        return None
    if key == "REPLACE_ME":
        return None
    if (
        not isinstance(key, str)
        or not key
        or any(unicodedata.category(char) == "Cc" for char in key)
    ):
        raise InvalidPrivateConfigError
    return key


def launch(command: str, arguments: list[str], environment: dict[str, str]) -> NoReturn:
    os.execvpe(command, [command, *arguments], environment)
    raise AssertionError("execvpe returned")


def main() -> int:
    try:
        key = load_private_key(config_path())
    except InvalidPrivateConfigError:
        print("Context7 private config invalid", file=sys.stderr)
        return 2

    if sys.argv[1:] == ["--validate-private-config"]:
        return 0

    environment = os.environ.copy()
    environment.pop("CONTEXT7_API_KEY", None)
    if key is not None:
        environment["CONTEXT7_API_KEY"] = key

    installed = shutil.which("context7-mcp")
    if installed:
        launch(installed, sys.argv[1:], environment)
    launch("npx", ["-y", "@upstash/context7-mcp", *sys.argv[1:]], environment)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
