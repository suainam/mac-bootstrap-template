#!/usr/bin/env python3
"""Run the parent Make adapter for the nine lifecycle stages.

The runner deliberately refuses to invent a target or a baseline. The caller
must provide a machine-readable ``before`` artifact, and every stage reselects
the host through ``make switch_remote.<host>`` before checking and executing
the adapter target.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


STAGES = (
    ("preflight", "preflight"),
    ("check", "check"),
    ("deploy", "deploy"),
    ("verify", "verify"),
    ("idempotence", "check"),
    ("rollback", "rollback"),
    ("rollback_verify", "rollback_verify"),
    ("redeploy", "redeploy"),
    ("recovery_verify", "recovery_verify"),
)
NO_CHANGE_STAGES = {"preflight", "check", "verify", "idempotence", "rollback_verify", "recovery_verify"}
RECAP_RE = re.compile(r"^\S+\s+:\s+ok=\d+.*$")
LIMIT_RE = re.compile(r'--limit(?:\s+|=)(?:"(?P<quoted>[^"]+)"|(?P<plain>\S+))')


class LifecycleError(RuntimeError):
    """Raised when a lifecycle safety or evidence gate fails."""


def role_target(role: str, stage: str) -> str:
    """Map a collection role ID to the parent Make target."""

    parts = role.split(".")
    if len(parts) < 2 or not parts[-1] or not parts[-2]:
        raise LifecycleError(f"role must include a scope and name: {role}")
    scope, name = parts[-2], parts[-1]
    return f"{stage}-{scope}.{name}"


def run(command: list[str], repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def redacted_tail(output: str, lines: int = 20) -> str:
    """Return useful failure context without echoing common secret formats."""

    tail = "\n".join(output.splitlines()[-lines:])
    tail = re.sub(r"(?i)(authorization\s*:\s*bearer\s+)\S+", r"\1<redacted>", tail)
    tail = re.sub(r"(?i)(token|password|secret|api[_-]?key)\s*[:=]\s*\S+", r"\1=<redacted>", tail)
    return tail


def require_success(result: subprocess.CompletedProcess[str], description: str) -> str:
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        raise LifecycleError(
            f"{description} failed with exit code {result.returncode}\n{redacted_tail(output)}"
        )
    return output


def validate_before(repo_root: Path, artifact: Path) -> dict[str, Any]:
    path = artifact if artifact.is_absolute() else repo_root / artifact
    if not path.is_file():
        raise LifecycleError(f"before artifact is missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError(f"before artifact is not valid JSON: {path}: {exc}") from exc
    before = data.get("lifecycle", {}).get("before", data.get("before"))
    if not isinstance(before, dict) or before.get("status") not in {"verified", "passed"}:
        raise LifecycleError("before artifact must contain lifecycle.before.status=verified or passed")
    return {"path": str(path), "status": before["status"]}


def select_and_preview(repo_root: Path, host: str, target: str) -> str:
    require_success(run(["make", f"switch_remote.{host}"], repo_root), "host selection")
    require_success(run(["make", "env_show"], repo_root), "environment display")
    preview = require_success(run(["make", "-n", target], repo_root), f"preview {target}")
    limits = [match.group("quoted") or match.group("plain") for match in LIMIT_RE.finditer(preview)]
    if host not in limits:
        raise LifecycleError(f"{target} preview does not target {host}: {redacted_tail(preview, 8)}")
    return preview


def execute(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve()
    before = validate_before(repo_root, args.before_artifact)
    result: dict[str, Any] = {
        "schema_version": "auroraops.role-lifecycle-run/v1",
        "role": args.role,
        "host": args.host,
        "before": before,
        "stages": [],
    }
    if args.output:
        output_path = args.output if args.output.is_absolute() else repo_root / args.output
    else:
        output_path = None

    for stage, adapter_stage in STAGES:
        target = role_target(args.role, adapter_stage)
        select_and_preview(repo_root, args.host, target)
        completed = run(["make", target], repo_root)
        transcript = require_success(completed, stage)
        limits = [match.group("quoted") or match.group("plain") for match in LIMIT_RE.finditer(transcript)]
        if args.host not in limits:
            raise LifecycleError(f"{stage} execution did not target {args.host}")
        recaps = [line.strip() for line in transcript.splitlines() if RECAP_RE.match(line.strip())]
        if not recaps:
            raise LifecycleError(f"{stage} produced no Ansible PLAY RECAP evidence")
        if stage in NO_CHANGE_STAGES and any("changed=0" not in line for line in recaps):
            raise LifecycleError(f"{stage} changed state unexpectedly: {recaps}")
        stage_record = {"stage": stage, "target": target, "status": "passed", "recaps": recaps}
        result["stages"].append(stage_record)
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{stage}: passed ({target})")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AuroraOps role lifecycle assurance through parent Make targets")
    parser.add_argument("--role", required=True, help="Role ID, for example vps.services.mihomo_native")
    parser.add_argument("--host", required=True, help="Inventory host selected by make switch_remote.<host>")
    parser.add_argument("--before-artifact", type=Path, required=True, help="Sanitized JSON artifact containing lifecycle.before")
    parser.add_argument("--output", type=Path, help="Optional sanitized run summary JSON")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd(), help="auroraops-control repository root")
    args = parser.parse_args()
    try:
        execute(args)
    except LifecycleError as exc:
        print(f"lifecycle blocked: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
