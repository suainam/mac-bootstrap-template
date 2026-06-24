"""End-to-end test: render Merge.yaml → validate structure + rule order."""

import os
import subprocess
import sys
import tempfile

import pytest

from helpers import PYTHON

yaml = pytest.importorskip("yaml")

RENDER_SCRIPT = os.path.join(
    os.path.dirname(__file__), "..", "scripts", "render-clash-merge.py"
)
PRIVATE_ENV = os.path.join(
    os.path.dirname(__file__), "..", "..", "private", "clash", "Merge.env"
)
WORKING_BACKUP = os.path.join(
    os.path.dirname(__file__), "..", "proxy", "clash", "Merge.yaml.working"
)


def render():
    """Run render script, return parsed YAML dict."""
    r = subprocess.run(
        [PYTHON, RENDER_SCRIPT, "--dry-run"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"Render failed: {r.stderr}"
    return yaml.safe_load(r.stdout), r.stdout


def rule_index(rules, pattern):
    """Find first rule containing pattern. Returns -1 if not found."""
    for i, r in enumerate(rules):
        if pattern in str(r):
            return i
    return -1


# ── Structure ────────────────────────────────────────────────

@pytest.mark.skipif(not os.path.exists(PRIVATE_ENV), reason="no private env")
def test_top_level_keys():
    d, _ = render()
    for k in ["proxy-providers", "proxy-groups", "dns", "tun", "rules", "profile"]:
        assert k in d, f"missing {k}"


@pytest.mark.skipif(not os.path.exists(PRIVATE_ENV), reason="no private env")
def test_fake_ip_filter_flat():
    """fake-ip-filter must be flat string list, no nesting."""
    d, _ = render()
    fif = d["dns"]["fake-ip-filter"]
    assert all(isinstance(x, str) for x in fif), f"nested: {fif}"


@pytest.mark.skipif(not os.path.exists(PRIVATE_ENV), reason="no private env")
def test_rules_flat():
    """rules must be flat string list."""
    d, _ = render()
    rules = d["rules"]
    assert all(isinstance(x, str) for x in rules), "rules contain non-string"


@pytest.mark.skipif(not os.path.exists(PRIVATE_ENV), reason="no private env")
def test_no_unresolved_placeholders():
    _, raw = render()
    assert "{{" not in raw, f"unresolved: {raw[raw.index('{{'):raw.index('{{')+30]}"


# ── Rule order ───────────────────────────────────────────────

@pytest.mark.skipif(not os.path.exists(PRIVATE_ENV), reason="no private env")
def test_rule_order():
    """Critical ordering: ads → LAN → private → AI → process → CN → udp → proxy-domains → MATCH."""
    d, _ = render()
    rules = d["rules"]

    idx = lambda p: rule_index(rules, p)
    assert idx("category-ads-all") < idx("127.0.0.0/8"), "ads before LAN"
    assert idx("127.0.0.0/8") < idx("dslyy.com"), "LAN before private"
    assert idx("dslyy.com") < idx("ai-services"), "private before AI"
    assert idx("ai-services") < idx("PROCESS-NAME-REGEX"), "AI before process"
    assert idx("PROCESS-NAME-REGEX") < idx("GEOSITE,CN"), "process before CN"
    assert idx("GEOSITE,CN") < idx("NETWORK,udp"), "CN before udp"
    assert idx("NETWORK,udp") < idx("proxy-domains"), "udp before proxy-domains"
    assert idx("proxy-domains") < idx("MATCH"), "proxy-domains before MATCH"


# ── Key rules present ────────────────────────────────────────

@pytest.mark.skipif(not os.path.exists(PRIVATE_ENV), reason="no private env")
def test_cn_catchall():
    """Must have DOMAIN-SUFFIX,cn for .cn fallback."""
    d, _ = render()
    rules = d["rules"]
    assert any("DOMAIN-SUFFIX,cn," in r for r in rules), "missing DOMAIN-SUFFIX,cn"


@pytest.mark.skipif(not os.path.exists(PRIVATE_ENV), reason="no private env")
def test_aliyun_explicit():
    """aliyun.com/aliyuncs.com explicit in rules."""
    d, _ = render()
    rules = d["rules"]
    assert any("aliyun.com" in r for r in rules)
    assert any("aliyuncs.com" in r for r in rules)


@pytest.mark.skipif(not os.path.exists(PRIVATE_ENV), reason="no private env")
def test_dns_config():
    """DNS has nameserver + fallback + respect-rules."""
    d, _ = render()
    dns = d["dns"]
    assert dns.get("respect-rules") is True
    assert len(dns.get("nameserver", [])) >= 2
    assert len(dns.get("fallback", [])) >= 2


@pytest.mark.skipif(not os.path.exists(PRIVATE_ENV), reason="no private env")
def test_tun_exclude():
    """tun.route-exclude-address has 172.16.0.0/12 for WSL2."""
    d, _ = render()
    addrs = d["tun"]["route-exclude-address"]
    assert "172.16.0.0/12" in addrs


# ── Diff against working backup ──────────────────────────────

@pytest.mark.skipif(not os.path.exists(WORKING_BACKUP), reason="no working backup")
def test_rules_match_working():
    """Rendered rules (ignoring comments) should have same core entries as working backup."""
    _, raw = render()
    with open(WORKING_BACKUP) as f:
        working = f.read()

    def clean(line):
        """Strip inline comments and normalize whitespace."""
        line = line.strip()
        if '#' in line:
            line = line[:line.index('#')].rstrip()
        return line

    rendered_rules = [clean(l) for l in raw.split("\n")
                      if l.strip().startswith("- ") and not l.strip().startswith("- #")]
    working_rules = [clean(l) for l in working.split("\n")
                     if l.strip().startswith("- ") and not l.strip().startswith("- #")]
    rendered_rules = [r for r in rendered_rules if r]
    working_rules = [r for r in working_rules if r]

    # Every working rule should appear in rendered (rendered may have extras)
    for rule in working_rules:
        # Skip DNS section rules that are in env, not template
        if any(k in rule for k in ["enable:", "ipv6:", "enhanced-mode:", "fake-ip-range:",
                                    "respect-rules:", "use-hosts:", "nameserver:", "fallback:",
                                    "geoip:", "geoip-code:"]):
            continue
        assert rule in rendered_rules, f"missing from rendered: {rule}"
