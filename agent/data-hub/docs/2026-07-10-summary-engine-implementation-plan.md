# Structured Summary Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the duplicated legacy Daily/period summary paths with one evidence-backed, revisioned Summary Engine that produces useful tagged Daily-to-Yearly Markdown and preserves the 09:00/17:30/18:00 China-workday schedule.

**Architecture:** The lifecycle manager remains the only public workflow entry. A thin period orchestrator builds deterministic evidence packets, invokes level-specific structured prompts, validates JSON against versioned schema/taxonomy/policy, stages immutable SQLite revisions, publishes Markdown through a recoverable two-phase protocol, and propagates degraded state to the durable workflow runner. Higher levels consume published lower-level items and wikilinks, never embedded Markdown bodies.

**Tech Stack:** Python 3.12, SQLite, `jsonschema`, `chinese-calendar`, pytest, shell/launchd, Markdown/Obsidian wikilinks.

## Global Constraints

- Public reusable behavior changes only under `template/`; no private values or machine-specific paths enter the child repository.
- SQLite is canonical state; Markdown is a recoverable projection.
- Keep exactly one runtime path: lifecycle manager -> `knowledge_workflows.py` -> Summary Engine.
- Delete `scripts/daily_summary.py`, its old stages, and non-archive callers after migration; do not add compatibility wrappers.
- Daily output: 800–1200 Chinese characters, balanced work progress and knowledge insight.
- Daily knowledge insights: exactly 0 or 2–4; every retained insight has evidence and reuse/decision value.
- Weekly output: 1200–1800 Chinese characters; it uses Daily item IDs and wikilinks, never Daily body copies.
- Monthly/Quarterly/Yearly consume immutable revisions from the immediately lower layer and never copy lower Markdown.
- Item dimensions use only `计划组织`, `创新`, `沟通协作`, `专业知识`, `学习成长`; zero to two per item.
- Schedule: 09:00 morning and 17:30 reminder only on `chinese_calendar` workdays; 18:00 runs every calendar day and dispatches eligible Daily-to-Yearly workflows in lower-to-higher order.
- Tests use the repository `.venv`; every implementation task follows red-green-refactor and ends with a focused commit.
- Update `agent/data-hub/docs/summary-engine-implementation-report.md` after every task with commit, tests, counts, artifacts, known gaps, and next checkpoint.
- Do not overwrite real `~/work/knowledge` artifacts until isolated tests pass and the acceptance step explicitly backs them up.

---

## File Map

**Create:**

- `agent/data-hub/summary_contracts.py` — load/validate schema, taxonomy, policy; normalize evidence and output.
- `agent/data-hub/summary_evidence.py` — deterministic local/llm_wiki evidence collection and grouping.
- `agent/data-hub/summary_synthesis.py` — level prompt selection, backend call, JSON retry/parse.
- `agent/data-hub/summary_renderer.py` — deterministic Markdown and recoverable file projection.
- `agent/data-hub/prompts/higher-period-summary.md` — Monthly/Quarterly/Yearly synthesis.
- `agent/data-hub/prompts/summary-evidence-research.md` — llm_wiki Deep Chat research request.
- `agent/data-hub/prompts/summary-output.schema.json` — discriminated Daily/Weekly/Higher JSON contract.
- `agent/data-hub/prompts/summary-dimensions.v1.json` — canonical taxonomy with include/exclude/examples.
- `agent/data-hub/prompts/summary-policy.v1.json` — length, insight, evidence sufficiency, and schedule policy.
- `agent/data-hub/daily_reminder.sh` — workday-gated 17:30 reminder.
- `agent/data-hub/docs/summary-engine-implementation-report.md` — rolling review evidence.
- `tests/test_summary_contracts.py`
- `tests/test_summary_evidence.py`
- `tests/test_summary_synthesis.py`
- `tests/test_summary_renderer.py`
- `tests/test_summary_publish_recovery.py`

**Rewrite/extend:**

- `pyproject.toml`, `uv.lock` — add `jsonschema`.
- `agent/data-hub/schema.sql`, `schema_migrations.py` — logical summaries, immutable revisions, items, dimensions, evidence, support.
- `agent/data-hub/summary_store.py` — staged/published revision store and recovery.
- `agent/data-hub/llm_wiki_client.py`, `llm_wiki_context.py` — `/chat` deep evidence with citations.
- `agent/data-hub/prompts/chat_review.md`, `daily-summary.md`, `weekly-summary.md` — structured contracts.
- `agent/data-hub/summary_inputs.py` — SQLite lower-revision dependency resolver; no Markdown body reads.
- `agent/data-hub/period_summary.py` — thin orchestrator.
- `agent/data-hub/scripts/build_period_summary.py` — CLI marker output.
- `agent/data-hub/knowledge_workflows.py` — one summary stage family with degraded propagation.
- `agent/data-hub/summary_calendar.py`, `scripts/run_summary_schedule.py` — dependency closure and workday/period triggers.
- `agent/data-hub/daily_morning.sh`, `run-daily-evening.sh`, `launchd/install_obsidian_jobs.sh` — exact schedule.
- Data Hub tests, lifecycle skill scripts, README/CONTEXT/ops/reference/troubleshooting/cron docs.

