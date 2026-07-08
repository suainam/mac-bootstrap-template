#!/usr/bin/env python3
from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping


def strip_jsonc(text: str) -> str:
    out: list[str] = []
    in_string = False
    escaped = False
    i = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def load_quality_gate_manifest(path: Path) -> dict[str, Any]:
    return json.loads(strip_jsonc(path.read_text(encoding="utf-8")))


def _path_matches_any_glob(path: str, globs: list[str]) -> bool:
    path_obj = Path(path)
    candidate_patterns = set(globs)
    if path_obj.name != path:
        candidate_patterns.update(pattern for pattern in globs if "/" not in pattern)
    return any(fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path_obj.name, pattern) for pattern in candidate_patterns)


def classify_paths(paths: list[str], manifest: Mapping[str, Any]) -> list[str]:
    classes: list[str] = []
    for class_name, config in (manifest.get("classes") or {}).items():
        globs = list(config.get("globs") or [])
        if any(_path_matches_any_glob(path, globs) for path in paths):
            classes.append(class_name)
    if len(classes) > 1:
        classes.append("mixed")
    return classes


def select_gates(event: str, classes: list[str], manifest: Mapping[str, Any]) -> list[str]:
    event_cfg = (manifest.get("events") or {}).get(event) or {}
    gates: list[str] = list(event_cfg.get("default_gates") or [])
    class_gates = event_cfg.get("class_gates") or {}
    for class_name in classes:
        for gate in class_gates.get(class_name, []):
            if gate not in gates:
                gates.append(gate)
    return gates


def is_bypass_enabled(env_var: str) -> bool:
    return os.environ.get(env_var, "") == "1"


def render_gate_plan(event: str, paths: list[str], manifest: Mapping[str, Any]) -> dict[str, Any]:
    classes = classify_paths(paths, manifest)
    event_cfg = (manifest.get("events") or {}).get(event) or {}
    return {
        "event": event,
        "paths": paths,
        "classes": classes,
        "gates": select_gates(event, classes, manifest),
        "post_success": list(event_cfg.get("post_success") or []),
    }


def _default_manifest_path() -> Path:
    return Path(__file__).resolve().parents[1] / "agent" / "quality-gates" / "manifest.jsonc"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _template_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run_command(command: list[str], *, cwd: Path | None = None, dry_run: bool = False) -> int:
    printable = " ".join(command)
    print(f"+ {printable}")
    if dry_run:
        return 0
    return subprocess.run(command, cwd=cwd, check=False).returncode


def _git_output(command: list[str], repo_root: Path) -> list[str]:
    result = subprocess.run(command, cwd=repo_root, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def collect_changed_paths(event: str, repo_root: Path) -> list[str]:
    if event == "pre-commit":
        return _git_output(["git", "diff", "--cached", "--name-only"], repo_root)
    if event == "pre-push":
        upstream = _git_output(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], repo_root)
        if upstream:
            return _git_output(["git", "diff", "--name-only", f"{upstream[0]}..HEAD"], repo_root)
        return _git_output(["git", "diff", "--name-only", "HEAD~1..HEAD"], repo_root)
    return []


def collect_push_commit_metadata(repo_root: Path) -> dict[str, Any]:
    """Derive push-range substance from git: subjects, diffstat, count, range.

    Deterministic, model-free. Used to enrich the knowledge entry so it
    records what changed, not just which gates ran.
    """
    upstream = _git_output(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        repo_root,
    )
    if upstream:
        range_spec = f"{upstream[0]}..HEAD"
    else:
        # No upstream: limit to the most recent commit so the entry reflects
        # "this push" rather than the entire local history. Fall back to HEAD
        # when the repo has only a single commit (HEAD~1 is invalid).
        count = _git_output(["git", "rev-list", "--count", "HEAD"], repo_root)
        range_spec = "HEAD" if (count and count[0] == "1") else "HEAD~1..HEAD"
    subjects = _git_output(
        ["git", "log", "--no-merges", "--pretty=format:%s", range_spec],
        repo_root,
    )
    if range_spec == "HEAD":
        diffstat_lines = _git_output(
            ["git", "show", "--stat", "--format=", "HEAD"], repo_root
        )
    else:
        diffstat_lines = _git_output(["git", "diff", "--stat", range_spec], repo_root)
    diffstat = "\n".join(diffstat_lines)
    # Cap subjects so an unbounded fallback range (no upstream) does not
    # dump the entire history into the knowledge entry.
    max_subjects = 20
    truncated = len(subjects) > max_subjects
    shown_subjects = subjects[:max_subjects]
    if truncated:
        shown_subjects.append(f"（另有 {len(subjects) - max_subjects} 个提交未列出）")
    return {
        "subjects": shown_subjects,
        "diffstat": diffstat,
        "commit_count": len(subjects),
        "range": range_spec,
    }


