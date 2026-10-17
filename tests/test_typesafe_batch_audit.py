"""Unit tests for TypeSafe Jev batch audit runner."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

TESTS_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = TESTS_DIR.parent
SCRIPTS_DIR = TEMPLATE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(TEMPLATE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(TEMPLATE_DIR.parent))

from typesafe_batch_audit import (
    INPUT_TOKEN_COST_PER_TOKEN,
    INPUT_TOKEN_PRICE_PER_MILLION,
    NoRedirectHandler,
    TypeSafeAccount,
    compute_evidence_hash,
    extract_code_contract_packets,
    is_sensitive,
    load_typesafe_accounts,
)


def test_pricing_constants():
    """Verify official verified pricing rate."""
    assert INPUT_TOKEN_PRICE_PER_MILLION == 0.042
    assert abs(INPUT_TOKEN_COST_PER_TOKEN - 0.000000042) < 1e-12


def test_sensitivity_screening_filter():
    """Verify that private IPs, internal hosts, and secrets are caught by sensitivity filter."""
    assert is_sensitive("Connect to https://10.0.103.217:59443/_static")
    assert is_sensitive("curl -fsSL https://s.suainam.eu.org/clash")
    assert is_sensitive("export API_KEY='sk-1234567890abcdef'")
    assert not is_sensitive("make check-all")
    assert not is_sensitive("git status --short")


def test_no_redirect_handler_rejects_redirects():
    """Verify that HTTP 3xx redirects are rejected fail-closed per security policy."""
    handler = NoRedirectHandler()
    with pytest.raises(RuntimeError, match="HTTP Redirect.*rejected"):
        handler.http_error_301(None, None, 301, "Moved Permanently", {"Location": "https://evil.com"})


def test_load_typesafe_accounts_strictly_ignores_openrouter_sibling(tmp_path: Path):
    """Verify that YAML parser strictly isolates typesafe-trial and ignores sibling providers like openrouter-judge."""
    catalog_content = """
providers:
  typesafe-trial:
    baseUrl: https://api.typesafe.ai
    api: typesafe
    authHeader: true
    accounts:
      - id: 1
        apiKey: TYPESAFE_API_KEY
      - id: 2
        apiKey: TYPESAFE_API_KEY1
    models:
      - id: jev-latest
  openrouter-judge:
    baseUrl: https://openrouter.ai/api/alpha
    api: openrouter-decisions
    apiKey: OPENROUTER_API_KEY
    authHeader: true
"""
    catalog_file = tmp_path / "providers.yml"
    catalog_file.write_text(catalog_content, encoding="utf-8")

    env_content = """
TYPESAFE_API_KEY=key_for_account_1
TYPESAFE_API_KEY1=key_for_account_2
OPENROUTER_API_KEY=key_for_openrouter_forbidden
"""
    env_file = tmp_path / ".env"
    env_file.write_text(env_content, encoding="utf-8")

    accounts = load_typesafe_accounts(catalog_file, env_file)

    # Must contain exactly the two TypeSafe accounts, NEVER OpenRouter
    assert len(accounts) == 2
    assert accounts[0].alias == "account_1"
    assert accounts[0].api_key == "key_for_account_1"
    assert accounts[1].alias == "account_2"
    assert accounts[1].api_key == "key_for_account_2"

    for acc in accounts:
        assert "openrouter" not in acc.api_key.lower()


def test_load_typesafe_accounts_hard_asserts_catalog_vars(tmp_path: Path):
    """Verify that catalog tampering or missing expected keys causes fail-closed ValueError."""
    tampered_yaml = """
providers:
  typesafe-trial:
    accounts:
      - id: 1
        apiKey: TYPESAFE_API_KEY
      - id: 2
        apiKey: ROGUE_API_KEY
"""
    catalog_file = tmp_path / "tampered.yml"
    catalog_file.write_text(tampered_yaml, encoding="utf-8")

    with pytest.raises(ValueError, match="Unauthorized or unexpected catalog configuration"):
        load_typesafe_accounts(catalog_file)

    with pytest.raises(FileNotFoundError):
        load_typesafe_accounts(tmp_path / "non_existent.yml")


def test_load_typesafe_accounts_deduplicates_identical_keys(tmp_path: Path):
    """Verify that if both account refs resolve to the same underlying key, they are deduplicated."""
    catalog_content = """
providers:
  typesafe-trial:
    accounts:
      - id: 1
        apiKey: TYPESAFE_API_KEY
      - id: 2
        apiKey: TYPESAFE_API_KEY1
"""
    catalog_file = tmp_path / "providers.yml"
    catalog_file.write_text(catalog_content, encoding="utf-8")

    env_content = """
TYPESAFE_API_KEY=identical_shared_key
TYPESAFE_API_KEY1=identical_shared_key
"""
    env_file = tmp_path / ".env"
    env_file.write_text(env_content, encoding="utf-8")

    accounts = load_typesafe_accounts(catalog_file, env_file)
    assert len(accounts) == 1
    assert accounts[0].alias == "account_1"
    assert accounts[0].api_key == "identical_shared_key"


def test_evidence_hash_determinism():
    """Verify that evidence hash computation is deterministic and changes with input variation."""
    h1 = compute_evidence_hash("code_contract", ["path/a.sh:10-20"], "snippet_foo")
    h2 = compute_evidence_hash("code_contract", ["path/a.sh:10-20"], "snippet_foo")
    h3 = compute_evidence_hash("code_contract", ["path/a.sh:10-20"], "snippet_bar")

    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64


def test_code_contract_packets_contain_valid_typesafe_questions():
    """Verify that extracted code contract packets conform to TypeSafe primitive contracts."""
    template_dir = Path("template")
    parent_dir = Path(".")

    packets = extract_code_contract_packets(template_dir, parent_dir)
    assert len(packets) >= 4

    for packet in packets:
        assert packet.category in (
            "code_contract",
            "pipeline_consistency",
            "documentation_drift",
        )
        assert len(packet.source_paths) >= 1
        assert len(packet.questions) >= 1

        for qid, q in packet.questions.items():
            assert "type" in q
            assert "instructions" in q
            qtype = q["type"]
            assert qtype in ("choice", "noul", "score")

            if qtype == "choice":
                assert isinstance(q.get("criteria"), dict)
                assert len(q["criteria"]) >= 2
            elif qtype == "score":
                assert isinstance(q.get("criteria"), list)
                assert len(q["criteria"]) >= 2
            elif qtype == "noul":
                if "criteria" in q:
                    assert isinstance(q["criteria"], dict)
