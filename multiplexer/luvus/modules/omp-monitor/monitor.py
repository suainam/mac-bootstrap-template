#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from pathlib import Path
import yaml

CONFIG_PATH = Path.home() / ".omp" / "agent" / "config.yml"


def get_active_model() -> str:
    if not CONFIG_PATH.exists():
        return "omp: ready"
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            model_roles = data.get("modelRoles", {})
            default_role = model_roles.get("default", "gemini-3.7-flash")
            bare_model = default_role.split("/")[-1].split(":")[0]
            return f"󰚩 {bare_model}"
    except Exception:
        return "󰚩 omp"


def push_bar() -> None:
    text = get_active_model()
    # Call luvus bar push
    try:
        subprocess.run(
            [
                "luvus",
                "bar",
                "push",
                "--id",
                "omp_status",
                "--region",
                "top-right",
                "--text",
                text,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        pass


def main() -> None:
    push_bar()


if __name__ == "__main__":
    main()