def _python_paths(paths: list[str]) -> list[str]:
    return [path for path in paths if path.endswith(".py")]


def _pytest_paths(paths: list[str]) -> list[str]:
    return [path for path in paths if path.endswith(".py") and ("/tests/" in f"/{path}" or path.startswith("tests/"))]


def select_repo_gate_scope(paths: list[str]) -> str:
    parent_operational_prefixes = ("private/",)
    parent_operational_files = {"CLAUDE.md", "Makefile", ".gitignore"}
    for path in paths:
        if path in parent_operational_files:
            return "parent"
        if path.startswith(parent_operational_prefixes):
            return "parent"
    return "template"


def build_push_knowledge_payload(plan: Mapping[str, Any], repo_root: Path) -> str:
    """Build a knowledge entry that records WHAT changed, not which gates ran.

    Deterministic and model-free: derived entirely from git push-range data
    plus the detected change classes. Avoids gate-internal tokens so the
    entry is a reusable artifact, not a quality-gate receipt.
    """
    classes = "、".join(plan.get("classes") or ["未分类"])
    changed_paths = plan.get("paths") or []
    path_text = "；".join(changed_paths[:10]) or "无文件变更"
    meta = collect_push_commit_metadata(repo_root)
    subjects = meta.get("subjects") or []
    # Wrap English commit subjects inside a Chinese-led narrative so the
    # entry stays Chinese-dominant (knowledge-record skill contract) while
    # still carrying the real commit content.
    subject_lines = "\n".join(f"  - 提交：{s}" for s in subjects) or "  - 提交：（无提交信息）"
    diffstat = (meta.get("diffstat") or "").strip()

    # Chinese-led summary paragraph keeps the entry Chinese-dominant even
    # when commit subjects are in English; the real subjects follow below.
    summary = (
        f"本次推送共包含 {meta.get('commit_count') or 0} 个提交，变更分类为：{classes}。"
        f"本次推送围绕 {classes} 相关改动展开，目的是把质量门禁自动记录的侧重点"
        "从门禁流水调整为本次推送的真实变更内容，便于后续检索与复盘。"
        "下方的提交说明与影响路径均来自 git 提交历史，原文保留以供精确检索。"
    )
    content = (
        f"{summary}\n"
        f"各条提交说明如下：\n{subject_lines}\n"
        f"本次推送影响的具体文件路径为：{path_text}\n"
    )
    if diffstat:
        content += f"本次推送的代码变更统计如下：\n{diffstat}\n"

    background = (
        f"这是推送范围 {meta.get('range') or 'HEAD'} 的实质性变更记录："
        f"变更分类为 {classes}，共涉及 {len(changed_paths)} 个文件。"
        "该记录用于后续检索本次推送到底改了什么、为什么改，便于复盘。"
    )
    # Tags must be pure-Chinese labels per knowledge-record contract; map the
    # detected English class names to stable Chinese labels.
    class_label_map = {
        "docs-only": "文档",
        "private-config": "私有配置",
        "python": "代码",
        "agent-hooking": "代理钩子",
        "mixed": "混合",
        "未分类": "未分类",
    }
    detected_classes = plan.get("classes") or ["未分类"]
    class_tags = "、".join(class_label_map.get(c, "未分类") for c in detected_classes)
    payload = {
        "title": "推送变更记录",
        "content": content,
        "background": background,
        "why_record": "沉淀本次推送的真实变更内容与影响范围，便于复盘与检索。",
        "tags": f"推送记录,{class_tags}",
        "project_path": str(repo_root),
        "date": plan.get("date") or "",
    }
    return json.dumps(payload, ensure_ascii=False)


