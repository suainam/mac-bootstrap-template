from __future__ import annotations

import importlib.util
import json
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
    # Tags must be pure-Chinese labels; English class is mapped
    assert payload["tags"] == "推送记录,代码"


def test_build_push_knowledge_payload_splits_multiple_class_tags(monkeypatch):
    import json

    class FakeRoot:
        pass

    monkeypatch.setattr(
        quality_gate,
        "collect_push_commit_metadata",
        lambda repo_root: {
            "subjects": ["docs: update runbook"],
            "diffstat": " docs/runbook.md | 1 +\n private/config.jsonc | 1 +",
            "commit_count": 1,
            "range": "origin/main..HEAD",
        },
    )
    plan = {
        "classes": ["docs-only", "private-config", "mixed"],
        "paths": ["docs/runbook.md", "private/config.jsonc"],
        "gates": ["classify"],
        "date": "2026-07-10",
    }

    payload = json.loads(quality_gate.build_push_knowledge_payload(plan, FakeRoot()))

    assert payload["tags"] == "推送记录,文档,私有配置,混合"


def test_knowledge_record_gate_does_not_append_chinese_filler(tmp_path):
    payload = json.dumps({
        "title": "推送变更记录",
        "content": "本次推送包含 1 个提交，变更分类：python。",
        "background": "推送范围的实质性变更记录。",
        "why_record": "沉淀本次推送的真实变更内容。",
        "tags": "推送记录,代码",
        "project_path": str(tmp_path),
        "date": "2026-07-08",
    }, ensure_ascii=False)
    result = subprocess.run(
        [str(ROOT / "scripts" / "knowledge-record-gate.sh"), "record-push", payload, "--dry-run"],
        cwd=ROOT.parent,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "补充说明" not in result.stdout
    assert "补充说明" not in result.stderr


def test_knowledge_record_gate_accepts_substance_push_summary():
    payload = (
        '{"title":"推送变更记录",'
        '"content":"本次推送共包含 2 个提交，变更分类为：python。'
        '本次推送围绕 python 相关改动展开，目的是把质量门禁自动记录的侧重点'
        '从门禁流水调整为本次推送的真实变更内容，便于后续检索与复盘。'
        '下方的提交说明与影响路径均来自 git 提交历史，原文保留以供精确检索。'
        '各条提交说明如下：\\n  - 提交：feat: add quality gate\\n  - 提交：fix: correct diffstat\\n'
        '本次推送影响的具体文件路径为：scripts/agent_quality_gate.py\\n",'
        '"background":"这是推送范围 origin/main..HEAD 的实质性变更记录：变更分类为 python，共涉及 1 个文件。",'
        '"why_record":"沉淀本次推送的真实变更内容与影响范围，便于复盘与检索。",'
        '"tags":"推送记录,代码",'
        f'"project_path":"{ROOT.parent}","date":"2026-07-08"}}'
    )

    result = subprocess.run(
        [str(ROOT / "scripts" / "knowledge-record-gate.sh"), "record-push", payload, "--dry-run"],
        cwd=ROOT.parent,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