**Delete:**

- `agent/data-hub/scripts/daily_summary.py`
- Tests that only encode deleted `daily_summary_stage()` / `materialization_stage()` compatibility behavior.

---

### Task 1: Versioned Summary Contracts and Taxonomy

**Files:**

- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `agent/data-hub/prompts/summary-output.schema.json`
- Create: `agent/data-hub/prompts/summary-dimensions.v1.json`
- Create: `agent/data-hub/prompts/summary-policy.v1.json`
- Create: `agent/data-hub/summary_contracts.py`
- Create: `tests/test_summary_contracts.py`
- Create: `agent/data-hub/docs/summary-engine-implementation-report.md`

**Interfaces:**

- Produces: `ContractBundle`, `EvidenceGroup`, `SummaryDocument`, `load_contract_bundle()`, `validate_summary_document()`, `canonical_json()`, `build_input_digest()`.
- Consumes later: every synthesis, store, renderer, and orchestrator task.

- [ ] **Step 1: Record baseline and write failing contract tests**

Create the report with baseline commit, current schedule, known privacy-audit baseline failure, and planned acceptance artifacts. Add tests equivalent to:

```python
def test_daily_contract_accepts_item_level_dimensions():
    bundle = load_contract_bundle()
    doc = {
        "contract_version": "summary-v1",
        "taxonomy_version": "dimensions-v1",
        "policy_version": "summary-policy-v1",
        "level": "daily",
        "period": "2026-07-10",
        "headline": "完成结构化总结设计。",
        "items": [{
            "item_type": "decision",
            "title": "统一入口",
            "conclusion": "所有周期总结通过 lifecycle manager。",
            "value": "消除双路径漂移。",
            "dimensions": ["计划组织", "专业知识"],
            "evidence_group_ids": ["evg_a"],
            "confidence": 0.95,
        }],
    }
    assert validate_summary_document(doc, bundle)["level"] == "daily"


def test_contract_rejects_unknown_or_three_dimensions():
    doc = valid_daily_document()
    doc["items"][0]["dimensions"] = ["计划组织", "专业知识", "未知"]
    with pytest.raises(SummaryContractError, match="dimensions"):
        validate_summary_document(doc, load_contract_bundle())


def test_insight_count_is_zero_or_two_to_four():
    doc = valid_daily_document()
    doc["items"].append(valid_item(item_type="insight"))
    with pytest.raises(SummaryContractError, match="insight count"):
        validate_summary_document(doc, load_contract_bundle())
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_summary_contracts.py -q`

Expected: collection fails because `summary_contracts` and contract files do not exist.

- [ ] **Step 3: Add dependency and contract assets**

Add `jsonschema>=4.0` to `dependencies`, refresh `uv.lock`, and define a JSON Schema with `if/then` branches for `daily`, `weekly`, and `monthly|quarterly|yearly`. The higher branches require `supporting_item_ids` and `lower_summary_refs`. Define policy values exactly:

```json
{
  "version": "summary-policy-v1",
  "daily_chars": {"min": 800, "max": 1200},
  "weekly_chars": {"min": 1200, "max": 1800},
  "daily_insights": {"allowed": [0, 2, 3, 4]},
  "max_dimensions_per_item": 2,
  "daily_min_work_evidence_groups": 1,
  "insight_min_source_refs": 2,
  "insight_min_source_kinds": 2,
  "higher_min_supporting_items": 2
}
```

Implement immutable dataclasses and validation:

```python
@dataclass(frozen=True)
class EvidenceGroup:
    evidence_group_id: str
    evidence_kind: str
    source_refs: tuple[str, ...]
    source_kinds: tuple[str, ...]
    payload: dict[str, Any]


@dataclass(frozen=True)
class ContractBundle:
    schema: dict[str, Any]
    taxonomy: dict[str, Any]
    policy: dict[str, Any]
    hashes: dict[str, str]


def validate_summary_document(value: dict[str, Any], bundle: ContractBundle) -> dict[str, Any]:
    jsonschema.validate(value, bundle.schema)
    # Enforce taxonomy whitelist, 0/2-4 insights, evidence membership, and placeholder rejection.
    return value
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_summary_contracts.py -q`

Expected: all contract tests pass.

- [ ] **Step 5: Update report and commit**

Record contract versions, test count, and generated lock change.

```bash
git add pyproject.toml uv.lock agent/data-hub/prompts agent/data-hub/summary_contracts.py tests/test_summary_contracts.py agent/data-hub/docs/summary-engine-implementation-report.md
git commit -m "feat(data-hub): add summary contracts"
```

### Task 2: Logical Summaries, Immutable Revisions, and Recovery Store

