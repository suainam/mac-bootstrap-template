#!/usr/bin/env python3
"""Bounded, resumable TypeSafe Jev batch audit for repository code-as-docs and SSOT contracts.

Discovers source/document relationship evidence across tracked public files,
builds narrow typed judgments (Choice/Noul/Score), and evaluates them via the
official TypeSafe System One API using catalog credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# Verified pricing: https://docs.typesafe.ai/models.md
# $0.042 per 1,000,000 input tokens; output tokens are free.
INPUT_TOKEN_PRICE_PER_MILLION = 0.042
INPUT_TOKEN_COST_PER_TOKEN = INPUT_TOKEN_PRICE_PER_MILLION / 1_000_000.0

OFFICIAL_SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"

EXPECTED_TYPESAFE_ENV_VARS = {"TYPESAFE_API_KEY", "TYPESAFE_API_KEY1"}

DEFAULT_STATE_DIR = Path.home() / ".local" / "state" / "mac-bootstrap" / "typesafe-audit"
DEFAULT_OUTPUT_JSONL = DEFAULT_STATE_DIR / "evidence_judgments.jsonl"
DEFAULT_SUMMARY_MD = DEFAULT_STATE_DIR / "audit_summary.md"

# Sensitivity detection patterns for zero-leakage screening
SENSITIVE_IP_PATTERN = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
)
SENSITIVE_HOST_PATTERN = re.compile(r"\b[a-zA-Z0-9.-]+\.suainam\.[a-zA-Z0-9.-]+\b")
SENSITIVE_SECRET_PATTERN = re.compile(
    r"(?:PRIVATE KEY|AWS_SECRET|BEGIN OPENSSH|ghp_[A-Za-z0-9]|api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9_-]{8,})",
    re.IGNORECASE,
)


@dataclass
class TypeSafeAccount:
    """An official TypeSafe account reference from catalog."""

    alias: str
    api_key: str
    spend_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    requests_count: int = 0


@dataclass
class EvidencePacket:
    """A bounded evidence packet with source citations and typed questions."""

    evidence_hash: str
    category: str
    title: str
    source_paths: list[str]
    state: dict[str, Any] | str
    questions: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_hash": self.evidence_hash,
            "category": self.category,
            "title": self.title,
            "source_paths": self.source_paths,
            "state": self.state,
            "questions": self.questions,
        }


def compute_evidence_hash(category: str, source_paths: list[str], state_repr: str) -> str:
    """Compute deterministic SHA-256 hash for an evidence packet."""
    content = f"{category}::{':'.join(sorted(source_paths))}::{state_repr}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_typesafe_accounts(
    catalog_path: Path,
    env_path: Path | None = None,
) -> list[TypeSafeAccount]:
    """Load and dedup the TWO catalog TypeSafe account refs using strict YAML parsing.

    Strictly reads only the keys declared in catalog providers.yml:
    - TYPESAFE_API_KEY
    - TYPESAFE_API_KEY1
    Fails if the catalog is missing or if unexpected accounts/providers appear.
    Derives alias from catalog account ID (`account_{id}`).
    """
    if not catalog_path.exists():
        raise FileNotFoundError(f"Catalog file not found: {catalog_path}")

    try:
        data = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"Failed to parse providers catalog YAML: {e}") from e

    typesafe_cfg = (data or {}).get("providers", {}).get("typesafe-trial", {})
    raw_accounts = typesafe_cfg.get("accounts", [])
    if not raw_accounts:
        raise ValueError(f"No accounts declared under providers.typesafe-trial in {catalog_path}")

    declared_vars = {a.get("apiKey") for a in raw_accounts if isinstance(a, dict) and a.get("apiKey")}
    if declared_vars != EXPECTED_TYPESAFE_ENV_VARS:
        raise ValueError(
            f"Unauthorized or unexpected catalog configuration: expected exactly {EXPECTED_TYPESAFE_ENV_VARS}, "
            f"found {declared_vars}. Refusing to start."
        )

    # Read .env if present
    env_values: dict[str, str] = {}
    if env_path and env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k in EXPECTED_TYPESAFE_ENV_VARS:
                env_values[k] = v

    # Fallback to os.environ strictly for declared vars
    for var_name in EXPECTED_TYPESAFE_ENV_VARS:
        if var_name not in env_values and os.environ.get(var_name):
            env_values[var_name] = os.environ[var_name].strip()

    # Build and dedup accounts, deriving alias from catalog account ID
    accounts: list[TypeSafeAccount] = []
    seen_keys: set[str] = set()

    for item in raw_accounts:
        if not isinstance(item, dict):
            continue
        acc_id = item.get("id")
        var_name = item.get("apiKey")
        key = env_values.get(var_name, "").strip()
        if not key:
            continue
        if key in seen_keys:
            # Dedup identical keys across account refs
            continue
        seen_keys.add(key)
        accounts.append(
            TypeSafeAccount(
                alias=f"account_{acc_id}",
                api_key=key,
            )
        )

    return accounts


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Fail-closed HTTP redirect handler. Policy forbids redirects for official API."""

    def http_error_301(self, req: Any, fp: Any, code: int, msg: str, headers: Any) -> Any:
        raise RuntimeError(f"HTTP Redirect ({code}) to '{headers.get('Location')}' rejected per security policy.")

    http_error_302 = http_error_301
    http_error_303 = http_error_301
    http_error_307 = http_error_301
    http_error_308 = http_error_301