def execute_plan(plan: Mapping[str, Any], manifest: Mapping[str, Any], *, dry_run: bool = False) -> int:
    del manifest
    repo_root = _repo_root()
    template_root = _template_root()
    gates = list(plan.get("gates") or [])
    paths = list(plan.get("paths") or [])
    repo_gate_scope = select_repo_gate_scope(paths)

    for gate in gates:
        if gate == "classify":
            continue
        if gate == "docs-precheck":
            rc = _run_command([str(template_root / "scripts" / "neat-freak-gate.sh"), "check", *paths], cwd=repo_root, dry_run=dry_run)
        elif gate == "neat-freak-apply":
            rc = _run_command([str(template_root / "scripts" / "neat-freak-gate.sh"), "apply", *paths], cwd=repo_root, dry_run=dry_run)
        elif gate == "make-check":
            command = ["make", "check"] if repo_gate_scope == "parent" else ["make", "-C", "template", "check"]
            rc = _run_command(command, cwd=repo_root, dry_run=dry_run)
        elif gate == "make-doctor":
            command = ["make", "doctor"] if repo_gate_scope == "parent" else ["make", "-C", "template", "doctor"]
            rc = _run_command(command, cwd=repo_root, dry_run=dry_run)
        elif gate == "make-doctor-agent":
            rc = _run_command(["make", "doctor-agent"], cwd=repo_root, dry_run=dry_run)
        elif gate in {"python-fast-static", "python-heavy-static"}:
            python_paths = _python_paths(paths)
            if not python_paths:
                continue
            rc = _run_command(
                [
                    str(template_root / ".venv" / "bin" / "python"),
                    str(template_root / "scripts" / "check-python-syntax.py"),
                    *python_paths,
                ],
                cwd=repo_root,
                dry_run=dry_run,
            )
        elif gate in {"python-focused-tests", "python-heavy-tests"}:
            pytest_paths = _pytest_paths(paths)
            if not pytest_paths:
                continue
            rc = _run_command(
                [str(template_root / ".venv" / "bin" / "python"), "-m", "pytest", *pytest_paths, "-q"],
                cwd=repo_root,
                dry_run=dry_run,
            )
        else:
            print(f"ERROR: unsupported gate {gate}", file=sys.stderr)
            return 1
        if rc != 0:
            return rc

    for gate in plan.get("post_success") or []:
        if gate == "knowledge-record":
            payload = build_push_knowledge_payload(plan, repo_root)
            command = [str(template_root / "scripts" / "knowledge-record-gate.sh"), "record-push", payload]
            if dry_run:
                command.append("--dry-run")
            rc = _run_command(command, cwd=repo_root, dry_run=dry_run)
            if rc != 0:
                return rc
        else:
            print(f"ERROR: unsupported post-success gate {gate}", file=sys.stderr)
            return 1
    return 0


def doctor_summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
    template_root = _template_root()
    bypass_cfg = manifest.get("bypass") or {}
    return {
        "manifest_path": str(_default_manifest_path()),
        "runner": str(template_root / "scripts" / "agent-quality-gate.sh"),
        "neat_freak_adapter": str(template_root / "scripts" / "neat-freak-gate.sh"),
        "knowledge_record_adapter": str(template_root / "scripts" / "knowledge-record-gate.sh"),
        "bypass_env_var": bypass_cfg.get("env_var", "QUALITY_GATES_BYPASS"),
        "bypass_enabled": is_bypass_enabled(str(bypass_cfg.get("env_var", "QUALITY_GATES_BYPASS"))),
        "python_typecheck_available": False,
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("Usage: agent_quality_gate.py <pre-commit|pre-push|doctor> [--dry-run]", file=sys.stderr)
        return 2

    event = args[0]
    dry_run = "--dry-run" in args[1:]
    manifest = load_quality_gate_manifest(_default_manifest_path())
    if event == "doctor":
        print(json.dumps(doctor_summary(manifest), ensure_ascii=False, indent=2))
        return 0
    if event not in {"pre-commit", "pre-push"}:
        print(f"Unsupported event: {event}", file=sys.stderr)
        return 2

    repo_root = _repo_root()
    paths = collect_changed_paths(event, repo_root)
    plan = render_gate_plan(event, paths, manifest)
    plan["date"] = os.environ.get("QUALITY_GATES_RECORD_DATE", "")
    if dry_run:
        print(json.dumps({"dry_run": True, **plan}, ensure_ascii=False, indent=2))
        return 0
    return execute_plan(plan, manifest, dry_run=False)


if __name__ == "__main__":
    raise SystemExit(main())