**Files:**

- Modify: `agent/data-hub/schema.sql`
- Modify: `agent/data-hub/schema_migrations.py`
- Rewrite: `agent/data-hub/summary_store.py`
- Modify: `agent/data-hub/db_helper.py`
- Modify: `tests/test_summary_store.py`
- Create: `tests/test_summary_publish_recovery.py`
- Modify: `agent/data-hub/docs/summary-engine-implementation-report.md`

**Interfaces:**

- Consumes: `SummaryDocument`, `EvidenceGroup`, `build_input_digest()`.
- Produces: `SummaryRevision`, `stage_revision()`, `find_published_revision()`, `mark_file_published()`, `finalize_revision()`, `recover_pending_revision()`, `load_revision_document()`.

- [ ] **Step 1: Write failing migration/store tests**

```python
def test_stage_revision_is_idempotent_for_same_input(conn):
    first = stage_revision(conn, summary_key("daily", "2026-07-10"), "digest-1", document(), evidence())
    second = stage_revision(conn, summary_key("daily", "2026-07-10"), "digest-1", document(), evidence())
    assert first.revision_id == second.revision_id
    assert conn.execute("SELECT count(*) FROM summary_revisions").fetchone()[0] == 1


def test_finalize_switches_current_revision_only_after_file_publish(conn, artifact):
    summary_id = ensure_logical_summary(conn, "daily", "2026-07-10")
    revision = stage_revision(
        conn,
        summary_id=summary_id,
        input_digest="digest-1",
        coverage_start="2026-07-10",
        coverage_end="2026-07-10",
        closure_status="closed",
        document=valid_daily_document(),
        evidence_groups=valid_evidence_groups(),
        quality_status="complete",
    )
    mark_file_published(conn, revision.revision_id, artifact.path, artifact.sha256)
    finalize_revision(conn, revision.revision_id)
    row = conn.execute("SELECT current_revision_id FROM summaries").fetchone()
    assert row[0] == revision.revision_id


def test_migration_converts_and_drops_legacy_summary_tables(conn_with_legacy_rows):
    ensure_summary_revision_schema(conn_with_legacy_rows)
    assert table_exists(conn_with_legacy_rows, "summaries")
    assert not table_exists(conn_with_legacy_rows, "summary_runs")
    assert not table_exists(conn_with_legacy_rows, "summary_run_sources")
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_summary_store.py tests/test_summary_publish_recovery.py -q`

Expected: failures for missing revision tables/APIs.

- [ ] **Step 3: Implement schema and one-time migration**

Create the exact tables from the approved spec: `summaries`, `summary_revisions`, `summary_items`, `summary_item_dimensions`, `summary_evidence_groups`, `summary_evidence_sources`, `summary_item_evidence`, `summary_item_support`. Add foreign keys and unique constraints. Migrate existing summary rows into `contract_version='legacy'` revisions and drop old tables in the same migration transaction.

Implement deterministic IDs:

```python
def logical_summary_id(level: str, period_id: str) -> str:
    return "summary_" + sha256(f"{level}:{period_id}".encode()).hexdigest()[:20]


def revision_id(summary_id: str, input_digest: str) -> str:
    return "rev_" + sha256(f"{summary_id}:{input_digest}".encode()).hexdigest()[:24]


def item_id(revision_id: str, section_key: str, ordinal: int) -> str:
    return "item_" + sha256(f"{revision_id}:{section_key}:{ordinal}".encode()).hexdigest()[:24]
```

- [ ] **Step 4: Implement staged publish and recovery state transitions**

Allow only:

```text
staged -> file_published -> published
staged|file_published -> failed
```

`finalize_revision()` must verify the artifact exists and its full-file SHA-256 equals `artifact_hash`. `recover_pending_revision()` must finalize a matching published file or request re-render for a staged revision without a matching file.

- [ ] **Step 5: Verify GREEN and migration safety**

Run: `.venv/bin/python -m pytest tests/test_summary_store.py tests/test_summary_publish_recovery.py tests/test_data_hub.py -q`

Expected: all pass; legacy rows preserved as legacy revisions, old tables absent.

- [ ] **Step 6: Update report and commit**

```bash
git add agent/data-hub/schema.sql agent/data-hub/schema_migrations.py agent/data-hub/db_helper.py agent/data-hub/summary_store.py tests/test_summary_store.py tests/test_summary_publish_recovery.py agent/data-hub/docs/summary-engine-implementation-report.md
git commit -m "feat(data-hub): add revisioned summary store"
```

### Task 3: llm_wiki Deep Evidence Collection

**Files:**

- Modify: `agent/data-hub/llm_wiki_client.py`
- Modify: `agent/data-hub/llm_wiki_context.py`
- Create: `agent/data-hub/summary_evidence.py`
- Create: `agent/data-hub/prompts/summary-evidence-research.md`
- Modify: `tests/test_llm_wiki_client.py`
- Create: `tests/test_summary_evidence.py`
- Modify: `agent/data-hub/docs/summary-engine-implementation-report.md`

