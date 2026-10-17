# Repository Maintenance & Audit Scripts

This directory contains standalone maintenance, intake, and audit scripts for `mac-bootstrap`.

## TypeSafe Jev Batch Audit (`typesafe_batch_audit.py`)

A bounded, resumable audit runner that evaluates code-as-docs relationships, Single Source of Truth (SSOT) contracts, and pipeline consistency using the official TypeSafe System One API (`jev-latest` / `jev-1.13.0`).

### Features
- **Official System One Integration**: Evaluates typed semantic primitives (`Choice`, `Noul`, `Score`) via `https://api.typesafe.ai/v1/systemone`.
- **Fail-Closed Security & Privacy**:
  - Rejects HTTP 3xx redirects.
  - Deterministically screens and drops internal IPs (`10.x.x.x`, `192.168.x.x`, `172.16-31.x.x`), personal domains, and secrets before payload generation.
  - Scans only git-tracked public files via `git ls-files -z`.
- **Dual Account Utilization & Enforceable Caps**:
  - Strict YAML catalog parser reading only `providers.typesafe-trial.accounts` from `providers.yml` (`TYPESAFE_API_KEY` and `TYPESAFE_API_KEY1`). Sibling providers (e.g. OpenRouter) are strictly isolated and rejected.
  - Enforces verified official pricing ($0.042/M input tokens, free output tokens) with a default cap of $0.50 per account.
  - Rebuilds cumulative account spend and request counts from existing JSONL ledgers upon resumption.
- **External Non-Tracked State**:
  - Default JSONL ledger: `~/.local/state/mac-bootstrap/typesafe-audit/evidence_judgments.jsonl`
  - Default summary report: `~/.local/state/mac-bootstrap/typesafe-audit/audit_summary.md`
  - Avoids polluting the repository working tree with untracked evaluation records.

### Usage

```bash
# Dry run: extract git-tracked evidence packets and validate questions without API calls
template/.venv/bin/python template/scripts/typesafe_batch_audit.py --dry-run

# Execute bounded batch audit (resumes automatically from existing ledger)
template/.venv/bin/python template/scripts/typesafe_batch_audit.py \
  --catalog private/agent/omp/catalog/providers.yml \
  --env private/agent/omp/.env \
  --max-packets 200 \
  --budget-per-account 0.50

# Run focused unit tests
template/.venv/bin/python -m pytest template/tests/test_typesafe_batch_audit.py
```
