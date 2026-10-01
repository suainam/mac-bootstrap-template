#!/usr/bin/env python3
"""Dispatch CLI & Automation Engine.

Self-contained inside dispatch skill.
Handles contract validation, state machine transitions, and Herdr process management.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class Phase(str, Enum):
    INIT = "init"
    RESEARCH = "research"
    WRITER_IMPLEMENTATION = "writer_implementation"
    SKEPTIC_REVIEW = "skeptic_review"
    AWAITING_HUMAN_GATE = "awaiting_human_gate"
    CLOSED = "closed"


VALID_TRANSITIONS: Dict[Phase, List[Phase]] = {
    Phase.INIT: [Phase.RESEARCH, Phase.WRITER_IMPLEMENTATION],
    Phase.RESEARCH: [Phase.WRITER_IMPLEMENTATION],
    Phase.WRITER_IMPLEMENTATION: [Phase.SKEPTIC_REVIEW, Phase.AWAITING_HUMAN_GATE],
    Phase.SKEPTIC_REVIEW: [Phase.WRITER_IMPLEMENTATION, Phase.AWAITING_HUMAN_GATE],
    Phase.AWAITING_HUMAN_GATE: [Phase.CLOSED],
    Phase.CLOSED: [],
}

MANDATORY_GOAL_SECTIONS = [
    "目标",
    "验证",
    "约束",
    "边界",
    "迭代策略",
    "完成条件",
    "暂停条件",
]

# Issue #125 — a task contract must also state HOW the work is done efficiently
# and WHICH standard skill pipeline executes it. Both clauses are alternatives,
# not all-of: a trivial task has no use for every tool, and demanding all of them
# turns a contract check into box-ticking.
#
# Matched case-insensitively against the whole document, so the clause may live
# in any section rather than being forced into a particular heading.
#
# Known limitation: this is a vocabulary check, not a commitment check. A contract
# that merely *describes* these terms -- quoting the list to explain what the
# rule requires -- satisfies it. That is the same trade every mechanical lint
# makes, and tightening it toward "must appear in a directive position" would
# be trivially gameable by rephrasing.
EFFICIENCY_CRITERIA: List[str] = [
    "rtk",
    "caveman ultra",
    "codebase-memory-mcp",
]

SKILL_TOOLCHAIN: List[str] = [
    "to-spec",
    "to-tickets",
    "implement-spec",
    "implement",
    "wayfinder",
]


class TaskContractError(Exception):
    pass


class StateTransitionError(Exception):
    pass


def _find_any(content: str, needles: List[str]) -> str:
    """Return the first needle present in ``content``, or "" if none is."""
    lowered = content.lower()
    for needle in needles:
        if needle.lower() in lowered:
            return needle
    return ""


def check_toolchain_contract(content: str) -> List[str]:
    """Return the Issue #125 clauses the contract does not satisfy.

    Pure: returns names of missing clauses, raises nothing, so the caller decides
    whether a miss is fatal.
    """
    missing: List[str] = []
    if not _find_any(content, EFFICIENCY_CRITERIA):
        missing.append(
            f"效能准则 (any of: {', '.join(EFFICIENCY_CRITERIA)})"
        )
    if not _find_any(content, SKILL_TOOLCHAIN):
        missing.append(
            f"标准 Skill 执行流 (any of: {', '.join(dict.fromkeys(SKILL_TOOLCHAIN))})"
        )
    return missing


def lint_task_contract(task_path: Path, *, allow_legacy: bool = False) -> None:
    if not task_path.is_file():
        raise TaskContractError(f"Task file '{task_path}' does not exist.")

    content = task_path.read_text(encoding="utf-8")

    # 1. 7 mandatory sections validation with non-empty content checking
    missing: List[str] = []
    for sec in MANDATORY_GOAL_SECTIONS:
        # Require section heading plus non-trivial content after it
        pattern = rf"(?:^|\n)#+\s*.*{sec}.*\n+([\s\S]+?)(?=\n#+\s*|\Z)"
        match = re.search(pattern, content, re.IGNORECASE)
        if not match:
            missing.append(sec)
        else:
            section_body = match.group(1).strip()
            if len(section_body) < 5:
                missing.append(f"{sec}(内容过短或为空)")

    if missing:
        raise TaskContractError(
            f"Task file '{task_path}' violates Qiaomu Goal Contract. "
            f"Missing or empty mandatory sections: {', '.join(missing)}.\n"
            "Action required: Formulate a compliant 7-section specification via /skill:qiaomu-goal-meta-skill."
        )

    # 2. Anti-Pseudo-Delegation check: absolute barrier against inlining raw diffs or patch code
    patch_patterns = [
        r"^\s*diff --git",
        r"^\s*@@\s+-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@",
        r"^\s*(\+\+\+|---)\s+[ab]/",
    ]
    for pat in patch_patterns:
        if re.search(pat, content, re.MULTILINE):
            raise TaskContractError(
                f"Pseudo-Delegation detected in '{task_path}'!\n"
                "The orchestrator must specify WHAT & ACCEPTANCE (outcomes, boundaries, verification commands),\n"
                "NEVER line-by-line patch code or raw diffs (HOW).\n"
                "Action required: Remove the raw diff/patch from the task specification."
            )

    # 3. Issue #125 — efficiency criteria and standard skill toolchain.
    #
    # Checked after the structural rules so a contract that is missing a whole
    # section is told that first; fixing the structure and then the toolchain is
    # two edits, but reporting the toolchain miss on an otherwise-broken file
    # buries the bigger problem.
    if allow_legacy:
        missing_clauses = check_toolchain_contract(content)
        if missing_clauses:
            # Loud, not silent: a grandfathered contract should never look
            # compliant by accident.
            print(
                f"Warning: '{task_path}' lacks {', '.join(missing_clauses)} "
                "(Issue #125 grandfathered via --allow-legacy).",
                file=sys.stderr,
            )
        return

    missing_clauses = check_toolchain_contract(content)
    if missing_clauses:
        raise TaskContractError(
            f"Task file '{task_path}' violates the Issue #125 toolchain contract.\n"
            f"Missing: {', '.join(missing_clauses)}.\n"
            "A contract must say how the work is done efficiently and which standard\n"
            "skill pipeline executes it, so a lane cannot silently reinvent both.\n"
            "Action required: add the missing clause(s) to any section, or re-lint with\n"
            "--allow-legacy to grandfather a pre-Issue-125 contract."
        )


def resolve_state_file(repo_path: Optional[str] = None) -> Path:
    """Resolve the state file path anchored to git-common-dir to prevent split-brain in worktrees."""
    target_dir = Path(repo_path) if repo_path else Path.cwd()
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=target_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        common_dir = Path(res.stdout.strip())
        return common_dir / "dispatch" / "ORCHESTRATOR_STATE.json"
    except Exception:
        # Fallback to local .dispatch inside target directory
        return target_dir / ".dispatch" / "ORCHESTRATOR_STATE.json"


@dataclass
class OrchestratorState:
    schema: int
    task_id: str
    phase: Phase
    review_round: int
    max_review_rounds: int
    lanes: Dict[str, Dict[str, Any]]
    known_facts: Dict[str, Any]
    awaiting_human_gate: bool
    extra_data: Dict[str, Any]
    @classmethod
    def load(cls, path: Path) -> OrchestratorState:
        default_state = cls(
            schema=2,
            task_id="default",
            phase=Phase.INIT,
            review_round=0,
            max_review_rounds=2,
            lanes={},
            known_facts={},
            awaiting_human_gate=False,
            extra_data={},
        )
        if not path.is_file():
            return default_state

        try:
            raw_text = path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except Exception as e:
            print(f"Warning: Corrupted state file '{path}' ({e}). Falling back to clean state.", file=sys.stderr)
            return default_state

        if not isinstance(data, dict):
            print(f"Warning: State file '{path}' is not a JSON object. Falling back to clean state.", file=sys.stderr)
            return default_state

        # Schema compatibility: support discovered_facts / active_panes mapping
        known = data.get("known_facts") or data.get("discovered_facts") or {}
        lanes = data.get("lanes") or data.get("active_panes") or {}
        if not isinstance(lanes, dict):
            lanes = {}

        # Safe Phase parsing
        raw_phase = data.get("phase", Phase.INIT.value)
        try:
            phase = Phase(raw_phase)
        except ValueError:
            print(f"Warning: Unknown phase '{raw_phase}', defaulting to INIT.", file=sys.stderr)
            phase = Phase.INIT

        def _safe_int(val: Any, fallback: int) -> int:
            if val is None:
                return fallback
            try:
                return int(val)
            except (ValueError, TypeError):
                return fallback

        # Preserve extra metadata (e.g. worktrees, completed_milestones) so they are not dropped
        standard_keys = {
            "schema", "task_id", "phase", "review_round", "max_review_rounds",
            "lanes", "active_panes", "known_facts", "discovered_facts", "awaiting_human_gate"
        }
        extra = {k: v for k, v in data.items() if k not in standard_keys}

        return cls(
            schema=_safe_int(data.get("schema"), 2),
            task_id=str(data.get("task_id", "default")),
            phase=phase,
            review_round=_safe_int(data.get("review_round"), 0),
            max_review_rounds=_safe_int(data.get("max_review_rounds"), 2),
            lanes=lanes,
            known_facts=known if isinstance(known, dict) else {},
            awaiting_human_gate=bool(data.get("awaiting_human_gate", False)),
            extra_data=extra,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = asdict(self)
        raw["phase"] = self.phase.value
        extra = raw.pop("extra_data", {})
        raw.update(extra)
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def advance(self, target: Phase) -> None:
        allowed = VALID_TRANSITIONS.get(self.phase, [])
        if target not in allowed:
            raise StateTransitionError(
                f"Illegal state transition: cannot transition from '{self.phase.value}' to '{target.value}'. "
                f"Allowed transitions: {[p.value for p in allowed]}"
            )

        if target == Phase.SKEPTIC_REVIEW:
            if self.review_round >= self.max_review_rounds:
                raise StateTransitionError(
                    f"Review Convergence Ceiling reached! review_round={self.review_round} >= max={self.max_review_rounds}. "
                    "Cannot spawn another Skeptic session. Next permitted action MUST be 'awaiting_human_gate'."
                )
            self.review_round += 1

        self.phase = target
        self.awaiting_human_gate = (target == Phase.AWAITING_HUMAN_GATE)

    def next_action(self) -> Dict[str, Any]:
        if self.phase == Phase.INIT:
            return {
                "permitted_action": "dispatch_researcher_or_writer",
                "phase": self.phase.value,
                "review_round": self.review_round,
            }
        elif self.phase == Phase.RESEARCH:
            return {
                "permitted_action": "dispatch_writer",
                "phase": self.phase.value,
                "review_round": self.review_round,
            }
        elif self.phase == Phase.WRITER_IMPLEMENTATION:
            if self.review_round < self.max_review_rounds:
                return {
                    "permitted_action": "dispatch_skeptic_or_human_gate",
                    "phase": self.phase.value,
                    "review_round": self.review_round,
                }
            return {
                "permitted_action": "awaiting_human_gate",
                "reason": "Review Convergence Ceiling reached",
                "phase": self.phase.value,
                "review_round": self.review_round,
            }
        elif self.phase == Phase.SKEPTIC_REVIEW:
            return {
                "permitted_action": "harvest_skeptic_review",
                "phase": self.phase.value,
                "review_round": self.review_round,
            }
        elif self.phase == Phase.AWAITING_HUMAN_GATE:
            return {
                "permitted_action": "request_human_authorization",
                "actions": ["git push", "gh pr create", "gh pr merge", "worktree cleanup"],
                "phase": self.phase.value,
                "review_round": self.review_round,
            }
        elif self.phase == Phase.CLOSED:
            return {"permitted_action": "done", "phase": self.phase.value}
        return {"permitted_action": "unknown"}


def cmd_state(args: argparse.Namespace) -> int:
    state_file = resolve_state_file(args.repo)
    state = OrchestratorState.load(state_file)

    if args.state_op == "next":
        print(json.dumps(state.next_action(), ensure_ascii=False, indent=2))
        return 0
    elif args.state_op == "advance":
        if not args.to_phase:
            print("Error: --to-phase is required for 'advance'.", file=sys.stderr)
            return 1
        target = Phase(args.to_phase)
        try:
            state.advance(target)
            state.save(state_file)
            print(f"State successfully advanced to: {state.phase.value} (round={state.review_round})")
            return 0
        except StateTransitionError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    elif args.state_op == "set-facts":
        if not args.json:
            print("Error: --json is required for 'set-facts'.", file=sys.stderr)
            return 1
        try:
            payload = json.loads(args.json)
            if isinstance(payload, dict):
                state.known_facts.update(payload)
            state.save(state_file)
            print(f"Updated known_facts in '{state_file}'.")
            return 0
        except Exception as e:
            print(f"Error parsing --json: {e}", file=sys.stderr)
            return 1
    elif args.state_op == "reset":
        if not args.confirm:
            print("Error: Resetting state requires --confirm flag.", file=sys.stderr)
            return 1
        clean_state = OrchestratorState(
            schema=2,
            task_id="default",
            phase=Phase.INIT,
            review_round=0,
            max_review_rounds=2,
            lanes={},
            known_facts={},
            awaiting_human_gate=False,
        )
        clean_state.save(state_file)
        print(f"Orchestrator state reset to INIT in '{state_file}'.")
        return 0
    elif args.state_op == "show":
        raw = asdict(state)
        raw["phase"] = state.phase.value
        print(json.dumps(raw, ensure_ascii=False, indent=2))
        return 0
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    task_file = Path(args.task)
    try:
        lint_task_contract(task_file, allow_legacy=getattr(args, "allow_legacy", False))
        print(f"OK: Task contract '{task_file}' is valid.")
        return 0
    except TaskContractError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dispatch Automation Engine")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # State subcommands
    p_state = subparsers.add_parser("state", help="Manage orchestrator state machine")
    p_state.add_argument("state_op", choices=["next", "advance", "show", "set-facts", "reset"])
    p_state.add_argument("--repo", default=os.getcwd(), help="Target repository root")
    p_state.add_argument("--to-phase", choices=[p.value for p in Phase], help="Target phase for advance")
    p_state.add_argument("--json", help="JSON string for set-facts")
    p_state.add_argument("--confirm", action="store_true", help="Confirmation flag for reset")
    p_state.set_defaults(func=cmd_state)

    # Lint subcommand
    p_lint = subparsers.add_parser("lint", help="Lint a task contract file")
    p_lint.add_argument("task", help="Path to task file")
    p_lint.add_argument(
        "--allow-legacy",
        action="store_true",
        help="grandfather a contract that predates the Issue #125 toolchain clauses "
        "(warns loudly rather than passing silently)",
    )
    p_lint.set_defaults(func=cmd_lint)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