**Interfaces:**

- Produces: `LlmWikiClient.chat(message, mode='deep')`, `EvidencePacket`, `collect_summary_evidence(level, period, conn, client)`.
- Consumes later: `summary_synthesis.synthesize_summary()`.

- [ ] **Step 1: Write failing API/evidence tests**

```python
def test_chat_posts_deep_mode_and_returns_citations(fake_transport):
    client = LlmWikiClient(
        api_base="http://127.0.0.1:19828",
        project_id="project-1",
        token_env="LLM_WIKI_TOKEN",
        token="test-token",
        transport=fake_transport,
    )
    result = client.chat("找出本周关键变化", mode="deep")
    assert fake_transport.request_json["mode"] == "deep"
    assert result["citations"][0]["path"] == "wiki/concepts/summary.md"


def test_evidence_groups_are_deterministic_and_exclude_summaries():
    packet_a = collect_summary_evidence(
        level="daily",
        period_id="2026-07-10",
        period_start="2026-07-10",
        period_end="2026-07-10",
        conn=seeded_conn,
        client=fake_client,
    )
    packet_b = collect_summary_evidence(
        level="daily",
        period_id="2026-07-10",
        period_start="2026-07-10",
        period_end="2026-07-10",
        conn=seeded_conn,
        client=fake_client,
    )
    assert packet_a.canonical_json() == packet_b.canonical_json()
    assert all(not ref.startswith("70_Summaries/") for group in packet_a.groups for ref in group.source_refs)
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_llm_wiki_client.py tests/test_summary_evidence.py -q`

- [ ] **Step 3: Extend client and build evidence packet**

Implement:

```python
def chat(self, message: str, *, mode: str = "deep") -> dict[str, Any]:
    return self._request(
        "POST",
        f"/api/v1/projects/{self.project_id}/chat",
        {"message": message, "mode": mode},
    )
```

Normalize local Daily/Git/records/candidates and llm_wiki search/chat citations into sorted evidence groups. Compute each ID only from period, canonical refs, and claim IDs. Never include `70_Summaries` search results or bodies.

- [ ] **Step 4: Implement sufficiency evaluation**

Return explicit `quality_status` and warning codes:

```python
@dataclass(frozen=True)
class EvidencePacket:
    groups: tuple[EvidenceGroup, ...]
    quality_status: Literal["complete", "degraded"]
    warnings: tuple[str, ...]
```

Raise `InsufficientEvidenceError` when the policy's whole-summary threshold is not met; do not raise when only the insight threshold is unmet.

- [ ] **Step 5: Verify GREEN, update report, commit**

Run: `.venv/bin/python -m pytest tests/test_llm_wiki_client.py tests/test_summary_evidence.py tests/test_knowledge_retrieval.py -q`

```bash
git add agent/data-hub/llm_wiki_client.py agent/data-hub/llm_wiki_context.py agent/data-hub/summary_evidence.py agent/data-hub/prompts/summary-evidence-research.md tests/test_llm_wiki_client.py tests/test_summary_evidence.py agent/data-hub/docs/summary-engine-implementation-report.md
git commit -m "feat(data-hub): collect cited summary evidence"
```

### Task 4: Structured Prompt Synthesis for All Five Levels

**Files:**

- Rewrite: `agent/data-hub/prompts/chat_review.md`
- Rewrite: `agent/data-hub/prompts/daily-summary.md`
- Rewrite: `agent/data-hub/prompts/weekly-summary.md`
- Create: `agent/data-hub/prompts/higher-period-summary.md`
- Create: `agent/data-hub/summary_synthesis.py`
- Modify: `agent/data-hub/data_hub_config.py`
- Modify: `agent/data-hub/llm_filter.py`
- Create: `tests/test_summary_synthesis.py`
- Modify: `tests/test_candidate_review.py`
- Modify: `agent/data-hub/docs/summary-engine-implementation-report.md`

**Interfaces:**

- Consumes: `EvidencePacket`, `ContractBundle`.
- Produces: `synthesize_summary(level, period, evidence, bundle, backend) -> SummaryDocument`.

- [ ] **Step 1: Write failing prompt selection/retry tests**

```python
@pytest.mark.parametrize(("level", "prompt_name"), [
    ("daily", "daily-summary.md"),
    ("weekly", "weekly-summary.md"),
    ("monthly", "higher-period-summary.md"),
    ("quarterly", "higher-period-summary.md"),
    ("yearly", "higher-period-summary.md"),
])
def test_level_selects_contract_prompt(level, prompt_name):
    assert prompt_name_for(level) == prompt_name


def test_invalid_json_retries_once_with_validation_error(fake_backend):
    fake_backend.outputs = ["not-json", json.dumps(valid_daily_document())]
    result = synthesize_summary(
        level="daily",
        period_id="2026-07-10",
        evidence=valid_evidence_packet(),
        bundle=load_contract_bundle(),
        backend=fake_backend,
    )
    assert result.level == "daily"
    assert fake_backend.calls == 2
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_summary_synthesis.py tests/test_candidate_review.py -q`

