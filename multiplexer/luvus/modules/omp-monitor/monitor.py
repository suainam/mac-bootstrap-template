#!/usr/bin/env python3
import json
import subprocess
from pathlib import Path
import yaml

CONFIG_PATH = Path.home() / ".omp" / "agent" / "config.yml"
SESSIONS_ROOT = Path.home() / ".omp" / "agent" / "sessions"


def _live_model_from_sessions() -> str | None:
    """Read the most recent assistant message's provider/model from latest jsonl."""
    try:
        candidates = list(SESSIONS_ROOT.glob("*/20*.jsonl")) + list(SESSIONS_ROOT.glob("20*.jsonl"))
        if not candidates:
            return None
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        lines = latest.read_text(errors="ignore").splitlines()
        for line in reversed(lines[-80:]):
            if '"provider"' not in line or '"model"' not in line:
                continue
            try:
                d = json.loads(line)
                msg = d.get("message", {})
                provider = msg.get("provider")
                model = msg.get("model")
                if provider and model:
                    name = model
                    if "/" in name:
                        name = name.split("/")[-1]
                    name = name.split(":")[0].replace("-contributor-free", "").replace("-free", "")
                    aliases = {
                        "muse-spark-1.2": "Muse Spark 1.2 Free",
                        "nemotron-3.5-lightning": "Nemotron 3.5 Free",
                        "openrouter": "OpenRouter free",
                        "gemini-3.7-flash": "Gemini 3.7 Flash",
                    }
                    for k, v in aliases.items():
                        if k in name:
                            name = v
                            break
                    # Include provider for disambiguation (user-requested)
                    return f"󰚩 {provider} · {name}"
            except Exception:
                continue
    except Exception:
        pass
    return None


def get_active_model() -> str:
    live = _live_model_from_sessions()
    if live:
        return live
    if not CONFIG_PATH.exists():
        return "󰚩 omp"
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            model_roles = data.get("modelRoles", {})
            default_role = model_roles.get("default", "gemini-3.7-flash")
            # Keep provider prefix for static fallback too
            provider = default_role.split("/")[0] if "/" in default_role else ""
            bare = default_role.split("/")[-1].split(":")[0]
            return f"󰚩 {provider} · {bare}" if provider else f"󰚩 {bare}"
    except Exception:
        return "󰚩 omp"


def push_bar() -> None:
    text = get_active_model()
    try:
        subprocess.run(
            ["luvus", "bar", "push", "--id", "omp_status", "--region", "top-right", "--text", text],
            capture_output=True, text=True, check=False,
        )
    except Exception:
        pass


def main() -> None:
    push_bar()


if __name__ == "__main__":
    main()
