from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, rel_path: str):
    path = ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


quality_gate = load_module("agent_quality_gate", "scripts/agent_quality_gate.py")


def test_load_quality_gate_manifest_reads_jsonc(tmp_path):
    manifest = tmp_path / "manifest.jsonc"
    manifest.write_text(
        """{
          // comment
          "events": {"pre-commit": {"gates": ["classify", "python-fast"]}}
        }""",
        encoding="utf-8",
    )

    data = quality_gate.load_quality_gate_manifest(manifest)

    assert data["events"]["pre-commit"]["gates"] == ["classify", "python-fast"]


def test_classify_paths_returns_docs_and_python_classes():
    manifest = {
        "classes": {
            "docs-only": {"globs": ["docs/**", "*.md"]},
            "python": {"globs": ["template/**/*.py", "tests/**/*.py"]},
        }
    }

    classes = quality_gate.classify_paths(
        ["docs/runbook.md", "template/scripts/agent_quality_gate.py"],
        manifest,
    )

    assert "docs-only" in classes
    assert "python" in classes
    assert "mixed" in classes


def test_select_gates_for_pre_push_includes_post_success_record():
    manifest = {
        "events": {
            "pre-push": {
                "default_gates": ["classify", "make-check"],
                "class_gates": {"python": ["python-heavy-static"]},
                "post_success": ["knowledge-record"],
            }
        },
        "classes": {
            "python": {"globs": ["template/**/*.py"]},
        },
    }

    plan = quality_gate.render_gate_plan("pre-push", ["template/scripts/foo.py"], manifest)

    assert plan["gates"] == ["classify", "make-check", "python-heavy-static"]
    assert plan["post_success"] == ["knowledge-record"]


def test_bypass_state_is_detected_from_env(monkeypatch):
    monkeypatch.setenv("QUALITY_GATES_BYPASS", "1")

    assert quality_gate.is_bypass_enabled("QUALITY_GATES_BYPASS") is True


def test_select_repo_gate_scope_uses_template_for_docs_only_changes():
    scope = quality_gate.select_repo_gate_scope([
        "docs/superpowers/specs/2026-07-07-agent-quality-gates-design.md"
    ])

    assert scope == "template"


def test_select_repo_gate_scope_uses_parent_for_parent_operational_changes():
    scope = quality_gate.select_repo_gate_scope([
        "CLAUDE.md",
        "Makefile",
        "private/agent/devspace.home.config.json",
    ])

    assert scope == "parent"


def test_collect_push_commit_metadata_returns_subjects_and_diffstat(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "a.md").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "docs: add a.md"], cwd=repo, check=True)

    meta = quality_gate.collect_push_commit_metadata(repo)

    assert meta["commit_count"] >= 1
    assert any("add a.md" in s for s in meta["subjects"])
    assert "a.md" in meta["diffstat"]


def test_build_push_knowledge_payload_carries_commit_subjects_not_gate_tokens(monkeypatch):
    import json

    class FakeRoot:
        pass

    monkeypatch.setattr(
        quality_gate, "collect_push_commit_metadata",
        lambda repo_root: {
            "subjects": ["feat: add quality gate", "fix: correct diffstat"],
            "diffstat": " scripts/agent_quality_gate.py | 12 ++++++++++++\n 1 file changed",
            "commit_count": 2,
            "range": "origin/main..HEAD",
        },
    )
    plan = {
        "classes": ["python"],
        "paths": ["scripts/agent_quality_gate.py"],
        "gates": ["classify", "make-check", "python-heavy-static"],
        "date": "2026-07-08",
    }
    payload = json.loads(quality_gate.build_push_knowledge_payload(plan, FakeRoot()))

    assert "feat: add quality gate" in payload["content"]
    assert "fix: correct diffstat" in payload["content"]
    assert "agent_quality_gate.py" in payload["content"]
    assert "执行门禁" not in payload["content"]
    assert payload["background"].strip() != ""


def test_knowledge_record_gate_accepts_chinese_dominant_push_summary_with_gate_tokens():
    payload = (
        '{"title":"推送质量门禁记录",'
        '"content":"本次推送通过质量门禁。变更分类：docs-only。执行门禁：classify、make-check、make-doctor。'
        '影响路径：docs/superpowers/specs/2026-07-07-agent-quality-gates-design.md。",'
        '"background":"自动记录一次推送级别的质量门禁结果，方便后续追溯自动化约束与影响范围。",'
        '"why_record":"沉淀一次真实发生的推送质量门禁结果与影响范围。",'
        '"tags":"质量门禁,自动记录",'
        f'"project_path":"{ROOT.parent}","date":"2026-07-07"}}'
    )

    result = subprocess.run(
        [str(ROOT / "scripts" / "knowledge-record-gate.sh"), "record-push", payload, "--dry-run"],
        cwd=ROOT.parent,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