- [ ] **Step 3: Rewrite prompts around shared injected contracts**

Each prompt receives `${contract_json}`, `${taxonomy_json}`, `${policy_json}`, and `${evidence_json}` and returns JSON only. `chat_review.md` keeps noise rejection and adds `dimension_hints`/`evidence_refs`. Daily requires work/insight balance. Weekly/higher require support IDs and lower refs and prohibit body copying.

Remove private full-file override for Data Hub behavior prompts. Keep backend/model/token values private through runtime config.

- [ ] **Step 4: Implement one-retry JSON synthesis**

```python
def synthesize_summary(
    *,
    level: str,
    period_id: str,
    evidence: EvidencePacket,
    bundle: ContractBundle,
    backend: LLMBackend,
) -> SummaryDocument:
    prompt = render_level_prompt(
        level=level,
        period_id=period_id,
        evidence=evidence,
        bundle=bundle,
    )
    for attempt in range(2):
        raw = backend.generate(prompt)
        try:
            return SummaryDocument.from_dict(validate_summary_document(json.loads(raw), bundle))
        except (json.JSONDecodeError, SummaryContractError) as exc:
            if attempt == 1:
                raise SummarySynthesisError(str(exc)) from exc
            prompt = render_repair_prompt(prompt, raw, str(exc))
```

- [ ] **Step 5: Verify GREEN, update report, commit**

Run: `.venv/bin/python -m pytest tests/test_summary_synthesis.py tests/test_candidate_review.py tests/test_llm_filter.py -q`

```bash
git add agent/data-hub/prompts agent/data-hub/summary_synthesis.py agent/data-hub/data_hub_config.py agent/data-hub/llm_filter.py tests/test_summary_synthesis.py tests/test_candidate_review.py agent/data-hub/docs/summary-engine-implementation-report.md
git commit -m "feat(data-hub): synthesize structured summaries"
```

### Task 5: Deterministic Markdown Renderer and Recoverable Publish

**Files:**

- Create: `agent/data-hub/summary_renderer.py`
- Create: `tests/test_summary_renderer.py`
- Extend: `tests/test_summary_publish_recovery.py`
- Add: `tests/fixtures/summary/daily.md`
- Add: `tests/fixtures/summary/weekly.md`
- Add: `tests/fixtures/summary/monthly.md`
- Modify: `agent/data-hub/docs/summary-engine-implementation-report.md`

**Interfaces:**

- Consumes: staged revision/document from `summary_store`.
- Produces: `RenderedArtifact`, `render_summary_markdown()`, `publish_revision()`, `recover_projection()`.

- [ ] **Step 1: Write failing golden/idempotency tests**

```python
def test_weekly_uses_wikilinks_without_daily_body():
    text = render_summary_markdown(weekly_document())
    assert "[[70_Summaries/Daily/2026-07-10|07-10]]" in text
    assert "### 70_Summaries/Daily/" not in text
    assert "copied daily body" not in text


def test_atomic_publish_recovery_after_finalize_failure(tmp_path, conn, monkeypatch):
    revision = staged_revision(conn)
    monkeypatch.setattr(summary_store, "finalize_revision", raising_finalize)
    with pytest.raises(RuntimeError):
        publish_revision(conn, revision.revision_id, target_path)
    assert target_path.exists()
    recover_projection(conn, target_path)
    assert current_revision(conn) == revision.revision_id
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_summary_renderer.py tests/test_summary_publish_recovery.py -q`

- [ ] **Step 3: Implement fixed Markdown rendering**

Render item-level `类型/维度/结论/价值/证据/置信度`, Daily and Weekly sections from the approved spec, and higher-period equivalents. Render source refs as Obsidian wikilinks when vault-relative and compact code refs otherwise. Count Chinese-visible characters against policy before publish.

- [ ] **Step 4: Implement full-file hashing and recovery**

Write to `target.with_suffix(target.suffix + '.tmp')`, fsync, compute SHA-256 over the complete temp bytes, record the hash on staged revision, then `os.replace`. The file frontmatter includes only revision/input IDs, not its own hash.

- [ ] **Step 5: Verify GREEN, update report, commit**

Run: `.venv/bin/python -m pytest tests/test_summary_renderer.py tests/test_summary_publish_recovery.py -q`

```bash
git add agent/data-hub/summary_renderer.py tests/test_summary_renderer.py tests/test_summary_publish_recovery.py tests/fixtures/summary agent/data-hub/docs/summary-engine-implementation-report.md
git commit -m "feat(data-hub): render recoverable summaries"
```

### Task 6: Period Dependencies and Thin Orchestration

**Files:**

