"""Durable workflow execution for Agent Data Hub."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Mapping, Any

from db_helper import get_db_connection
from workflow_contracts import StageSpec, evaluate_success_checks, normalize_stage


CURRENT_DIR = Path(__file__).resolve().parent


def now_iso() -> str:
    return datetime.now().isoformat(timespec="microseconds")


def hash_json(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def db_path_from_env() -> Path:
    return Path(
        os.path.expandvars(
            os.environ.get(
                "AGENT_DB_PATH",
                str(Path.home() / "work/config/mac-bootstrap/private/agent/data/agent_history.db"),
            )
        )
    )


def get_runs_dir() -> Path:
    configured = os.environ.get("AGENT_RUNS_DIR")
    if configured:
        return Path(os.path.expandvars(configured))
    return db_path_from_env().parent / "runs"


def generate_run_id(workflow_name: str, target_date: str) -> str:
    started = now_iso()
    digest = hashlib.sha1(f"{workflow_name}:{target_date}:{started}".encode("utf-8")).hexdigest()[:10]
    return f"run_{target_date.replace('-', '')}_{digest}"


class WorkflowRunner:
    """Run workflow steps with durable DB state and per-step log files."""

    def __init__(self, *, conn=None, command_runner=None, runs_dir: Path | None = None, sleep=time.sleep):
        self.owns_conn = conn is None
        self.conn = conn or get_db_connection()
        self.command_runner = command_runner or subprocess.run
        self.runs_dir = runs_dir or get_runs_dir()
        self.sleep = sleep

    def close(self) -> None:
        if self.owns_conn:
            self.conn.close()

    def __enter__(self) -> "WorkflowRunner":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def run(
        self,
        workflow_name: str,
        target_date: str,
        steps: list[StageSpec | Mapping[str, Any]],
        *,
        run_id: str | None = None,
        resume_run_id: str | None = None,
        retry_failed_run_id: str | None = None,
        from_step: str | None = None,
        max_attempts: int = 1,
    ) -> list[dict]:
        active_run_id = self._prepare_run(
            workflow_name,
            target_date,
            run_id=run_id,
            resume_run_id=resume_run_id,
            retry_failed_run_id=retry_failed_run_id,
            max_attempts=max_attempts,
        )
        run_dir = self.runs_dir / active_run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        stage_specs = [normalize_stage(step) for step in steps]
        start_index = self._start_index(
            active_run_id,
            stage_specs,
            resume=bool(resume_run_id),
            retry_failed=bool(retry_failed_run_id),
            from_step=from_step,
        )

        results: list[dict] = []
        degraded = False
        for index, step in enumerate(stage_specs):
            existing_status = self._step_status(active_run_id, index)
            if existing_status == "degraded":
                degraded = True
            if index < start_index or (from_step is None and self._is_step_done(existing_status)):
                self._ensure_step(active_run_id, index, step)
                results.append({"name": step["name"], "status": "skipped", "run_id": active_run_id})
                continue

            step_id = self._ensure_step(active_run_id, index, step)
            result = self._run_step(active_run_id, step_id, index, step, run_dir, max_attempts)
            results.append(result)
            if result["status"] == "degraded":
                degraded = True
            if result["status"] == "failed":
                self._finish_run(active_run_id, "failed", result.get("error_message"))
                return results

        self._finish_run(active_run_id, "degraded" if degraded else "completed", None)
        return results

    def _prepare_run(
        self,
        workflow_name: str,
        target_date: str,
        *,
        run_id: str | None,
        resume_run_id: str | None,
        retry_failed_run_id: str | None,
        max_attempts: int,
    ) -> str:
        self._validate_run_mode(run_id, resume_run_id, retry_failed_run_id)
        if resume_run_id or retry_failed_run_id:
            active_run_id = resume_run_id or retry_failed_run_id
            self._validate_existing_run(active_run_id, workflow_name, target_date)
            self._mark_run_running(active_run_id, max_attempts)
            return active_run_id

        active_run_id = run_id or generate_run_id(workflow_name, target_date)
        self._create_run(active_run_id, workflow_name, target_date, max_attempts)
        return active_run_id

    def _validate_run_mode(
        self,
        run_id: str | None,
        resume_run_id: str | None,
        retry_failed_run_id: str | None,
    ) -> None:
        selected = [value for value in (run_id, resume_run_id, retry_failed_run_id) if value]
        if len(selected) > 1:
            raise ValueError("run_id, resume_run_id, and retry_failed_run_id are mutually exclusive")

    def _create_run(self, run_id: str, workflow_name: str, target_date: str, max_attempts: int) -> None:
        self.conn.execute(
            """
            INSERT INTO workflow_runs
                (id, workflow_name, target_date, status, started_at, max_attempts, metadata_json)
            VALUES (?, ?, ?, 'running', ?, ?, '{}')
            """,
            (run_id, workflow_name, target_date, now_iso(), max_attempts),
        )
        self.conn.commit()

    def _validate_existing_run(self, run_id: str, workflow_name: str, target_date: str) -> None:
        row = self.conn.execute(
            "SELECT workflow_name, target_date FROM workflow_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"unknown run_id: {run_id}")
        if row["workflow_name"] != workflow_name or row["target_date"] != target_date:
            raise ValueError(f"run_id {run_id} does not match workflow/date")

    def _mark_run_running(self, run_id: str, max_attempts: int) -> None:
        self.conn.execute(
            """
            UPDATE workflow_runs
            SET status = 'running', completed_at = NULL, max_attempts = ?, error_message = NULL
            WHERE id = ?
            """,
            (max_attempts, run_id),
        )
        self.conn.commit()

    def _finish_run(self, run_id: str, status: str, error_message: str | None) -> None:
        self.conn.execute(
            "UPDATE workflow_runs SET status = ?, completed_at = ?, error_message = ? WHERE id = ?",
            (status, now_iso(), error_message, run_id),
        )
        self.conn.commit()

    def _start_index(
        self,
        run_id: str,
        steps: list[StageSpec],
        *,
        resume: bool,
        retry_failed: bool,
        from_step: str | None,
    ) -> int:
        if from_step:
            for index, step in enumerate(steps):
                if step.name == from_step:
                    return index
            raise ValueError(f"unknown step for workflow: {from_step}")
        if retry_failed:
            row = self.conn.execute(
                """
                SELECT step_index FROM workflow_steps
                WHERE run_id = ? AND status = 'failed'
                ORDER BY step_index ASC LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            return int(row["step_index"]) if row else 0
        if resume:
            rows = self.conn.execute(
                "SELECT step_index, status FROM workflow_steps WHERE run_id = ? ORDER BY step_index ASC",
                (run_id,),
            ).fetchall()
            completed = {int(row["step_index"]) for row in rows if row["status"] in ("completed", "degraded")}
            for index in range(len(steps)):
                if index not in completed:
                    return index
            return len(steps)
        return 0

    def _step_status(self, run_id: str, step_index: int) -> str | None:
        row = self.conn.execute(
            "SELECT status FROM workflow_steps WHERE run_id = ? AND step_index = ?",
            (run_id, step_index),
        ).fetchone()
        return row["status"] if row else None

    def _is_step_done(self, status: str | None) -> bool:
        return status in ("completed", "degraded")

    def _ensure_step(self, run_id: str, step_index: int, step: StageSpec) -> str:
        step_id = f"{run_id}_step_{step_index + 1:02d}"
        self.conn.execute(
            """
            INSERT INTO workflow_steps
                (id, run_id, step_index, step_name, status, command_json, produces_json, input_hash)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
            ON CONFLICT(run_id, step_index) DO UPDATE SET
                step_name = excluded.step_name,
                command_json = excluded.command_json,
                produces_json = excluded.produces_json,
                input_hash = excluded.input_hash
            """,
            (
                step_id,
                run_id,
                step_index,
                step.name,
                json.dumps(step.command, ensure_ascii=False),
                json.dumps(step.produces, ensure_ascii=False),
                hash_json(
                    {
                        "command": step.command,
                        "produces": step.produces,
                        "success_checks": [check.to_dict() for check in step.success_checks],
                    }
                ),
            ),
        )
        self.conn.commit()
        return step_id

    def _run_step(
        self,
        run_id: str,
        step_id: str,
        step_index: int,
        step: StageSpec,
        run_dir: Path,
        max_attempts: int,
    ) -> dict:
        last_error = ""
        attempts = max(max_attempts, step.retry_policy.max_attempts)
        stdout_path = stderr_path = None
        for attempt in range(1, attempts + 1):
            stdout_path, stderr_path = self._log_paths(run_dir, step_index, step.name, attempt)
            self._mark_step_running(step_id, attempt, stdout_path, stderr_path)
            try:
                completed = self.command_runner(step.command, cwd=CURRENT_DIR, capture_output=True, text=True)
            except Exception as exc:
                last_error = str(exc) or exc.__class__.__name__
                stdout_path.write_text("", encoding="utf-8")
                stderr_path.write_text(last_error, encoding="utf-8")
                self._mark_step_failed(step_id, -1, last_error)
                self._record_log_artifacts(run_id, step_id, stdout_path, stderr_path)
                if attempt < attempts and self._should_retry(-1, step):
                    self.sleep(self._backoff_seconds(attempt, step))
                    continue
                break
            stdout_path.write_text(completed.stdout or "", encoding="utf-8")
            stderr_path.write_text(completed.stderr or "", encoding="utf-8")

            if completed.returncode == 0:
                self._record_log_artifacts(run_id, step_id, stdout_path, stderr_path)
                checks_passed, check_error = evaluate_success_checks(step, stdout_path, stderr_path)
                if checks_passed:
                    self._mark_step_finished(step_id, "completed", completed.returncode, step, stdout_path, stderr_path)
                    return self._result(step.name, "completed", run_id, attempt, stdout_path, stderr_path)
                last_error = check_error or "success check failed"
                if step.degraded_ok:
                    self._mark_step_finished(
                        step_id,
                        "degraded",
                        completed.returncode,
                        step,
                        stdout_path,
                        stderr_path,
                        error_message=last_error,
                    )
                    result = self._result(step.name, "degraded", run_id, attempt, stdout_path, stderr_path)
                    result["error_message"] = last_error
                    return result
                self._mark_step_failed(step_id, completed.returncode, last_error)
                if attempt < attempts and self._should_retry(completed.returncode, step):
                    self.sleep(self._backoff_seconds(attempt, step))
                    continue
                break

            last_error = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()
            self._mark_step_failed(step_id, completed.returncode, last_error)
            self._record_log_artifacts(run_id, step_id, stdout_path, stderr_path)
            if attempt < attempts and self._should_retry(completed.returncode, step):
                self.sleep(self._backoff_seconds(attempt, step))
                continue
            break

        result = self._result(step.name, "failed", run_id, attempt, stdout_path, stderr_path)
        result["error_message"] = last_error
        return result

    def _should_retry(self, exit_code: int, step: StageSpec) -> bool:
        retryable = step.retry_policy.retryable_exit_codes
        return not retryable or exit_code in retryable

    def _backoff_seconds(self, attempt: int, step: StageSpec) -> float:
        if step.retry_policy.backoff_seconds:
            return step.retry_policy.backoff_seconds
        return min(2 ** (attempt - 1), 30)

    def _log_paths(self, run_dir: Path, step_index: int, step_name: str, attempt: int) -> tuple[Path, Path]:
        safe_name = step_name.replace("/", "_").replace(":", "_")
        prefix = run_dir / f"{step_index + 1:02d}-{safe_name}.attempt{attempt}"
        return prefix.with_suffix(".stdout.log"), prefix.with_suffix(".stderr.log")

    def _mark_step_running(self, step_id: str, attempt: int, stdout_path: Path, stderr_path: Path) -> None:
        self.conn.execute(
            """
            UPDATE workflow_steps
            SET status = 'running', attempt = ?, started_at = ?, completed_at = NULL,
                exit_code = NULL, stdout_path = ?, stderr_path = ?, error_message = NULL
            WHERE id = ?
            """,
            (attempt, now_iso(), str(stdout_path), str(stderr_path), step_id),
        )
        self.conn.commit()

    def _mark_step_finished(
        self,
        step_id: str,
        status: str,
        exit_code: int,
        step: StageSpec,
        stdout_path: Path,
        stderr_path: Path,
        *,
        error_message: str | None = None,
    ) -> None:
        output_hash = hash_json(
            {"stdout": hash_file(stdout_path), "stderr": hash_file(stderr_path), "produces": step.produces}
        )
        self.conn.execute(
            """
            UPDATE workflow_steps
            SET status = ?, completed_at = ?, exit_code = ?, output_hash = ?, error_message = ?
            WHERE id = ?
            """,
            (status, now_iso(), exit_code, output_hash, error_message[:1000] if error_message else None, step_id),
        )
        self.conn.commit()

    def _mark_step_failed(self, step_id: str, exit_code: int, error_message: str) -> None:
        self.conn.execute(
            """
            UPDATE workflow_steps
            SET status = 'failed', completed_at = ?, exit_code = ?, error_message = ?
            WHERE id = ?
            """,
            (now_iso(), exit_code, error_message[:1000], step_id),
        )
        self.conn.commit()

    def _record_log_artifacts(self, run_id: str, step_id: str, stdout_path: Path, stderr_path: Path) -> None:
        created_at = now_iso()
        for path, kind in ((stdout_path, "stdout"), (stderr_path, "stderr")):
            artifact_key = f"{run_id}:{step_id}:{kind}:{path}"
            artifact_id = f"artifact_{hashlib.sha1(artifact_key.encode('utf-8')).hexdigest()[:16]}"
            self.conn.execute(
                """
                INSERT OR REPLACE INTO artifact_manifest
                    (id, run_id, step_id, artifact_path, artifact_kind, content_hash, created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, '{}')
                """,
                (artifact_id, run_id, step_id, str(path), kind, hash_file(path), created_at),
            )
        self.conn.commit()

    def _result(self, name: str, status: str, run_id: str, attempt: int, stdout_path: Path, stderr_path: Path) -> dict:
        return {
            "name": name,
            "status": status,
            "run_id": run_id,
            "attempt": attempt,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
