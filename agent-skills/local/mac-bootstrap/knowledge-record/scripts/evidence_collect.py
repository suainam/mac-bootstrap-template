#!/usr/bin/env python3
"""Repo evidence collection for knowledge-record suggest."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Mapping


@dataclass(frozen=True)
class EvidencePacket:
    worktree_summary: str
    test_summary: str
    command_summary: str
    references: list[str]

    def combined_text(self) -> str:
        parts = [
            f"工作区变更：{self.worktree_summary}",
            f"测试结果：{self.test_summary}",
            f"关键命令：{self.command_summary}",
        ]
        if self.references:
            parts.append("引用：" + ";".join(self.references))
        return "\n".join(parts)


def _run_git_status(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return "无法读取工作区状态。"
    output = result.stdout.strip()
    if not output:
        return "工作区无未提交变更。"
    count = len([line for line in output.splitlines() if line.strip()])
    return f"工作区有 {count} 项未提交变更。"


def collect_repo_evidence(repo_root: Path, env: Mapping[str, str] | None = None) -> EvidencePacket:
    values = env or os.environ
    references = [
        part.strip()
        for part in values.get("KNOWLEDGE_RECORD_REFERENCES", "").split(";")
        if part.strip()
    ]
    return EvidencePacket(
        worktree_summary=_run_git_status(repo_root),
        test_summary=values.get("KNOWLEDGE_RECORD_TEST_SUMMARY", "未提供本次测试摘要。"),
        command_summary=values.get("KNOWLEDGE_RECORD_COMMAND_SUMMARY", "未提供本次关键命令摘要。"),
        references=references,
    )