- Rewrite: `agent/data-hub/summary_inputs.py`
- Rewrite: `agent/data-hub/period_summary.py`
- Modify: `agent/data-hub/scripts/build_period_summary.py`
- Modify: `tests/test_summary_inputs.py`
- Modify: `tests/test_period_summary.py`
- Modify: `tests/test_build_period_summary_cli.py`
- Modify: `agent/data-hub/docs/summary-engine-implementation-report.md`

**Interfaces:**

- Produces: `resolve_lower_revisions()`, `dependency_closure()`, `build_period_summary() -> SummaryBuildResult`.
- Consumes: all prior contract/evidence/synthesis/store/renderer modules.

- [ ] **Step 1: Write failing dependency/closure tests**

```python
def test_weekly_preholiday_revision_is_provisional_when_week_has_later_workday(conn):
    result = resolve_period_coverage("weekly", "2026-10-02")
    assert result.closure_status == "provisional"


def test_month_end_closure_requests_missing_current_weekly_revision(conn):
    closure = dependency_closure("monthly", "2026-07-31", conn)
    assert closure.workflows[-1] == "build_monthly_summary"
    assert "build_weekly_summary" in closure.workflows


def test_summary_inputs_never_reads_lower_markdown_body(monkeypatch):
    monkeypatch.setattr(Path, "read_text", lambda *_: (_ for _ in ()).throw(AssertionError("no Markdown reads")))
    assert resolve_lower_revisions(
        conn=seeded_conn,
        level="weekly",
        period_start="2026-07-06",
        period_end="2026-07-12",
        coverage_end="2026-07-10",
        deployment_start="2026-07-10",
    ) == expected
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_summary_inputs.py tests/test_period_summary.py tests/test_build_period_summary_cli.py -q`

- [ ] **Step 3: Rewrite dependency resolver**

Query only published SQLite revisions/items/support. Use coverage intersection with higher period and deployment start. Preserve immutable lower revision IDs chosen at the boundary.

- [ ] **Step 4: Rewrite orchestrator and CLI result marker**

```python
@dataclass(frozen=True)
class SummaryBuildResult:
    output_path: Path
    revision_id: str
    quality_status: Literal["complete", "degraded"]
    warnings: tuple[str, ...]


def main():
    result = build_period_summary(args.level, args.anchor_date)
    print(json.dumps(asdict(result), default=str, ensure_ascii=False))
    if result.quality_status == "degraded":
        print("SUMMARY_STATUS=degraded")
```

If a published revision with identical input digest exists, return it before synthesis.

- [ ] **Step 5: Verify all five levels and GREEN**

Run: `.venv/bin/python -m pytest tests/test_summary_inputs.py tests/test_period_summary.py tests/test_build_period_summary_cli.py -q`

- [ ] **Step 6: Update report and commit**

```bash
git add agent/data-hub/summary_inputs.py agent/data-hub/period_summary.py agent/data-hub/scripts/build_period_summary.py tests/test_summary_inputs.py tests/test_period_summary.py tests/test_build_period_summary_cli.py agent/data-hub/docs/summary-engine-implementation-report.md
git commit -m "feat(data-hub): orchestrate revisioned period summaries"
```

### Task 7: One Lifecycle Path and Legacy Removal

**Files:**

- Modify: `agent/data-hub/knowledge_workflows.py`
- Delete: `agent/data-hub/scripts/daily_summary.py`
- Modify: `tests/test_daily_workflows.py`
- Delete/replace: `tests/test_daily_summary_runtime.py`
- Modify: `tests/test_lifecycle_manager_adapters.py`
- Modify: `agent/skills/personal/knowledge-daily-weekly-synthesis/scripts/run-daily-synthesis.sh`
- Modify: `agent/skills/personal/knowledge-source-ingestion/scripts/run-full-cycle.sh`
- Modify: corresponding `SKILL.md` and reference files
- Modify: `agent/data-hub/obsidian_helper.py`
- Modify: `agent/data-hub/docs/summary-engine-implementation-report.md`

**Interfaces:**

- Public entry remains: `manager.py run --workflow build_<level>_summary --date YYYY-MM-DD`.
- Stage contract emits degraded when stdout contains `SUMMARY_STATUS=degraded`.

- [ ] **Step 1: Write failing single-path/degraded tests**

```python
def test_summary_stage_maps_degraded_marker():
    stage = build_workflow_steps("build_daily_summary", "2026-07-10")[0]
    assert stage.degraded_ok is True
    assert any(check.kind == "output_not_contains" and "SUMMARY_STATUS=degraded" in check.expected for check in stage.success_checks)


def test_no_runtime_caller_references_legacy_daily_summary():
    offenders = scan_runtime_files("daily_summary.py", exclude=("docs/archive", "tests/archive"))
    assert offenders == []
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_daily_workflows.py tests/test_lifecycle_manager_adapters.py -q`

- [ ] **Step 3: Remove dead stages and migrate callers**

