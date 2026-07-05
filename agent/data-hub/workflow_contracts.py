"""Typed workflow stage contracts and success checks."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


def get_vault_dir() -> Path:
    return Path(os.path.expandvars(os.environ.get("OBSIDIAN_VAULT_DIR", str(Path.home() / "work/knowledge"))))


@dataclass(frozen=True)
class SuccessCheck:
    kind: str
    target: str
    expected: Any = True

    @classmethod
    def from_value(cls, value: "SuccessCheck | Mapping[str, Any]") -> "SuccessCheck":
        if isinstance(value, cls):
            return value
        return cls(kind=value["kind"], target=value["target"], expected=value.get("expected", True))

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "target": self.target, "expected": self.expected}


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    retryable_exit_codes: tuple[int, ...] = field(default_factory=tuple)
    backoff_seconds: float = 0.0

    @classmethod
    def from_value(cls, value: "RetryPolicy | Mapping[str, Any] | None") -> "RetryPolicy":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        return cls(
            max_attempts=int(value.get("max_attempts", 1)),
            retryable_exit_codes=tuple(value.get("retryable_exit_codes", ())),
            backoff_seconds=float(value.get("backoff_seconds", 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_attempts": self.max_attempts,
            "retryable_exit_codes": list(self.retryable_exit_codes),
            "backoff_seconds": self.backoff_seconds,
        }


@dataclass(frozen=True)
class StageSpec:
    name: str
    command: list[str]
    produces: list[str] = field(default_factory=list)
    success_checks: list[SuccessCheck] = field(default_factory=list)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    degraded_ok: bool = False

    @classmethod
    def from_value(cls, value: "StageSpec | Mapping[str, Any]") -> "StageSpec":
        if isinstance(value, cls):
            return value
        return cls(
            name=value["name"],
            command=list(value["command"]),
            produces=list(value.get("produces", [])),
            success_checks=[SuccessCheck.from_value(check) for check in value.get("success_checks", [])],
            retry_policy=RetryPolicy.from_value(value.get("retry_policy")),
            degraded_ok=parse_bool(value.get("degraded_ok", False)),
        )

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "produces": self.produces,
            "success_checks": [check.to_dict() for check in self.success_checks],
            "retry_policy": self.retry_policy.to_dict(),
            "degraded_ok": self.degraded_ok,
        }


@dataclass(frozen=True)
class StageResult:
    name: str
    status: str
    run_id: str
    attempt: int
    stdout_path: str
    stderr_path: str
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "name": self.name,
            "status": self.status,
            "run_id": self.run_id,
            "attempt": self.attempt,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
        }
        if self.error_message:
            result["error_message"] = self.error_message
        return result


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1", "yes", "on"):
            return True
        if normalized in ("false", "0", "no", "off", ""):
            return False
    if value in (0, None):
        return False
    if value == 1:
        return True
    raise ValueError(f"expected boolean value, got {value!r}")


def normalize_stage(value: StageSpec | Mapping[str, Any]) -> StageSpec:
    return StageSpec.from_value(value)


def stages_to_dicts(stages: list[StageSpec | Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_stage(stage).to_dict() for stage in stages]


def evaluate_success_checks(stage: StageSpec, stdout_path: Path, stderr_path: Path) -> tuple[bool, str | None]:
    for check in stage.success_checks:
        passed, message = evaluate_success_check(check, stdout_path, stderr_path)
        if not passed:
            return False, message
    return True, None


def evaluate_success_check(check: SuccessCheck, stdout_path: Path, stderr_path: Path) -> tuple[bool, str | None]:
    if check.kind == "file_exists":
        path = resolve_target_path(check.target)
        passed = path.exists() == bool(check.expected)
        return passed, None if passed else f"expected file exists={check.expected}: {path}"

    if check.kind == "stdout_exists":
        passed = stdout_path.exists() and stdout_path.is_file()
        return passed, None if passed else f"stdout log missing: {stdout_path}"

    if check.kind == "output_not_contains":
        haystack = read_output_target(check.target, stdout_path, stderr_path)
        needles = check.expected if isinstance(check.expected, list) else [check.expected]
        found = [str(needle) for needle in needles if str(needle) and str(needle) in haystack]
        passed = not found
        return passed, None if passed else f"output contained disallowed marker: {', '.join(found)}"

    return False, f"unknown success check kind: {check.kind}"


def resolve_target_path(target: str) -> Path:
    path = Path(os.path.expandvars(target)).expanduser()
    if path.is_absolute():
        return path
    return get_vault_dir() / path


def read_output_target(target: str, stdout_path: Path, stderr_path: Path) -> str:
    paths = {
        "stdout": [stdout_path],
        "stderr": [stderr_path],
        "combined": [stdout_path, stderr_path],
    }.get(target)
    if paths is None:
        paths = [resolve_target_path(target)]
    return "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in paths if path.exists())
