"""Tests for Clash Merge.yaml template rendering."""

import os
import subprocess
import sys
import tempfile

import pytest

TEMPLATE = os.path.join(
    os.path.dirname(__file__), "..", "proxy", "clash", "Merge.yaml"
)
PRIVATE_ENV = os.path.join(
    os.path.dirname(__file__), "..", "..", "private", "clash", "Merge.env"
)
RENDER_SCRIPT = os.path.join(
    os.path.dirname(__file__), "..", "scripts", "render-clash-merge.py"
)


def run_render(dry_run=True):
    """Run the render script and return stdout."""
    args = ["python3", RENDER_SCRIPT]
    if dry_run:
        args.append("--dry-run")
    r = subprocess.run(args, capture_output=True, text=True)
    return r.stdout, r.stderr, r.returncode


# ── Unit: parse_env ─────────────────────────────────────────

def test_parse_env_single_values():
    """Single-line values are parsed correctly."""
    sys.path.insert(0, os.path.dirname(RENDER_SCRIPT))
    from importlib import import_module
    render = import_module("render-clash-merge")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("KEY_A=value_a\nKEY_B=value_b\n")
        f.flush()
        env = render.parse_env(f.name)
    os.unlink(f.name)

    assert env["KEY_A"] == "value_a"
    assert env["KEY_B"] == "value_b"


def test_parse_env_multiline_values():
    """Multi-line values (indented continuation) are joined with indent preserved."""
    sys.path.insert(0, os.path.dirname(RENDER_SCRIPT))
    from importlib import import_module
    render = import_module("render-clash-merge")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("RULES=\n  - line1\n  - line2\n  - line3\n")
        f.flush()
        env = render.parse_env(f.name)
    os.unlink(f.name)

    assert env["RULES"] == "  - line1\n  - line2\n  - line3"


def test_parse_env_skips_comments():
    """Comment lines are ignored."""
    sys.path.insert(0, os.path.dirname(RENDER_SCRIPT))
    from importlib import import_module
    render = import_module("render-clash-merge")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("# comment\nKEY=val\n# another\n")
        f.flush()
        env = render.parse_env(f.name)
    os.unlink(f.name)

    assert len(env) == 1
    assert env["KEY"] == "val"


# ── Unit: render_template ───────────────────────────────────

def test_render_substitutes_placeholders():
    """{{PLACEHOLDER}} is replaced with the env value."""
    sys.path.insert(0, os.path.dirname(RENDER_SCRIPT))
    from importlib import import_module
    render = import_module("render-clash-merge")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tf:
        tf.write("name: {{MY_NAME}}\nvalue: {{MY_VAL}}\n")
        tf.flush()
        result = render.render_template(tf.name, {"MY_NAME": "hello", "MY_VAL": "world"})
    os.unlink(tf.name)

    assert "hello" in result
    assert "world" in result
    assert "{{" not in result


def test_render_keeps_unknown_placeholders():
    """Unknown placeholders are left as-is."""
    sys.path.insert(0, os.path.dirname(RENDER_SCRIPT))
    from importlib import import_module
    render = import_module("render-clash-merge")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tf:
        tf.write("name: {{KNOWN}}\nother: {{UNKNOWN}}\n")
        tf.flush()
        result = render.render_template(tf.name, {"KNOWN": "ok"})
    os.unlink(tf.name)

    assert "ok" in result
    assert "{{UNKNOWN}}" in result


# ── Unit: multi-line indent ─────────────────────────────────

def _load_render():
    sys.path.insert(0, os.path.dirname(RENDER_SCRIPT))
    from importlib import import_module
    return import_module("render-clash-merge")


def test_multiline_dedented_and_reindented():
    """Multi-line env values: dedent then re-indent to placeholder column."""
    render = _load_render()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tf:
        # placeholder at 4 spaces (like fake-ip-filter)
        tf.write("list:\n    {{ITEMS}}\n")
        tf.flush()
        # env value with 2sp indent (as parse_env stores continuation lines)
        result = render.render_template(tf.name, {"ITEMS": "  - a\n  - b\n  - c"})
    os.unlink(tf.name)

    lines = result.strip().split("\n")
    assert lines == ["list:", "    - a", "    - b", "    - c"]


def test_multiline_at_col0():
    """Multi-line value at column 0 gets no extra indent."""
    render = _load_render()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tf:
        tf.write("{{ITEMS}}\n")
        tf.flush()
        result = render.render_template(tf.name, {"ITEMS": "  - x\n  - y"})
    os.unlink(tf.name)

    lines = result.strip().split("\n")
    assert lines == ["- x", "- y"]


def test_single_line_no_dedent():
    """Single-line values pass through unchanged."""
    render = _load_render()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tf:
        tf.write("val: {{X}}\n")
        tf.flush()
        result = render.render_template(tf.name, {"X": "hello"})
    os.unlink(tf.name)

    assert result == "val: hello\n"