Delete `daily_summary_stage()` and `materialization_stage()`. Update both skills to call the lifecycle manager. Remove old comments/placeholders that name the deleted script. Delete the script only after the scan test proves no runtime caller remains.

- [ ] **Step 4: Verify degraded status reaches workflow run**

Run: `.venv/bin/python -m pytest tests/test_daily_workflows.py tests/test_lifecycle_manager_adapters.py tests/test_workflow_abandoned.py -q`

Expected: complete marker -> completed; degraded marker -> step/run degraded; nonzero -> failed.

- [ ] **Step 5: Update report and commit**

```bash
git add -A agent/data-hub agent/skills/personal/knowledge-daily-weekly-synthesis agent/skills/personal/knowledge-source-ingestion tests/test_daily_workflows.py tests/test_lifecycle_manager_adapters.py tests/test_workflow_abandoned.py
git commit -m "refactor(data-hub): remove legacy summary path"
```

### Task 8: Preserve and Correct Scheduled Automation

**Files:**

- Modify: `agent/data-hub/summary_calendar.py`
- Modify: `agent/data-hub/scripts/run_summary_schedule.py`
- Modify: `agent/data-hub/daily_morning.sh`
- Create: `agent/data-hub/daily_reminder.sh`
- Modify: `agent/data-hub/run-daily-evening.sh`
- Modify: `launchd/install_obsidian_jobs.sh`
- Modify: `tests/test_summary_calendar.py`
- Modify: `tests/test_summary_schedule.py`
- Modify: `tests/test_lifecycle_manager_adapters.py`
- Modify: `agent/data-hub/docs/summary-engine-implementation-report.md`

**Interfaces:**

- Produces: exact 09:00/17:30/18:00 launchd schedule and `planned_workflows()` with dependency closure.

- [ ] **Step 1: Write failing schedule tests**

```python
def test_installer_uses_exact_times_and_reminder_wrapper():
    text = installer_text()
    assert "<integer>9</integer>" in text
    assert "<integer>17</integer>" in text
    assert "<integer>30</integer>" in text
    assert "<integer>18</integer>" in text
    assert "18:30" not in text
    assert "${DATA_HUB_DIR}/daily_reminder.sh" in text


def test_daily_and_reminder_gate_on_chinese_workday(monkeypatch):
    monkeypatch.setattr(summary_calendar, "is_workday", lambda _: False)
    assert should_run_scheduled_event("morning", "2026-10-01") is False
    assert should_run_scheduled_event("reminder", "2026-10-01") is False


def test_period_boundary_expands_lower_dependency_closure(monkeypatch):
    assert planned_workflows("2026-12-31") == [
        "build_daily_summary", "build_weekly_summary", "build_monthly_summary",
        "build_quarterly_summary", "build_yearly_summary",
    ]
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_summary_calendar.py tests/test_summary_schedule.py tests/test_lifecycle_manager_adapters.py -q`

- [ ] **Step 3: Implement workday gates and 18:00 installer**

Use `chinese_calendar` only. Morning/reminder wrappers exit 0 with a clear `skip: non-workday` line. Evening fires daily; `planned_workflows()` adds triggered levels plus required lower closure and returns the fixed low-to-high order.

- [ ] **Step 4: Verify GREEN and shell syntax**

Run:

```bash
.venv/bin/python -m pytest tests/test_summary_calendar.py tests/test_summary_schedule.py tests/test_lifecycle_manager_adapters.py -q
bash -n agent/data-hub/daily_morning.sh agent/data-hub/daily_reminder.sh agent/data-hub/run-daily-evening.sh launchd/install_obsidian_jobs.sh
```

- [ ] **Step 5: Update report and commit**

```bash
git add agent/data-hub/summary_calendar.py agent/data-hub/scripts/run_summary_schedule.py agent/data-hub/daily_morning.sh agent/data-hub/daily_reminder.sh agent/data-hub/run-daily-evening.sh launchd/install_obsidian_jobs.sh tests/test_summary_calendar.py tests/test_summary_schedule.py tests/test_lifecycle_manager_adapters.py agent/data-hub/docs/summary-engine-implementation-report.md
git commit -m "fix(data-hub): preserve workday summary schedule"
```

### Task 9: Documentation Alignment and Isolated End-to-End Acceptance

**Files:**

- Modify: `agent/data-hub/README.md`
- Modify: `agent/data-hub/CONTEXT.md`
- Modify: `agent/data-hub/docs/README.md`
- Modify: `agent/data-hub/docs/ops.md`
- Modify: `agent/data-hub/docs/reference.md`
- Modify: `agent/data-hub/docs/troubleshooting.md`
- Modify: `agent/data-hub/docs/cron-setup.md`
- Modify: `agent/data-hub/docs/summary-engine-implementation-report.md`
- Modify: relevant skill docs/tests

**Interfaces:**

- Produces: one current runbook and reviewable isolated acceptance evidence.

