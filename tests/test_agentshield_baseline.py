from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from helpers import PYTHON, TEMPLATE


SCRIPT = Path(TEMPLATE) / "scripts" / "verify-agentshield-baseline.py"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_acknowledged_fingerprint_passes_without_exposing_evidence(tmp_path: Path) -> None:
    fingerprint = "rule::settings.json::private endpoint evidence"
    scan = tmp_path / "scan.json"
    baseline = tmp_path / "baseline.json"
    write_json(
        scan,
        {
            "findings": [
                {
                    "id": "rule",
                    "file": "settings.json",
                    "severity": "high",
                    "fingerprint": fingerprint,
                }
            ]
        },
    )
    write_json(
        baseline,
        {
            "version": 2,
            "acknowledged_findings": [
                {
                    "id": "rule",
                    "file": "settings.json",
                    "severity": "high",
                    "fingerprint_sha256": hashlib.sha256(fingerprint.encode()).hexdigest(),
                }
            ]
        },
    )

    result = subprocess.run([PYTHON, SCRIPT, scan, baseline], text=True, capture_output=True)

    assert result.returncode == 0
    assert result.stdout.strip() == "acknowledged=1"
    assert "private endpoint evidence" not in result.stdout


def test_changed_fingerprint_fails_with_rule_and_file_only(tmp_path: Path) -> None:
    scan = tmp_path / "scan.json"
    baseline = tmp_path / "baseline.json"
    write_json(
        scan,
        {
            "findings": [
                {
                    "id": "rule",
                    "file": "settings.json",
                    "severity": "critical",
                    "fingerprint": "new secret evidence",
                }
            ]
        },
    )
    write_json(baseline, {"version": 2, "acknowledged_findings": []})

    result = subprocess.run([PYTHON, SCRIPT, scan, baseline], text=True, capture_output=True)

    assert result.returncode == 1
    assert result.stdout.strip() == "new_or_changed id=rule file=settings.json severity=critical"
    assert "new secret evidence" not in result.stdout


def test_changed_severity_fails_even_when_fingerprint_is_unchanged(tmp_path: Path) -> None:
    fingerprint = "same evidence"
    scan = tmp_path / "scan.json"
    baseline = tmp_path / "baseline.json"
    write_json(
        scan,
        {
            "findings": [
                {
                    "id": "rule",
                    "file": "settings.json",
                    "severity": "critical",
                    "fingerprint": fingerprint,
                }
            ]
        },
    )
    write_json(
        baseline,
        {
            "version": 2,
            "acknowledged_findings": [
                {
                    "id": "rule",
                    "file": "settings.json",
                    "severity": "high",
                    "fingerprint_sha256": hashlib.sha256(fingerprint.encode()).hexdigest(),
                }
            ],
        },
    )

    result = subprocess.run([PYTHON, SCRIPT, scan, baseline], text=True, capture_output=True)

    assert result.returncode == 1
    assert "new_or_changed id=rule file=settings.json severity=critical" in result.stdout


def test_malformed_scan_fails_closed_without_traceback(tmp_path: Path) -> None:
    scan = tmp_path / "scan.json"
    baseline = tmp_path / "baseline.json"
    write_json(scan, {"findings": [{"id": "rule", "file": "settings.json"}]})
    write_json(baseline, {"version": 2, "acknowledged_findings": []})

    result = subprocess.run([PYTHON, SCRIPT, scan, baseline], text=True, capture_output=True)

    assert result.returncode == 2
    assert result.stdout.strip() == "invalid_scan_baseline"
    assert result.stderr == ""
    assert "Traceback" not in result.stdout


def test_untrusted_labels_cannot_inject_doctor_output(tmp_path: Path) -> None:
    scan = tmp_path / "scan.json"
    baseline = tmp_path / "baseline.json"
    write_json(
        scan,
        {
            "findings": [
                {
                    "id": "rule\nsecret evidence",
                    "file": "settings.json\nforged=OK",
                    "severity": "high",
                    "fingerprint": "changed",
                }
            ]
        },
    )
    write_json(baseline, {"version": 2, "acknowledged_findings": []})

    result = subprocess.run([PYTHON, SCRIPT, scan, baseline], text=True, capture_output=True)

    assert result.returncode == 1
    assert result.stdout.count("\n") == 1
    assert "secret evidence" not in result.stdout
    assert "forged=OK" not in result.stdout