def test_rendered_yaml_structure_valid():
    """Integration: rendered output passes yaml.safe_load + key structure."""
    yaml = pytest.importorskip("yaml")
    stdout, stderr, rc = run_render(dry_run=True)
    assert rc == 0, f"Render failed: {stderr}"

    d = yaml.safe_load(stdout)

    # fake-ip-filter is flat string list, no nested dicts
    fif = d["dns"]["fake-ip-filter"]
    assert all(isinstance(x, str) for x in fif), f"fake-ip-filter nested: {fif}"

    # rules is flat string list
    rules = d["rules"]
    assert all(isinstance(x, str) for x in rules), f"rules nested: {rules}"

    # proxy-providers has 3 entries
    assert len(d["proxy-providers"]) == 3


# ── Unit: check_unresolved ──────────────────────────────────

def test_check_unresolved_finds_remaining():
    assert render_check("{{LEFT}} and {{RIGHT}}") == ["LEFT", "RIGHT"]


def test_check_unresolved_empty():
    assert render_check("no placeholders here") == []


def render_check(content):
    sys.path.insert(0, os.path.dirname(RENDER_SCRIPT))
    from importlib import import_module
    render = import_module("render-clash-merge")
    return render.check_unresolved(content)


# ── Integration: real files ─────────────────────────────────

@pytest.mark.skipif(
    not os.path.exists(PRIVATE_ENV), reason="private/clash/Merge.env not found"
)
def test_template_has_placeholders():
    """Template file contains expected placeholders."""
    with open(TEMPLATE) as f:
        content = f.read()
    assert "{{PROVIDER_A_URL}}" in content
    assert "{{PROVIDER_A_NAME}}" in content
    assert "{{AI_FILTER}}" in content
    assert "{{RULES_PRIVATE}}" in content
    assert "{{FAKE_IP_FILTER_INTERNAL}}" in content


@pytest.mark.skipif(
    not os.path.exists(PRIVATE_ENV), reason="private/clash/Merge.env not found"
)
def test_private_env_has_required_keys():
    """Private env defines all required keys."""
    sys.path.insert(0, os.path.dirname(RENDER_SCRIPT))
    from importlib import import_module
    render = import_module("render-clash-merge")

    env = render.parse_env(PRIVATE_ENV)
    required = [
        "PROVIDER_A_NAME", "PROVIDER_A_URL", "PROVIDER_A_PREFIX",
        "PROVIDER_B_NAME", "PROVIDER_B_URL", "PROVIDER_B_PREFIX",
        "PROVIDER_C_NAME", "PROVIDER_C_URL", "PROVIDER_C_PREFIX",
        "AI_FILTER", "RULES_PRIVATE", "FAKE_IP_FILTER_INTERNAL",
    ]
    for key in required:
        assert key in env, f"Missing key: {key}"
        assert env[key], f"Empty value for: {key}"


@pytest.mark.skipif(
    not os.path.exists(PRIVATE_ENV), reason="private/clash/Merge.env not found"
)
def test_render_produces_valid_yaml():
    """Rendered output is valid YAML."""
    stdout, stderr, rc = run_render(dry_run=True)
    assert rc == 0, f"Render failed: {stderr}"

    # Minimal YAML check: has required top-level keys
    assert "proxy-providers:" in stdout
    assert "proxy-groups:" in stdout
    assert "dns:" in stdout
    assert "tun:" in stdout
    assert "rules:" in stdout


@pytest.mark.skipif(
    not os.path.exists(PRIVATE_ENV), reason="private/clash/Merge.env not found"
)
def test_render_no_unresolved_placeholders():
    """Rendered output has no unresolved {{PLACEHOLDERS}}."""
    stdout, stderr, rc = run_render(dry_run=True)
    assert rc == 0
    assert "{{" not in stdout, f"Unresolved placeholders in output"


@pytest.mark.skipif(
    not os.path.exists(PRIVATE_ENV), reason="private/clash/Merge.env not found"
)
def test_render_private_data_not_in_template():
    """Private data (URLs, tokens) is NOT in the template file."""
    with open(TEMPLATE) as f:
        template = f.read()

    # These should NOT appear in the template
    private_markers = [
        "handclap6764",        # subscription domain
        "token=",              # auth token
        "dslyy.com",           # company domain
        "msuai.top",           # personal domain
        "ctokai.com",          # internal domain
    ]
    for marker in private_markers:
        assert marker not in template, f"Private data '{marker}' found in template!"


@pytest.mark.skipif(
    not os.path.exists(PRIVATE_ENV), reason="private/clash/Merge.env not found"
)
def test_render_contains_process_rules():
    """Template contains process rules (public knowledge)."""
    with open(TEMPLATE) as f:
        template = f.read()
    assert "PROCESS-NAME-REGEX" in template
    assert "Claude" in template
    assert "chrome" in template.lower()
    assert "wget" in template


@pytest.mark.skipif(
    not os.path.exists(PRIVATE_ENV), reason="private/clash/Merge.env not found"
)
def test_render_contains_private_domains():
    """Rendered output contains private domains from env."""
    stdout, _, rc = run_render(dry_run=True)
    assert rc == 0
    assert "dslyy.com" in stdout
    assert "msuai.top" in stdout