- [ ] **Step 1: Write failing documentation/alignment assertions**

Update tests to require 18:00, forbid active `daily_summary.py` instructions, require the five-level structured contract and item dimensions, and require the report's checkpoint headings.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_lifecycle_manager_adapters.py tests/test_data_hub_orchestration_runtime.py -q`

- [ ] **Step 3: Update current docs and remove stale operational claims**

Document:

- Single manager entry.
- Item-level dimensions and SQLite canonical tables.
- Revision/publish recovery commands.
- llm_wiki search/deep-chat degraded behavior.
- 09:00/17:30/18:00 and China workday/holiday rules.
- Five-level dependency closure and provisional/closed revisions.

- [ ] **Step 4: Run isolated five-level flow twice**

Use temp DB/vault/runtime and fake deterministic backend. Generate Daily, Weekly, Monthly, Quarterly, Yearly, then rerun identical commands. Record:

- revision/item/dimension/source/support counts before/after rerun;
- output paths and SHA-256 values;
- frontmatter and representative item blocks;
- assertion that no higher artifact contains a lower body.

- [ ] **Step 5: Run focused suite and commit**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_summary_contracts.py tests/test_summary_store.py \
  tests/test_summary_evidence.py tests/test_summary_synthesis.py \
  tests/test_summary_renderer.py tests/test_summary_publish_recovery.py \
  tests/test_summary_inputs.py tests/test_period_summary.py \
  tests/test_summary_calendar.py tests/test_summary_schedule.py \
  tests/test_daily_workflows.py tests/test_lifecycle_manager_adapters.py -q
```

```bash
git add agent/data-hub/README.md agent/data-hub/CONTEXT.md agent/data-hub/docs agent/skills tests
git commit -m "docs(data-hub): align summary lifecycle runbooks"
```

### Task 10: Live Acceptance, Quality Gates, Review, and Final Records

**Files:**

- Modify: `agent/data-hub/docs/summary-engine-implementation-report.md`
- Modify only review-requested implementation/docs files.

**Interfaces:**

- Produces: real 2026-07-10 Daily and 2026-W28 Weekly evidence, scheduler evidence, full test/doctor evidence, review findings/resolutions.

- [ ] **Step 1: Run full automated gates before touching live artifacts**

Run sequentially:

```bash
.venv/bin/python -m pytest tests -q
make check
make doctor
make privacy-audit
```

Expected: all pass. If privacy audit still reports the pre-existing `tests/test_skill_supply_chain.py` owner paths, record it as baseline and resolve it in an isolated, separately reviewed commit before claiming the gate passes.

- [ ] **Step 2: Back up live artifacts and record baseline**

Copy the current Daily/Weekly files and query current SQLite counts without modifying originals. Record paths, hashes, current run IDs, and the backup directory in the implementation report.

- [ ] **Step 3: Run real llm_wiki-backed Daily and Weekly twice**

Run manager workflows for `2026-07-10` and W28. After the first run capture:

- workflow/revision IDs and complete/degraded status;
- llm_wiki citations and warnings;
- item/dimension/source/support counts;
- Markdown hashes and representative structure.

Run the same workflows again. Require identical current revision IDs, row counts, and Markdown hashes.

- [ ] **Step 4: Reinstall and inspect live launchd jobs**

Run the project installer, then use `launchctl print`/generated plist inspection to prove 09:00, 17:30, 18:00. Exercise date-injected scheduler tests for ordinary workday, weekend, statutory holiday, adjusted workday, pre-holiday workday, month/quarter/year end. Do not wait for wall-clock triggers.

- [ ] **Step 5: Request independent code review and resolve findings**

Use `requesting-code-review`; provide spec, plan, commit range, test evidence, live artifacts, and implementation report. Fix every Critical/High and all in-scope Medium findings with new failing tests first. Record finding -> resolution -> commit.

- [ ] **Step 6: Run neat-freak and final gates**

Use `neat-freak` to check paths, parent/template boundaries, prompt/schema/taxonomy single-source rules, current docs, stale old-entry references, and workspace hygiene. Then rerun sequentially:

```bash
.venv/bin/python -m pytest tests -q
make check
make doctor
make privacy-audit
```

- [ ] **Step 7: Finalize report and commit**

The report must contain:

- commit timeline and task checkpoints;
- exact tests/gates with pass/fail counts;
- isolated and live run IDs;
- pre/post SQLite counts;
- artifact paths/hashes/snippets;
- schedule evidence;
- code review findings/resolutions;
- known residual risks (or `none`);
- rollback steps.

```bash
git add agent/data-hub/docs/summary-engine-implementation-report.md
git commit -m "docs(data-hub): record summary engine acceptance"
```

- [ ] **Step 8: Finish the development branch**

Use `finishing-a-development-branch`. Do not push or update the parent submodule pointer until the public child branch is verified and the chosen integration path is confirmed. Preserve unrelated parent `private/agent/data/agent_history.db` changes.