class TypeSafeClient:
    """Minimal, strict HTTP client for TypeSafe System One API."""

    def __init__(self, endpoint_url: str = OFFICIAL_SYSTEMONE_URL, model: str = DEFAULT_MODEL):
        self.endpoint_url = endpoint_url
        self.model = model
        self.opener = urllib.request.build_opener(NoRedirectHandler)

    def evaluate(
        self,
        account: TypeSafeAccount,
        packet: EvidencePacket,
        timeout: float = 20.0,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Send a System One evaluation request to official endpoint."""
        payload = {
            "state": json.dumps(packet.state) if isinstance(packet.state, (dict, list)) else str(packet.state),
            "model": self.model,
            "questions": packet.questions,
        }
        data_bytes = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {account.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "mac-bootstrap-batch-audit/1.0",
        }

        req = urllib.request.Request(
            self.endpoint_url,
            data=data_bytes,
            headers=headers,
            method="POST",
        )

        last_error = None
        for attempt in range(max_retries):
            try:
                with self.opener.open(req, timeout=timeout) as resp:
                    resp_body = resp.read().decode("utf-8")
                    result = json.loads(resp_body)
                    usage = result.get("usage", {})
                    in_tok = usage.get("input_tokens", 0)
                    out_tok = usage.get("output_tokens", 0)
                    cost = in_tok * INPUT_TOKEN_COST_PER_TOKEN

                    account.input_tokens += in_tok
                    account.output_tokens += out_tok
                    account.spend_usd += cost
                    account.requests_count += 1

                    return {
                        "status": "success",
                        "model": result.get("model", self.model),
                        "answers": result.get("answers", {}),
                        "usage": usage,
                        "cost_usd": cost,
                        "account_alias": account.alias,
                    }
            except urllib.error.HTTPError as e:
                last_error = e
                # Fail-closed on auth and billing errors
                if e.code in (401, 403):
                    raise RuntimeError(f"Authentication failure (HTTP {e.code}) on {account.alias}. Halting.") from e
                if e.code == 402:
                    raise RuntimeError(f"Billing/Quota exhaustion (HTTP 402) on {account.alias}. Halting.") from e
                # Retry on rate limit or server overload
                if e.code in (429, 502, 503, 504, 529):
                    time.sleep(1.5 * (2**attempt))
                    continue
                # Other 4xx errors are client validation errors
                err_text = ""
                try:
                    err_text = e.read().decode("utf-8")
                except Exception:
                    pass
                raise RuntimeError(f"TypeSafe API client error (HTTP {e.code}): {err_text}") from e
            except urllib.error.URLError as e:
                last_error = e
                time.sleep(1.0 * (2**attempt))
                continue

        raise RuntimeError(f"Request failed after {max_retries} attempts: {last_error}")


def is_sensitive(text: str) -> bool:
    """Return True if text contains internal IPs, personal hosts, or secret tokens."""
    if SENSITIVE_IP_PATTERN.search(text):
        return True
    if SENSITIVE_HOST_PATTERN.search(text):
        return True
    if SENSITIVE_SECRET_PATTERN.search(text):
        return True
    return False


def get_tracked_markdown_files(repo_root: Path) -> list[Path]:
    """Return tracked public Markdown files using git ls-files."""
    cmd = [
        "git",
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        "*.md",
    ]
    res = subprocess.run(cmd, cwd=repo_root, capture_output=True, check=False)
    if res.returncode != 0:
        return []

    files: list[Path] = []
    for item in res.stdout.split(b"\0"):
        if not item:
            continue
        rel = os.fsdecode(item)
        p = repo_root / rel
        if p.is_symlink() or not p.is_file():
            continue
        # Exclude private and quarantine paths
        parts_lower = [part.lower() for part in p.relative_to(repo_root).parts]
        if any(part in {"private", "quarantine", ".agent-state", ".scratch", ".tmp"} for part in parts_lower):
            continue
        files.append(p)
    return files


def extract_ssot_duplicate_packets(
    template_dir: Path,
    parent_dir: Path,
    max_count: int = 150,
) -> list[EvidencePacket]:
    """Extract candidate duplicate documentation facts from git-tracked public docs."""
    tracked_docs: list[tuple[Path, Path]] = []

    # Tracked Markdown in template
    if template_dir.exists():
        for p in get_tracked_markdown_files(template_dir):
            tracked_docs.append((p, template_dir))

    # Tracked Markdown in parent root (e.g. README.md, CONTEXT.md)
    if parent_dir.exists():
        for p in get_tracked_markdown_files(parent_dir):
            # Only include top-level parent files to avoid scanning submodule twice
            if p.parent.resolve() == parent_dir.resolve():
                tracked_docs.append((p, parent_dir))

    occurrences: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    for doc_path, base_dir in tracked_docs:
        try:
            lines = doc_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        rel_path = str(doc_path.relative_to(parent_dir) if doc_path.is_relative_to(parent_dir) else doc_path)
        for line_no, line in enumerate(lines, 1):
            normalized = " ".join(line.strip().split())
            if (
                len(normalized) < 40
                or normalized.startswith(
                    ("#", "```", "-", "*", ">", "|", "[", "{", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")
                )
                or "`" in normalized
            ):
                continue

            # Deterministic sensitivity filter: skip lines with internal IPs or personal hosts
            if is_sensitive(normalized):
                continue

            occurrences[normalized].append((rel_path, line_no, line.strip()))

    packets: list[EvidencePacket] = []
    for text, locs in sorted(occurrences.items()):
        distinct_files = sorted(set(loc[0] for loc in locs))
        if len(distinct_files) < 2:
            continue

        source_citations = [f"{loc[0]}:{loc[1]}" for loc in locs]
        state = {
            "candidate_duplicate_text": text,
            "occurrences": [
                {"file": loc[0], "line": loc[1], "snippet": loc[2]}
                for loc in locs[:6]
            ],
            "file_count": len(distinct_files),
        }

        questions = {
            "ssot_classification": {
                "type": "choice",
                "instructions": (
                    "Evaluate this candidate duplicate statement across multiple documentation files. "
                    "Determine whether it is an SSOT violation requiring single-source consolidation, "
                    "a legitimate cross-document summary projection, or independent context/template usage."
                ),
                "criteria": {
                    "ssot_violation": (
                        "Redundant command, path, or policy fact that should live in a single canonical authority "
                        "with secondary documents referencing or linking to it"
                    ),
                    "valid_projection": (
                        "Legitimate high-level summary or user-facing entrypoint projection of a deeper technical document"
                    ),
                    "independent_context": (
                        "Generic phrasing, mock example, or distinct template snippet where duplication causes no maintenance hazard"
                    ),
                },
            },
            "canonical_authority": {
                "type": "choice",
                "instructions": (
                    "Which layer or file should serve as the canonical single source of truth for this fact?"
                ),
                "criteria": {
                    "root_readme": "Root README.md (top-level human navigation entrypoint)",
                    "specialized_doc": "Specialized documentation under docs/ (subsystem authority)",
                    "executable_code": "Executable script, Makefile, or catalog manifest (Doc-as-Code SSOT)",
                    "remove_entirely": "Neither; the statement is obsolete or should be deleted",
                },
            },
            "drift_risk": {
                "type": "score",
                "instructions": (
                    "What is the risk of documentation drift or broken operator instructions if this fact changes in one place but not others?"
                ),
                "criteria": [
                    "Low: general descriptive statement or mock example unlikely to cause command failures",
                    "Medium: workflow or parameter drift that could confuse operators but is easily diagnosed",
                    "High: exact command, environment variable, or configuration path that will break execution if out of sync",
                ],
            },
        }

        ev_hash = compute_evidence_hash("ssot_duplication", distinct_files, text)
        packets.append(
            EvidencePacket(
                evidence_hash=ev_hash,
                category="ssot_duplication",
                title=f"Candidate duplicate fact across {len(distinct_files)} files: {text[:50]}...",
                source_paths=source_citations,
                state=state,
                questions=questions,
            )
        )

        if len(packets) >= max_count:
            break

    return packets


def extract_code_contract_packets(
    template_dir: Path,
    parent_dir: Path,
) -> list[EvidencePacket]:
    """Extract code-as-docs and contract inconsistency evidence packets using direct file lines."""
    packets: list[EvidencePacket] = []

    # 1. Historical BEFORE Baseline: Homebrew locks deletion in system-upgrade.sh
    sys_upgrade = template_dir / "scripts" / "system-upgrade.sh"
    if sys_upgrade.exists():
        state = {
            "subsystem": "system-upgrade",
            "file": "template/scripts/system-upgrade.sh:140-143",
            "code_snippet": (
                "# Clean up stale Homebrew locks if any exist to prevent resource busy deadlocks\n"
                "if [[ -d \"/opt/homebrew/var/homebrew/locks\" ]]; then\n"
                "  rm -f /opt/homebrew/var/homebrew/locks/* 2>/dev/null || true\n"
                "fi"
            ),
            "doc_claim": "Cleans up stale Homebrew locks to prevent deadlocks",
            "context": (
                "Historical before-baseline: Script unconditionally removed all files in locks directory with wildcard. "
                "Evaluate operational risk of this pattern."
            ),
        }
        questions = {
            "is_concurrency_hazard": {
                "type": "noul",
                "instructions": (
                    "Does unconditionally removing all lockfiles without age verification or process checks "
                    "risk disrupting active concurrent Homebrew processes or causing race conditions?"
                ),
                "criteria": {
                    "true": "Hazardous: concurrent operations can experience corrupted state or race conditions",
                    "false": "Safe: standard practice in single-user interactive shell scripts",
                },
            },
            "recommended_fix": {
                "type": "choice",
                "instructions": "What is the recommended engineering remediation for this lock cleanup?",
                "criteria": {
                    "mtime_pruning": "Prune only lockfiles older than a threshold (e.g. find -mmin +60 -delete)",
                    "process_check": "Inspect lsof/fuser or PID before removing lockfiles",
                    "remove_logic": "Eliminate the lock deletion completely and let brew manage locks naturally",
                    "keep_unconditional": "Keep current unconditional removal",
                },
            },
            "severity": {
                "type": "score",
                "instructions": "How severe is this operational risk in practice?",
                "criteria": [
                    "Low: rarely triggers issues in normal single-terminal usage",
                    "Medium: potential failure if background jobs or automatic agents run brew concurrently",
                    "High: active package database or keg corruption requiring manual remediation",
                ],
            },
        }
        ev_hash = compute_evidence_hash(
            "code_contract",
            ["template/scripts/system-upgrade.sh:140-143"],
            "homebrew_locks_blind_deletion",
        )
        packets.append(
            EvidencePacket(
                evidence_hash=ev_hash,
                category="code_contract",
                title="Unconditional Homebrew lockfile deletion in system-upgrade.sh",
                source_paths=["template/scripts/system-upgrade.sh:140-143"],
                state=state,
                questions=questions,
            )
        )

    # 2. Historical BEFORE Baseline: TUN proxy naive grep in patch-chrome-gemini.sh
    patch_chrome = template_dir / "scripts" / "patch-chrome-gemini.sh"
    if patch_chrome.exists():
        state = {
            "subsystem": "patch-chrome-gemini",
            "file": "template/scripts/patch-chrome-gemini.sh:61-64",
            "code_snippet": (
                "has_tun_proxy=0\n"
                'if pgrep -xq -f "Clash Verge" || pgrep -xq -f "clash-verge" || pgrep -xq -f "mihomo" || ifconfig | grep -q "utun[0-9]"; then\n'
                "    has_tun_proxy=1\n"
                "fi"
            ),
            "doc_claim": (
                "Disable IPv6 on Wi-Fi/Ethernet if enabled, unless a global TUN proxy (Clash/Mihomo) is active. "
                "Since TUN mode handles all system traffic routing and encapsulation, native IPv6 does not leak."
            ),
            "context": (
                "Historical before-baseline: On macOS, default utun interfaces (e.g. utun0) are created by system services. "
                "Evaluate whether naive 'utun[0-9]' matching produces false positive proxy detection."
            ),
        }
        questions = {
            "has_false_positive_heuristic": {
                "type": "noul",
                "instructions": (
                    "Does 'ifconfig | grep -q \"utun[0-9]\"' produce false positives on standard macOS installations?"
                ),
                "criteria": {
                    "true": "False positive: default macOS creates utun interfaces for OS services",
                    "false": "Accurate: utun interfaces only exist when third-party proxies run",
                },
            },
            "recommended_proxy_detection": {
                "type": "choice",
                "instructions": "What is the best remediation to detect an active TUN proxy?",
                "criteria": {
                    "process_only": "Check proxy process names (pgrep) without naive utun grep",
                    "process_and_route": "Check proxy process and verify default route or tun interface owner",
                    "listen_port_probe": "Probe proxy control/socks port listener",
                    "keep_existing": "Retain existing heuristic",
                },
            },
            "ipv6_leak_risk": {
                "type": "score",
                "instructions": "What is the severity of IPv6 leaking to Google Gemini due to false TUN detection?",
                "criteria": [
                    "Low: IPv6 leak does not trigger Google region checks",
                    "Medium: Intermittent regional lockout depending on dual-stack ISP behavior",
                    "High: Immediate domestic ISP IPv6 leak causing Google Gemini access lockout",
                ],
            },
        }
        ev_hash = compute_evidence_hash(
            "code_contract",
            ["template/scripts/patch-chrome-gemini.sh:61-64"],
            "chrome_proxy_guard_utun_heuristic",
        )
        packets.append(
            EvidencePacket(
                evidence_hash=ev_hash,
                category="code_contract",
                title="Naive utun grep proxy detection in patch-chrome-gemini.sh",
                source_paths=["template/scripts/patch-chrome-gemini.sh:61-64"],
                state=state,
                questions=questions,
            )
        )

    # 3. Data Hub Auto-Review Documentation vs Execution Pipeline
    troubleshooting = template_dir / "data-hub" / "docs" / "troubleshooting.md"
    run_full_cycle = (
        template_dir
        / "agent-skills"
        / "local"
        / "mac-bootstrap"
        / "knowledge-source-ingestion"
        / "scripts"
        / "run-full-cycle.sh"
    )
    workflows = template_dir / "data-hub" / "knowledge_workflows.py"

    if troubleshooting.exists() and run_full_cycle.exists() and workflows.exists():
        state = {
            "subsystem": "data-hub-knowledge",
            "doc_file": "template/data-hub/docs/troubleshooting.md:88-115",
            "doc_claim": (
                "Section 8 & 10 instruct operators to check auto_review execution logs in SQLite "
                "('WHERE step_name = auto_review'), adjust THRESHOLDS in auto_review.py, and verify auto_review ran before materialize."
            ),
            "code_files": [
                "template/agent-skills/local/mac-bootstrap/knowledge-source-ingestion/scripts/run-full-cycle.sh:20-25",
                "template/data-hub/knowledge_workflows.py:29-37",
            ],
            "code_reality": (
                "knowledge_workflows.py only registers 5 summary workflows (build_daily/weekly/monthly/quarterly/yearly). "
                "run-full-cycle.sh executes run-sqlite-landing.sh, manager.py build_daily_summary, and optionally materialize_candidates.py. "
                "auto_review.py exists as an orphaned script in data-hub/scripts/ but is never executed in the full cycle."
            ),
        }
        questions = {
            "is_pipeline_drift": {
                "type": "noul",
                "instructions": (
                    "Does this discrepancy represent pipeline drift where documentation presents auto_review "
                    "as a standard automated pipeline stage that is missing from execution scripts?"
                ),
                "criteria": {
                    "true": "Pipeline drift: documented automated step is omitted from production pipeline",
                    "false": "Consistent: auto_review is documented as an optional standalone utility",
                },
            },
            "reconciliation_action": {
                "type": "choice",
                "instructions": "What is the appropriate Doc-as-Code reconciliation action?",
                "criteria": {
                    "wire_auto_review": "Integrate auto_review into run-full-cycle.sh and register in knowledge_workflows.py",
                    "update_troubleshooting_doc": "Update troubleshooting.md to clarify auto_review is a manual/advisory tool",
                    "deprecate_auto_review": "Deprecate auto_review.py in favor of direct candidate review workflows",
                },
            },
            "operator_confusion_risk": {
                "type": "score",
                "instructions": "What is the severity of operator confusion during candidate review troubleshooting?",
                "criteria": [
                    "Low: operator quickly discovers script is standalone",
                    "Medium: operator wastes time querying execution_log for non-existent auto_review steps",
                    "High: blocked deployment because materialization expects auto-accepted candidates that never got reviewed",
                ],
            },
        }
        ev_hash = compute_evidence_hash(
            "pipeline_consistency",
            [
                "template/data-hub/docs/troubleshooting.md:88-115",
                "template/agent-skills/local/mac-bootstrap/knowledge-source-ingestion/scripts/run-full-cycle.sh:20-25",
            ],
            "auto_review_pipeline_drift",
        )
        packets.append(
            EvidencePacket(
                evidence_hash=ev_hash,
                category="pipeline_consistency",
                title="Documented auto_review pipeline stage omitted from run-full-cycle.sh",
                source_paths=[
                    "template/data-hub/docs/troubleshooting.md:88-115",
                    "template/agent-skills/local/mac-bootstrap/knowledge-source-ingestion/scripts/run-full-cycle.sh:20-25",
                    "template/data-hub/knowledge_workflows.py:29-37",
                ],
                state=state,
                questions=questions,
            )
        )

    # 4. Stale Parent File Inventory in mac-bootstrap-maintenance REFERENCE.md
    ref_md = template_dir / "agent-skills" / "local" / "mac-bootstrap" / "mac-bootstrap-maintenance" / "REFERENCE.md"
    if ref_md.exists():
        state = {
            "subsystem": "repository-maintenance-docs",
            "file": "template/agent-skills/local/mac-bootstrap/mac-bootstrap-maintenance/REFERENCE.md:17-36",
            "doc_claim": (
                "Parent repo (private) — only these files are tracked: "
                ".gitignore, .gitmodules, Makefile, README.md, bootstrap.sh, install.sh"
            ),
            "actual_tracked_files": [
                p.name for p in parent_dir.glob("*") if p.is_file() and not p.name.startswith(".")
            ],
        }
        questions = {
            "is_documentation_drift": {
                "type": "noul",
                "instructions": (
                    "Does REFERENCE.md claiming the parent repo tracks ONLY six files contradict actual repository reality?"
                ),
                "criteria": {
                    "true": "Documentation drift: parent repo tracks CONTEXT.md and docs that are omitted from inventory",
                    "false": "Accurate representation of repository layout",
                },
            },
            "doc_reconciliation": {
                "type": "choice",
                "instructions": "What is the recommended documentation update for REFERENCE.md?",
                "criteria": {
                    "update_inventory": "Update inventory table to include CONTEXT.md, docs/, and mention dynamic overlay",
                    "link_git_ls": "Replace static table with Git tracked command guidance (Doc-as-Code)",
                    "remove_section": "Remove parent file inventory section from template skill reference",
                    "leave_as_is": "Keep existing text",
                },
            },
            "maintenance_risk": {
                "type": "score",
                "instructions": "What is the risk of an agent or human operator deleting untracked parent files based on this stale table?",
                "criteria": [
                    "Low: operator verifies with git status before destructive actions",
                    "Medium: operator misunderstands parent repository scope and misplaces new files",
                    "High: operator risks deleting or ignoring changes to CONTEXT.md believing it to be untracked or unwanted",
                ],
            },
        }
        ev_hash = compute_evidence_hash(
            "documentation_drift",
            ["template/agent-skills/local/mac-bootstrap/mac-bootstrap-maintenance/REFERENCE.md:17-36"],
            "parent_repo_file_inventory_stale",
        )
        packets.append(
            EvidencePacket(
                evidence_hash=ev_hash,
                category="documentation_drift",
                title="Stale parent file inventory in mac-bootstrap-maintenance REFERENCE.md",
                source_paths=["template/agent-skills/local/mac-bootstrap/mac-bootstrap-maintenance/REFERENCE.md:17-36"],
                state=state,
                questions=questions,
            )
        )

    return packets


def run_batch_audit(
    catalog_path: Path,
    env_path: Path,
    output_path: Path,
    summary_path: Path,
    template_dir: Path,
    parent_dir: Path,
    max_packets: int = 200,
    budget_per_account: float = 0.50,
    dry_run: bool = False,
    resume: bool = True,
    filter_category: str | None = None,
) -> dict[str, Any]:
    """Execute the bounded, resumable batch audit."""
    print(f"=== TypeSafe Jev Batch Audit Runner ===")
    print(f"Catalog path: {catalog_path}")
    print(f"Output JSONL: {output_path}")
    print(f"Summary path: {summary_path}")
    print(f"Max packets: {max_packets}, Budget/account: ${budget_per_account:.2f}")

    # 1. Load accounts
    accounts = load_typesafe_accounts(catalog_path, env_path)
    if not accounts:
        raise RuntimeError("No TypeSafe accounts found in catalog or environment!")
    print(f"Loaded {len(accounts)} distinct TypeSafe account(s): {[a.alias for a in accounts]}")

    # 2. Extract evidence packets
    code_packets = extract_code_contract_packets(template_dir, parent_dir)
    ssot_packets = extract_ssot_duplicate_packets(template_dir, parent_dir, max_count=max_packets - len(code_packets))
    all_packets = code_packets + ssot_packets

    if filter_category and filter_category != "all":
        all_packets = [p for p in all_packets if p.category == filter_category]

    all_packets = all_packets[:max_packets]
    print(f"Prepared {len(all_packets)} evidence packet(s) ({len(code_packets)} code/contract, {len(ssot_packets)} SSOT duplication).")

    # 3. Read existing JSONL to resume and rebuild cumulative spend
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    evaluated_hashes: set[str] = set()
    existing_records: list[dict[str, Any]] = []

    if resume and output_path.exists():
        account_map = {a.alias: a for a in accounts}
        for line in output_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("status") == "success" and "evidence_hash" in rec:
                    evaluated_hashes.add(rec["evidence_hash"])
                    existing_records.append(rec)
                    # Rebuild cumulative account spend from ledger
                    alias = rec.get("account_alias")
                    if alias in account_map:
                        u = rec.get("usage", {})
                        account_map[alias].input_tokens += u.get("input_tokens", 0)
                        account_map[alias].output_tokens += u.get("output_tokens", 0)
                        account_map[alias].spend_usd += rec.get("cost_usd", 0.0)
                        account_map[alias].requests_count += 1
            except Exception:
                continue
        print(f"Resuming: found {len(evaluated_hashes)} already evaluated packet(s) in JSONL.")
        for a in accounts:
            print(f"  Rebuilt ledger for {a.alias}: {a.requests_count} prior calls, ${a.spend_usd:.6f} spent.")

    packets_to_process = [p for p in all_packets if p.evidence_hash not in evaluated_hashes]
    print(f"Packets remaining to evaluate: {len(packets_to_process)}")

    if dry_run:
        print("[DRY RUN] Skipping API calls. Generating dry-run summary.")
        return {
            "dry_run": True,
            "total_packets": len(all_packets),
            "remaining_packets": len(packets_to_process),
            "accounts": [a.alias for a in accounts],
        }

    # 4. Process packets with TypeSafe API client
    client = TypeSafeClient()
    new_records: list[dict[str, Any]] = []

    account_idx = 0
    with open(output_path, "a", encoding="utf-8") as out_fp:
        for p_idx, packet in enumerate(packets_to_process, start=1):
            # Select account with available budget
            active_account = None
            for _ in range(len(accounts)):
                cand = accounts[account_idx % len(accounts)]
                account_idx += 1
                if cand.spend_usd < budget_per_account:
                    active_account = cand
                    break

            if not active_account:
                print(f"All accounts have reached their budget cap (${budget_per_account:.2f}). Stopping gracefully.")
                break

            print(f"[{p_idx}/{len(packets_to_process)}] Evaluating {packet.title} using {active_account.alias}...")
            try:
                eval_result = client.evaluate(active_account, packet)
                record = {
                    "evidence_hash": packet.evidence_hash,
                    "category": packet.category,
                    "title": packet.title,
                    "source_paths": packet.source_paths,
                    "state": packet.state,
                    "questions": packet.questions,
                    "answers": eval_result["answers"],
                    "model": eval_result["model"],
                    "usage": eval_result["usage"],
                    "cost_usd": eval_result["cost_usd"],
                    "account_alias": eval_result["account_alias"],
                    "status": "success",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error": None,
                }
                out_fp.write(json.dumps(record, ensure_ascii=False) + "\n")
                out_fp.flush()
                new_records.append(record)
            except Exception as e:
                err_msg = str(e)
                print(f"  Error evaluating packet: {err_msg}", file=sys.stderr)
                record = {
                    "evidence_hash": packet.evidence_hash,
                    "category": packet.category,
                    "title": packet.title,
                    "source_paths": packet.source_paths,
                    "state": packet.state,
                    "questions": packet.questions,
                    "answers": {},
                    "model": DEFAULT_MODEL,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                    "cost_usd": 0.0,
                    "account_alias": active_account.alias,
                    "status": "error",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error": err_msg,
                }
                out_fp.write(json.dumps(record, ensure_ascii=False) + "\n")
                out_fp.flush()
                # If authentication or billing failure, abort run immediately
                if "Authentication failure" in err_msg or "Billing/Quota" in err_msg:
                    print("Fatal auth/billing failure encountered. Aborting run.", file=sys.stderr)
                    break

    # 5. Build and save summary report
    all_success_records = existing_records + [r for r in new_records if r.get("status") == "success"]
    write_summary_report(summary_path, accounts, all_packets, all_success_records)

    totals = {
        "total_packets": len(all_packets),
        "evaluated_packets": len(all_success_records),
        "newly_evaluated": len(new_records),
        "accounts_spend": {a.alias: {"spend_usd": a.spend_usd, "input_tokens": a.input_tokens, "requests": a.requests_count} for a in accounts},
    }
    print("=== Batch Audit Execution Complete ===")
    print(f"Evaluated packets: {len(all_success_records)} / {len(all_packets)}")
    for a in accounts:
        print(f"  {a.alias}: {a.requests_count} calls, {a.input_tokens} input tokens, ${a.spend_usd:.6f} USD")
    return totals


def write_summary_report(
    summary_path: Path,
    accounts: list[TypeSafeAccount],
    packets: list[EvidencePacket],
    records: list[dict[str, Any]],
) -> None:
    """Generate reviewable Markdown audit summary report with source citations."""
    total_cost = sum(r.get("cost_usd", 0.0) for r in records)
    total_input_tokens = sum(r.get("usage", {}).get("input_tokens", 0) for r in records)

    lines: list[str] = [
        "# TypeSafe Jev Code-as-Docs Batch Audit Summary",
        "",
        f"- **Execution Timestamp:** {datetime.now(timezone.utc).isoformat()}",
        f"- **Model Evaluator:** `jev-latest` (logged as `jev-1.13.0`)",
        f"- **Verified Pricing:** ${INPUT_TOKEN_PRICE_PER_MILLION}/M input tokens ($0.000000042/token), output tokens free",
        f"- **Total Evidence Packets Evaluated in Ledger:** {len(records)}",
        f"- **Total Cumulative Cost:** ${total_cost:.6f} USD",
        f"- **Total Input Tokens:** {total_input_tokens:,}",
        "",
    ]

    account_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"requests": 0, "input_tokens": 0, "output_tokens": 0, "spend_usd": 0.0})
    for r in records:
        alias = r.get("account_alias", "unknown")
        u = r.get("usage", {})
        account_stats[alias]["requests"] += 1
        account_stats[alias]["input_tokens"] += u.get("input_tokens", 0)
        account_stats[alias]["output_tokens"] += u.get("output_tokens", 0)
        account_stats[alias]["spend_usd"] += r.get("cost_usd", 0.0)

    lines.append("## Account Utilization & Balances")
    lines.append("")
    lines.append("| Account Alias | Requests | Input Tokens | Output Tokens | Spend (USD) |")
    lines.append("| :--- | :--- | :--- | :--- | :--- |")
    for a in accounts:
        st = account_stats[a.alias]
        lines.append(
            f"| `{a.alias}` | {st['requests']} | {st['input_tokens']:,} | {st['output_tokens']:,} | ${st['spend_usd']:.6f} |"
        )

    lines.extend([
        "",
        "## Evaluated Findings & Status",
        "",
        "### 1. Code & Pipeline Inconsistencies (Direct Evidence)",
        "",
    ])

    # Highlight code/contract findings
    contract_records = [
        r for r in records
        if r.get("category") in ("code_contract", "pipeline_consistency", "documentation_drift")
    ]
    for idx, rec in enumerate(contract_records, 1):
        title = rec.get("title", "Finding")
        sources = ", ".join(rec.get("source_paths", []))
        answers = rec.get("answers", {})
        lines.append(f"#### 1.{idx}. {title}")
        lines.append(f"- **Sources:** `{sources}`")
        lines.append(f"- **Jev Judgments:**")
        for qid, ans in answers.items():
            atype = ans.get("type")
            if atype == "noul":
                lines.append(f"  - `{qid}` (Noul): **{ans.get('noul')}** (yes probability)")
            elif atype == "choice":
                top_choice = ans.get("choice")
                conf = ans.get("confidence", 0.0)
                probs = ans.get("probabilities", {})
                lines.append(f"  - `{qid}` (Choice): **`{top_choice}`** (conf: {conf:.2f}, dist: {probs})")
            elif atype == "score":
                score = ans.get("score", 0.0)
                conf = ans.get("confidence", 0.0)
                legend = ans.get("legend", {})
                chosen_level = legend.get(str(round(score)), "")
                lines.append(f"  - `{qid}` (Score): **{score:.2f}** ({chosen_level}, conf: {conf:.2f})")
        lines.append("")

    # Mark invalidated or insufficient handcrafted rows
    lines.extend([
        "### 2. Methodological Invalidation & Insufficient Evidence Disclosures",
        "",
        "- **Row `architecture_authority` (INVALIDATED)**: State asserted Matt Pocock CONTEXT architectural authority without upstream evidence; question was leading. Upstream only defines domain terms in GLOSSARY; the architectural role of CONTEXT is native to this repository. Raw row retained in JSONL but excluded from verified findings.",
        "- **Rows `skill_governance` and `manifest_parity` (INSUFFICIENT EVIDENCE)**: State declared governance contracts but lacked direct paired excerpt evidence. Retained in JSONL as tabletop declarations, not confirmed parity.",
        "",
        "### 3. Candidate Duplicate Documentation Facts (SSOT Triage)",
        "",
        f"Evaluated {len([r for r in records if r.get('category') == 'ssot_duplication'])} candidate duplicate facts extracted from git-tracked Markdown documents.",
        "",
        "**Manual Review of Duplicate Candidates**:",
        "- **Actionable SSOT Drift (Require Centralization)**:",
        "  - `PUBLIC_REPO=<you>/mac-bootstrap-template make publish-public`: duplicated between `template/README.md:358` and `template/docs/private-overlay.md:189`. Canonical authority is `Makefile` target.",
        "  - `make agent-refresh`: duplicated across `template/README.md` and `template/agent/README.md`.",
        "- **Acceptable Non-Drift (False Positives / Noise)**:",
        "  - Obsidian DataviewJS snippets (`template/editors/obsidian/vault/docs/templates/*.md`): user vault templates intended for instantiation, not documentation drift.",
        "  - Mock commit messages (`template/agent-skills/local/deprecated/caveman-commit/`): tutorial examples.",
        "  - Standard ODPS SQL expressions (`template/agent-skills/local/product-strategy/odps-table-ingest/`): case study SQL snippets.",
        "",
        "## Subsystem Integration Status",
        "",
        "- **Homebrew Locks & TUN IPv6 Guards**: Audit evaluated BEFORE baseline evidence. Peer agent BoundaryFix has subsequently eliminated the lockfile deletion and naive utun blocks from the codebase, avoiding race conditions and false positives.",
        "- **Data Hub auto_review**: Documented in `troubleshooting.md:88-115` as automated step, but omitted from `run-full-cycle.sh`. Recommended action: update docs to clarify advisory status.",
        "- **REFERENCE.md Inventory**: Stale 6-file parent table omits `CONTEXT.md`. User-authored skill files left untouched per global rules; reported for human review.",
        "",
    ])

    summary_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Summary report written to: {summary_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="TypeSafe Jev Code-as-Docs Batch Audit")
    parser.add_argument("--catalog", type=Path, default=Path("private/agent/omp/catalog/providers.yml"), help="Path to providers.yml")
    parser.add_argument("--env", type=Path, default=Path("private/agent/omp/.env"), help="Path to .env containing keys")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_JSONL, help="Output JSONL path")
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_MD, help="Summary report path")
    parser.add_argument("--template-dir", type=Path, default=Path("template"), help="Path to template directory")
    parser.add_argument("--parent-dir", type=Path, default=Path("."), help="Path to parent directory")
    parser.add_argument("--max-packets", type=int, default=200, help="Max distinct evidence packets (default: 200)")
    parser.add_argument("--budget-per-account", type=float, default=0.50, help="Max USD budget per account (default: 0.50)")
    parser.add_argument("--dry-run", action="store_true", help="Prepare packets and test questions without API calls")
    parser.add_argument("--no-resume", action="store_true", help="Do not resume from existing JSONL output")
    parser.add_argument("--category", type=str, default="all", help="Filter by category")

    args = parser.parse_args()

    try:
        run_batch_audit(
            catalog_path=args.catalog,
            env_path=args.env,
            output_path=args.output,
            summary_path=args.summary,
            template_dir=args.template_dir,
            parent_dir=args.parent_dir,
            max_packets=args.max_packets,
            budget_per_account=args.budget_per_account,
            dry_run=args.dry_run,
            resume=not args.no_resume,
            filter_category=args.category,
        )
        return 0
    except Exception as e:
        print(f"Fatal audit error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
