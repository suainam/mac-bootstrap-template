"""Tests for universal 5-stage analytics lifecycle skills.

Verifies:
1. Standards compliance (writing-for-agents, frontmatter, descriptions, leading words, steps).
2. Reachability of all internal context pointers, scripts, templates, and reference assets.
3. Functional parity and complete coverage of legacy product-strategy skills.
4. Health of underlying unit test suites for analytics tools.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.skill_registry import (
    load_registry,
    validate_skill_dir,
)
LIFECYCLE_ROOT = ROOT / "agent-skills/local/analytics-lifecycle"
PRODUCT_STRATEGY_ROOT = ROOT / "agent-skills/local/product-strategy"

EXPECTED_STAGES = [
    ("analytics-demand-intake", "阶段一：需求收集"),
    ("analytics-demand-analysis", "阶段二：需求分析"),
    ("analytics-data-solution", "阶段三：数据方案"),
    ("analytics-data-execution", "阶段四：数据分析"),
    ("analytics-result-delivery", "阶段五：结果交付"),
]

def test_all_five_lifecycle_skills_exist_and_pass_supply_chain_validation() -> None:
    """Every stage skill must exist and pass official skill supply chain validation."""
    registry = load_registry(ROOT / "agent-skills/registry/sources.jsonc")
    for skill_name, title_keyword in EXPECTED_STAGES:
        key = ("local-analytics-lifecycle", skill_name)
        assert key in registry.skills, f"Skill {skill_name} not registered in sources.jsonc"
        ref = registry.skills[key]
        assert ref.source_type == "internal"
        assert ref.scope == "global", f"Skill {skill_name} must be globally distributed"
        assert ref.agents, f"Skill {skill_name} must declare agent targets"

    for skill_name, title_keyword in EXPECTED_STAGES:
        skill_dir = LIFECYCLE_ROOT / skill_name
        assert skill_dir.is_dir(), f"Missing skill directory: {skill_dir}"

        # Official skill supply chain validation
        errors = validate_skill_dir(skill_dir, skill_name)
        assert not errors, f"Supply chain validation errors for {skill_name}: {errors}"

        # Content and structure validation
        skill_md = skill_dir / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")
        assert title_keyword in content, f"Missing title keyword '{title_keyword}' in {skill_name}"
        assert "## 核心主导词 (Leading Words)" in content
        assert "## 内部资产引用 (Internal Assets)" in content
        assert "完成标准" in content


def test_frontmatter_adheres_to_writing_for_agents_criteria() -> None:
    """Verify descriptions are concise (<=1024), front-load leading words, and avoid bloat."""
    for skill_name, _ in EXPECTED_STAGES:
        skill_md = LIFECYCLE_ROOT / skill_name / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")
        parts = content.split("---", 2)
        assert len(parts) >= 3, f"Invalid frontmatter structure in {skill_name}"

        meta = {}
        for line in parts[1].strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip("'\"")

        assert meta.get("name") == skill_name
        desc = meta.get("description", "")
        assert len(desc) > 20, f"Description too short for {skill_name}"
        assert len(desc) <= 1024, f"Description exceeds 1024 chars for {skill_name}"

        # Front-loaded leading words verify high demand and clear triggers
        first_word = desc.split()[0].lower()
        assert first_word in {"intake", "analyze", "author", "execute", "deliver"}, (
            f"Expected leading action verb in {skill_name} description, got '{first_word}'"
        )


def test_asset_pointers_resolve_to_real_files() -> None:
    """Assert all internal pointers and script references exist on disk without dead links."""
    for skill_name, _ in EXPECTED_STAGES:
        skill_dir = LIFECYCLE_ROOT / skill_name
        content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")

        for word in content.split():
            clean_word = word.strip("`'\"(),;:")
            if any(clean_word.startswith(prefix) for prefix in ("scripts/", "references/", "examples/", "templates/", "../../")):
                if not clean_word.endswith("..."):
                    target_path = (skill_dir / clean_word).resolve()
                    assert target_path.exists(), f"Broken pointer in {skill_name}: {clean_word} -> {target_path}"


def test_demand_intake_is_self_contained_with_all_assets() -> None:
    """Assert analytics-demand-intake has all required local scripts, references, examples, and templates."""
    intake_dir = LIFECYCLE_ROOT / "analytics-demand-intake"
    assert (intake_dir / "scripts/extract_devops_demand.js").is_file()
    assert (intake_dir / "scripts/wecom_sheet_driver.js").is_file()
    assert (intake_dir / "references/socratic_probing_guide.md").is_file()
    assert (intake_dir / "references/wecom_sheet_patterns.md").is_file()
    assert (intake_dir / "examples/golden_demand_extraction.md").is_file()
    assert (intake_dir / "examples/adhoc_socratic_clarification.md").is_file()
    assert (intake_dir / "templates/demand_template.md").is_file()

def test_demand_analysis_is_self_contained_with_all_assets() -> None:
    """Assert analytics-demand-analysis has all required local scripts, references, examples, and templates."""
    analysis_dir = LIFECYCLE_ROOT / "analytics-demand-analysis"
    assert (analysis_dir / "scripts/dmp_mcp_client.py").is_file()
    assert (analysis_dir / "scripts/dataworks_lineage.py").is_file()
    assert (analysis_dir / "references/profiling_checklist.md").is_file()
    assert (analysis_dir / "references/MULTI_MODEL_MASKING_AUDIT.md").is_file()
    assert (analysis_dir / "references/analysis_assumptions_log.md").is_file()
    assert (analysis_dir / "examples/golden_profiling_and_caliber_lock.md").is_file()
    assert (analysis_dir / "templates/caliber_lock_template.md").is_file()

def test_data_solution_is_self_contained_with_all_assets() -> None:
    """Assert analytics-data-solution has all required local scripts, references, examples, and templates."""
    solution_dir = LIFECYCLE_ROOT / "analytics-data-solution"
    assert (solution_dir / "scripts/odps_sql_linter.py").is_file()
    assert (solution_dir / "references/ODPS_OPTIMIZATION_RULES.md").is_file()
    assert (solution_dir / "references/BATCH_ROLLOUT_REGRESSION_SOP.md").is_file()
    assert (solution_dir / "examples/golden_rfc_technical_design.md").is_file()
    assert (solution_dir / "templates/rfc_technical_design_template.md").is_file()
    assert (solution_dir / "templates/sql_solution_template.sql").is_file()
    # Assert domain blueprints are self-contained locally
    assert (solution_dir / "references/domain_blueprints/new_store_benefit_metrics_contract.md").is_file()
    assert (solution_dir / "references/domain_blueprints/new_store_assessment_rules_contract.md").is_file()
    assert (solution_dir / "references/domain_blueprints/o2o_store_benefit_reference.md").is_file()
    assert (solution_dir / "references/domain_blueprints/franchise_market_baseline_contract.md").is_file()

def test_data_execution_is_self_contained_with_all_assets() -> None:
    """Assert analytics-data-execution has required local scripts, references, and golden examples."""
    execution_dir = LIFECYCLE_ROOT / "analytics-data-execution"
    assert (execution_dir / "scripts/audit_execution_sanity.py").is_file()
    assert (execution_dir / "scripts/odps_quick_probe.py").is_file()
    assert (execution_dir / "references/DATA_QUALITY_CHECKLIST.md").is_file()
    assert (execution_dir / "examples/golden_execution_runner.py").is_file()

def test_result_delivery_is_self_contained_with_all_assets() -> None:
    """Assert analytics-result-delivery has required local scripts, references, and golden examples."""
    delivery_dir = LIFECYCLE_ROOT / "analytics-result-delivery"
    assert (delivery_dir / "scripts/wecom_sheet_driver.js").is_file()
    assert (delivery_dir / "scripts/portal_browser_sync.js").is_file()
    assert (delivery_dir / "references/wecom_sheet_patterns.md").is_file()
    assert (delivery_dir / "references/hpm_criteria.md").is_file()
    assert (delivery_dir / "templates/delivery_report_template.md").is_file()
    assert (delivery_dir / "examples/golden_delivery_report.md").is_file()
    # Assert sankey flow engine and visual contracts are self-contained
    assert (delivery_dir / "scripts/sankey_engine.py").is_file()
    assert (delivery_dir / "references/sankey_style_contract.md").is_file()
    assert (delivery_dir / "references/sankey_wording_templates.md").is_file()
    assert (delivery_dir / "references/DELIVERY_SYNTHESIS_REFERENCE.md").is_file()
def test_legacy_skills_functional_parity_and_coverage() -> None:
    """Assert all capabilities of legacy product-strategy skills are reachable through the 5 stages."""
    # Verify legacy skills exist and remain untouched as single source of truth for assets
    legacy_skills = [
        "odps-table-ingest",
        "dataworks-yoy-backfill",
        "ps-analytics",
        "ps-causal-evaluation",
        "ps-franchise-store-report",
        "o2o-store-benefit-report",
        "hpm-performance-review",
        "ps-new-store-benefit-report",
        "ps-reduction-scope-config-maintenance",
        "web-video-presentation-delivery",
        "odps-query-uv",
        "ps-portal-sync",
    ]
    for skill in legacy_skills:
        skill_dir = PRODUCT_STRATEGY_ROOT / skill
        assert (skill_dir / "SKILL.md").is_file(), f"Legacy asset skill missing: {skill}"

    # Verify stage mapping coverage across lifecycle:
    # Stage 3 owns domain solution blueprints (spec, formulas, models)
    solution_content = (LIFECYCLE_ROOT / "analytics-data-solution/SKILL.md").read_text(encoding="utf-8")
    assert "ps-new-store-benefit-report" in solution_content
    assert "o2o-store-benefit-report" in solution_content
    assert "ps-franchise-store-report" in solution_content
    assert "ps-causal-evaluation" in solution_content
    assert "ps-reduction-scope-config-maintenance" in solution_content

    # Stage 4 owns pure execution, data ingestion, backfill and verification
    execution_content = (LIFECYCLE_ROOT / "analytics-data-execution/SKILL.md").read_text(encoding="utf-8")
    assert "odps-table-ingest" in execution_content
    assert "dataworks-yoy-backfill" in execution_content
    assert "ps-reduction-scope-config-maintenance" in execution_content
    assert "audit_execution_sanity.py" in execution_content
    delivery_content = (LIFECYCLE_ROOT / "analytics-result-delivery/SKILL.md").read_text(encoding="utf-8")
    assert "ps-portal-sync" in delivery_content
    assert "hpm-performance-review" in delivery_content
    assert "web-video-presentation-delivery" in delivery_content

    analysis_content = (LIFECYCLE_ROOT / "analytics-demand-analysis/SKILL.md").read_text(encoding="utf-8")
    assert "dmp_mcp_client.py" in analysis_content
    assert "MULTI_MODEL_MASKING_AUDIT.md" in analysis_content


def test_underlying_analytics_unit_tests_pass() -> None:
    """Verify that existing unit test suites for underlying analytics tools continue to pass."""
    test_file = PRODUCT_STRATEGY_ROOT / "ps-analytics/scripts/test_analytics_skill.py"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-q"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"Underlying analytics tests failed: {result.stdout}\n{result.stderr}"
