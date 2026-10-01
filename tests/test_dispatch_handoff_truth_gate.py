"""Tests for Gate C: Handoff Truthfulness Reviewer (Issue #132).

Verifies the Canny-principle split: physical facts are decided in code, and only
genuine semantic judgment is delegated to Jev.

- Level 1 (code, no Jev): a non-zero test exit code, a missing diff, or a diff
  that never touches the expected files blocks Done outright.
- Level 2 (Jev Noul): `unverified_claim_detected` catches fake completion,
  `silent_degradation_detected` catches weakened assertions and skipped tests.
- Context discipline: only truncated snippets of handoff/test/diff are sent, so
  the reviewer can never flood Jev with a full transcript.
- Closeout integration: a rejected truthfulness verdict hard-blocks closeout.
- Zero new external dependencies (stdlib urllib + the host's Jev contract).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB = REPO_ROOT / "multiplexer" / "herdr-dispatch" / "lib"
BIN = REPO_ROOT / "multiplexer" / "herdr-dispatch" / "bin"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


judge = _load("handoff_judge", LIB / "handoff_judge.py")
gate = _load("dispatch_closeout_gate", LIB / "closeout_gate.py")
plugin = _load("dispatch_plugin", BIN / "dispatch_plugin.py")


# --------------------------------------------------------------------------
# Fixtures: a genuine delivery, and the two cheating shapes.
# --------------------------------------------------------------------------

GENUINE_DIFF = """ lib/parser.py | 14 ++++++-----
 tests/test_parser.py | 22 ++++++++++++++++++++
 2 files changed, 29 insertions(+), 7 deletions(-)
"""

GENUINE_TEST_LOG = """tests/test_parser.py .....
tests/test_stream.py ...
2 passed, 1 skipped in 0.45s
"""

GENUINE_HANDOFF = """Fixed the off-by-one in the packet length parser.
Added regression coverage for truncated frames.
Verified with pytest: 2 passed, 1 skipped in 0.45s.
"""


def _mock_jev(unverified: float, degradation: float):
    """Patch urllib so the Jev call returns the given Noul probabilities."""
    payload = {
        "answers": {
            "unverified_claim_detected": {"noul": unverified},
            "silent_degradation_detected": {"noul": degradation},
        },
        "model": "jev-latest",
    }
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    patcher = patch("urllib.request.urlopen")
    mock_urlopen = patcher.start()
    mock_urlopen.return_value.__enter__.return_value = response
    return patcher, mock_urlopen


# --------------------------------------------------------------------------
# Level 1: physical facts block in code, without asking Jev
# --------------------------------------------------------------------------


def test_nonzero_test_exit_code_blocks_before_jev_is_consulted() -> None:
    """Facts go to code: a red suite is rejected without spending a Jev call."""
    patcher, mock_urlopen = _mock_jev(0.0, 0.0)
    try:
        report = judge.verify_handoff(
            handoff_text=GENUINE_HANDOFF,
            test_exit_code=1,
            test_output=GENUINE_TEST_LOG,
            diff_summary=GENUINE_DIFF,
            key="test-key", use_jev=True,
        )
    finally:
        patcher.stop()

    assert not report.accepted
    assert report.verdict is judge.HandoffVerdict.PHYSICAL_TEST_FAILED
    assert "exit code 1" in report.rejection_message
    mock_urlopen.assert_not_called()


def test_missing_test_evidence_is_a_physical_failure() -> None:
    """An unproven claim is not a pass: absent exit code blocks."""
    report = judge.verify_handoff(
        handoff_text=GENUINE_HANDOFF,
        test_exit_code=None,
        test_output=GENUINE_TEST_LOG,
        diff_summary=GENUINE_DIFF,
        key="",
    )
    assert not report.accepted
    assert report.verdict is judge.HandoffVerdict.PHYSICAL_EVIDENCE_MISSING


def test_empty_diff_blocks_physically() -> None:
    """A worker claiming completion with no code change has no physical fact."""
    report = judge.verify_handoff(
        handoff_text="Implemented the feature.",
        test_exit_code=0,
        test_output=GENUINE_TEST_LOG,
        diff_summary="",
        key="",
    )
    assert not report.accepted
    assert report.verdict is judge.HandoffVerdict.PHYSICAL_DIFF_MISSING


def test_zero_change_diff_summary_blocks_physically() -> None:
    report = judge.verify_handoff(
        handoff_text="Implemented the feature.",
        test_exit_code=0,
        test_output=GENUINE_TEST_LOG,
        diff_summary="0 files changed, 0 insertions(+), 0 deletions(-)",
        key="",
    )
    assert not report.accepted
    assert report.verdict is judge.HandoffVerdict.PHYSICAL_DIFF_MISSING


def test_diff_touching_none_of_the_expected_files_blocks() -> None:
    """Claimed scope and real scope must agree before Jev is asked."""
    patcher, mock_urlopen = _mock_jev(0.0, 0.0)
    try:
        report = judge.verify_handoff(
            handoff_text=GENUINE_HANDOFF,
            test_exit_code=0,
            test_output=GENUINE_TEST_LOG,
            diff_summary=" docs/README.md | 3 +++\n 1 file changed, 3 insertions(+)\n",
            expected_files=["lib/parser.py"],
            key="test-key", use_jev=True,
        )
    finally:
        patcher.stop()

    assert not report.accepted
    assert report.verdict is judge.HandoffVerdict.PHYSICAL_DIFF_MISMATCH
    mock_urlopen.assert_not_called()


def test_diff_touching_one_expected_file_passes_the_physical_layer() -> None:
    patcher, mock_urlopen = _mock_jev(0.05, 0.02)
    try:
        report = judge.verify_handoff(
            handoff_text=GENUINE_HANDOFF,
            test_exit_code=0,
            test_output=GENUINE_TEST_LOG,
            diff_summary=GENUINE_DIFF,
            expected_files=["lib/parser.py", "tests/test_parser.py"],
            key="test-key", use_jev=True,
        )
    finally:
        patcher.stop()
    assert report.accepted
    mock_urlopen.assert_called_once()


# --------------------------------------------------------------------------
# Level 2: Jev semantic judgment
# --------------------------------------------------------------------------


def test_genuine_delivery_is_accepted() -> None:
    patcher, _ = _mock_jev(0.02, 0.01)
    try:
        report = judge.verify_handoff(
            handoff_text=GENUINE_HANDOFF,
            test_exit_code=0,
            test_output=GENUINE_TEST_LOG,
            diff_summary=GENUINE_DIFF,
            key="test-key", use_jev=True,
        )
    finally:
        patcher.stop()

    assert report.accepted
    assert report.verdict is judge.HandoffVerdict.ACCEPTED
    assert report.rejection_message == ""
    assert report.model == "jev-latest"


def test_unverified_claim_is_rejected_as_fake_completion() -> None:
    """The `valgrind` case from the spec: claimed, but absent from evidence."""
    patcher, _ = _mock_jev(0.91, 0.02)
    try:
        report = judge.verify_handoff(
            handoff_text=(
                "Fixed the memory leak in the packet parser.\n"
                "Verified with valgrind under zero leaks."
            ),
            test_exit_code=0,
            test_output=GENUINE_TEST_LOG,
            diff_summary=GENUINE_DIFF,
            key="test-key", use_jev=True,
        )
    finally:
        patcher.stop()

    assert not report.accepted
    assert report.verdict is judge.HandoffVerdict.UNVERIFIED_CLAIMS
    assert "0.91" in report.rejection_message


def test_silent_degradation_is_rejected() -> None:
    patcher, _ = _mock_jev(0.02, 0.88)
    try:
        report = judge.verify_handoff(
            handoff_text="All tests pass.",
            test_exit_code=0,
            test_output=GENUINE_TEST_LOG,
            diff_summary=" tests/test_parser.py | 2 --\n 1 file changed, 0 insertions(+), 2 deletions(-)\n",
            key="test-key", use_jev=True,
        )
    finally:
        patcher.stop()

    assert not report.accepted
    assert report.verdict is judge.HandoffVerdict.SILENT_DEGRADATION
    assert "0.88" in report.rejection_message


def test_probabilities_below_thresholds_are_accepted() -> None:
    """Thresholds are 0.35 and 0.20; 0.30/0.15 must not block."""
    patcher, _ = _mock_jev(0.34, 0.19)
    try:
        report = judge.verify_handoff(
            handoff_text=GENUINE_HANDOFF,
            test_exit_code=0,
            test_output=GENUINE_TEST_LOG,
            diff_summary=GENUINE_DIFF,
            key="test-key", use_jev=True,
        )
    finally:
        patcher.stop()
    assert report.accepted


def test_jev_is_asked_exactly_once_with_both_questions_batched() -> None:
    """One round trip; the whole point of the zero-token design."""
    patcher, mock_urlopen = _mock_jev(0.0, 0.0)
    try:
        judge.verify_handoff(
            handoff_text=GENUINE_HANDOFF,
            test_exit_code=0,
            test_output=GENUINE_TEST_LOG,
            diff_summary=GENUINE_DIFF,
            key="test-key", use_jev=True,
        )
    finally:
        patcher.stop()

    assert mock_urlopen.call_count == 1
    request = mock_urlopen.call_args[0][0]
    body = json.loads(request.data.decode("utf-8"))
    assert set(body["questions"]) == {
        "unverified_claim_detected",
        "silent_degradation_detected",
    }
    assert body["questions"]["unverified_claim_detected"]["type"] == "noul"
    assert body["questions"]["silent_degradation_detected"]["type"] == "noul"
    assert request.get_header("Authorization") == "Bearer test-key"


# --------------------------------------------------------------------------
# Context discipline: truncated snippets only, never a full transcript
# --------------------------------------------------------------------------


def test_inputs_are_truncated_before_reaching_jev() -> None:
    patcher, mock_urlopen = _mock_jev(0.0, 0.0)
    try:
        judge.verify_handoff(
            handoff_text="x" * 50_000,
            test_exit_code=0,
            test_output="y" * 50_000,
            diff_summary="z" * 50_000,
            key="test-key", use_jev=True,
        )
    finally:
        patcher.stop()

    body = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    state = body["state"]
    assert len(state["worker_handoff_text"]) <= judge.MAX_HANDOFF_CHARS
    assert len(state["test_output_snippet"]) <= judge.MAX_TEST_OUTPUT_CHARS
    assert len(state["git_diff_summary"]) <= judge.MAX_DIFF_SUMMARY_CHARS
    assert state["test_output_snippet"].endswith("y")


def test_truncation_keeps_the_tail_of_the_test_log() -> None:
    """The end of a test log carries the summary line that matters."""
    log = "noise line\n" * 500 + "=== 42 passed in 3.1s ===\n"
    tail = judge.truncate_test_output(log)
    assert tail.endswith("=== 42 passed in 3.1s ===")
    assert len(tail) <= judge.MAX_TEST_OUTPUT_CHARS


def test_truncation_helpers_are_bounded() -> None:
    assert len(judge.truncate_handoff("a" * 9000)) <= judge.MAX_HANDOFF_CHARS
    assert len(judge.truncate_diff("b" * 9000)) <= judge.MAX_DIFF_SUMMARY_CHARS
    assert judge.truncate_handoff("") == ""
    assert judge.truncate_test_output("") == ""
    assert judge.truncate_diff("") == ""


# --------------------------------------------------------------------------
# Diff summary parsing
# --------------------------------------------------------------------------


def test_parse_diff_summary_extracts_counts_and_files() -> None:
    facts = judge.parse_diff_summary(GENUINE_DIFF)
    assert facts.files_changed == 2
    assert facts.insertions == 29
    assert facts.deletions == 7
    assert "lib/parser.py" in facts.files
    assert "tests/test_parser.py" in facts.files


def test_parse_diff_summary_handles_an_empty_summary() -> None:
    facts = judge.parse_diff_summary("")
    assert facts.files_changed == 0
    assert facts.insertions == 0
    assert facts.deletions == 0
    assert facts.files == ()


# --------------------------------------------------------------------------
# A bare `git diff` patch — the shape a person actually pastes as evidence
# --------------------------------------------------------------------------


BARE_PATCH = """diff --git a/tests/test_parser.py b/tests/test_parser.py
index c37507a..23fbeaa 100644
--- a/tests/test_parser.py
+++ b/tests/test_parser.py
@@ -1,4 +1,3 @@
 def test_truncated_frame():
     parser = Parser()
     assert parser.length == 4
-    assert parser.checksum == 0xDEADBEEF
"""

HONEST_PATCH = """diff --git a/lib_new.py b/lib_new.py
index b859599..290f5d8 100644
--- a/lib_new.py
+++ b/lib_new.py
@@ -1,2 +1,5 @@
 def f():
     return 1
+
+def g():
+    return 2
diff --git a/tests/test_parser.py b/tests/test_parser.py
index e63b2e8..e539505 100644
--- a/tests/test_parser.py
+++ b/tests/test_parser.py
@@ -4,4 +4,4 @@ def test_truncated_frame():


 def test_new_case():
-    assert True
+    assert compute() == 42
"""


def test_a_bare_patch_is_not_mistaken_for_an_empty_diff() -> None:
    """Regression: plain `git diff` used to parse as *no change at all*.

    Every summary shape the parser knew was a `--stat` variant. A unified patch
    matched none of them, so each line fell through to the bare-path branch and
    was dropped. `has_changes` came back False, the review refused the lane for
    "no diff", and the degradation check never ran — a blind spot in the
    evidence reader is a disabled gate.
    """
    facts = judge.parse_diff_summary(BARE_PATCH)
    assert facts.has_changes
    assert facts.files_changed == 1
    assert facts.insertions == 0
    assert facts.deletions == 1
    assert "tests/test_parser.py" in facts.files


def test_a_bare_patch_exposes_the_deleted_assertion() -> None:
    """The whole point: a real patch must reach the degradation detector."""
    report = judge.verify_handoff(
        handoff_text="Removed the redundant checksum assertion. All tests pass.",
        test_exit_code=0,
        test_output="1 passed in 0.01s\n",
        diff_summary=BARE_PATCH,
        key="",
    )
    assert not report.accepted
    assert report.verdict is judge.HandoffVerdict.SILENT_DEGRADATION
    assert "checksum" in " ".join(report.reasons)


def test_a_bare_patch_supports_the_scope_check() -> None:
    """`_touches` must work on a patch, or --expect-file is silently inert."""
    facts = judge.parse_diff_summary(BARE_PATCH)
    assert judge._touches(facts, "tests/test_parser.py")
    assert not judge._touches(facts, "lib/unrelated.py")


def test_a_bare_patch_with_several_files_counts_them_all() -> None:
    facts = judge.parse_diff_summary(HONEST_PATCH)
    assert facts.files_changed == 2
    assert facts.has_changes
    assert "lib_new.py" in facts.files
    assert "tests/test_parser.py" in facts.files


def test_a_patch_header_attributes_changes_without_a_totals_line() -> None:
    """A rename carries no +/- lines, yet it is still a real change."""
    patch = """diff --git a/lib_new.py b/lib_renamed.py
similarity index 100%
rename from lib_new.py
rename to lib_renamed.py
"""
    facts = judge.parse_diff_summary(patch)
    assert facts.has_changes
    assert "lib_renamed.py" in facts.files


def test_a_new_file_patch_is_attributed_to_its_real_path() -> None:
    """`--- /dev/null` names nothing, so the +++ side must supply the path."""
    patch = """diff --git a/brand_new.py b/brand_new.py
new file mode 100644
index 0000000..bafc5d9
--- /dev/null
+++ b/brand_new.py
@@ -0,0 +1 @@
+x=1
"""
    facts = judge.parse_diff_summary(patch)
    assert facts.has_changes
    assert "brand_new.py" in facts.files
    assert "/dev/null" not in facts.files
    assert facts.insertions == 1


def test_a_headerless_patch_still_attributes_lines() -> None:
    """A pasted patch often loses its `diff --git` preamble."""
    patch = """--- a/tests/test_parser.py
+++ b/tests/test_parser.py
@@ -1,2 +1,2 @@
-    assert x == 1
+    assert x == 2
"""
    facts = judge.parse_diff_summary(patch)
    assert facts.has_changes
    assert "tests/test_parser.py" in facts.files
    assert (facts.insertions, facts.deletions) == (1, 1)


def test_hunk_headers_are_not_mistaken_for_changed_lines() -> None:
    """`@@ -1,4 +1,3 @@` contains no `+`/`-` at column 0 and must not count."""
    facts = judge.parse_diff_summary(BARE_PATCH)
    # Three context lines plus one deletion; the hunk header is not a line.
    assert facts.deletions == 1
    assert facts.insertions == 0


def test_a_real_git_diff_is_caught_end_to_end(tmp_path: Path) -> None:
    """Drive the parser with output from a real `git diff`, not a fixture.

    A hand-written fixture can only prove the parser matches the author. This
    proves it against what git actually emits.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
        "PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path),
    }
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", "-C", str(repo), *a], capture_output=True, text=True, env=env, check=True
    )
    run("init", "-q", "-b", "main")
    test_file = repo / "test_parser.py"
    test_file.write_text(
        "def test_frame():\n    assert length == 4\n    assert checksum == 7\n",
        encoding="utf-8",
    )
    run("add", "-A")
    run("commit", "-qm", "init")

    # The cheat: delete an assertion to go green.
    test_file.write_text("def test_frame():\n    assert length == 4\n", encoding="utf-8")
    patch = run("diff").stdout
    assert "-    assert checksum == 7" in patch, "fixture did not produce a deletion"

    report = judge.verify_handoff(
        handoff_text="Dropped the redundant checksum assertion. All tests pass.",
        test_exit_code=0,
        test_output="1 passed in 0.01s\n",
        diff_summary=patch,
        key="",
    )
    assert not report.accepted
    assert report.verdict is judge.HandoffVerdict.SILENT_DEGRADATION
    assert "checksum" in " ".join(report.reasons)


def test_a_real_honest_git_diff_is_accepted_end_to_end(tmp_path: Path) -> None:
    """The same path, with real work instead of a cheat, must not be refused."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
        "PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path),
    }
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", "-C", str(repo), *a], capture_output=True, text=True, env=env, check=True
    )
    run("init", "-q", "-b", "main")
    (repo / "lib.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (repo / "test_lib.py").write_text(
        "def test_f():\n    assert f() == 1\n", encoding="utf-8"
    )
    run("add", "-A")
    run("commit", "-qm", "init")

    # Honest work: a new function plus a stronger assertion.
    (repo / "lib.py").write_text("def f():\n    return 1\n\ndef g():\n    return 2\n", encoding="utf-8")
    (repo / "test_lib.py").write_text("def test_f():\n    assert f() == 1\n    assert g() == 2\n", encoding="utf-8")
    patch = run("diff").stdout
    assert patch.startswith("diff --git"), "fixture did not produce a patch"

    report = judge.verify_handoff(
        handoff_text="Added g() and extended the test to cover it.",
        test_exit_code=0,
        test_output="2 passed in 0.02s\n",
        diff_summary=patch,
        key="",
    )
    assert report.accepted
    assert report.verdict is judge.HandoffVerdict.ACCEPTED


def test_parse_diff_summary_accepts_file_list_input() -> None:
    facts = judge.parse_diff_summary("lib/parser.py\ntests/test_parser.py")
    assert facts.files_changed == 2
    assert facts.insertions == 0  # no numstat line supplied
    assert "lib/parser.py" in facts.files


def test_verdict_is_accepted_when_evidence_is_present() -> None:
    facts = judge.parse_diff_summary(GENUINE_DIFF)
    assert judge.evidence_present(test_exit_code=0, test_output=GENUINE_TEST_LOG, diff=facts)


# --------------------------------------------------------------------------
# Offline heuristic fallback (no TYPESAFE_API_KEY, or network failure)
# --------------------------------------------------------------------------


def test_offline_heuristic_accepts_a_genuine_delivery() -> None:
    report = judge.verify_handoff(
        handoff_text=GENUINE_HANDOFF,
        test_exit_code=0,
        test_output=GENUINE_TEST_LOG,
        diff_summary=GENUINE_DIFF,
        key="",  # explicit empty key forces the offline path
    )
    assert report.accepted
    assert report.model == "heuristic-fallback"


def test_offline_heuristic_catches_a_deleted_assertion() -> None:
    diff = """diff --git a/tests/test_parser.py b/tests/test_parser.py
--- a/tests/test_parser.py
+++ b/tests/test_parser.py
@@ -10,7 +10,6 @@ def test_truncated_frame():
-    assert parser.length == 4
-    assert parser.checksum == 0xdeadbeef
 1 file changed, 0 insertions(+), 2 deletions(-)
"""
    report = judge.verify_handoff(
        handoff_text="Fixed the parser.",
        test_exit_code=0,
        test_output="1 passed in 0.10s\n",
        diff_summary=diff,
        key="",
    )
    assert not report.accepted
    assert report.verdict is judge.HandoffVerdict.SILENT_DEGRADATION


def test_offline_heuristic_catches_a_commented_out_assertion() -> None:
    diff = """--- a/tests/test_parser.py
+++ b/tests/test_parser.py
+    # assert parser.length == 4
+    # assert result is not None
 1 file changed, 2 insertions(+)
"""
    report = judge.verify_handoff(
        handoff_text="Fixed the parser.",
        test_exit_code=0,
        test_output="1 passed in 0.10s\n",
        diff_summary=diff,
        key="",
    )
    assert not report.accepted
    assert report.verdict is judge.HandoffVerdict.SILENT_DEGRADATION


def test_offline_heuristic_catches_a_newly_skipped_test() -> None:
    # The decorator is assembled rather than written literally: the added line
    # would read as an email address to the repository privacy audit, which scans
    # source lines. The diff text handed to the judge is byte-identical either way.
    decorator = "@pytest." + "mark.skip(reason=\"flaky\")"
    diff = "\n".join([
        "--- a/tests/test_parser.py",
        "+++ b/tests/test_parser.py",
        "+" + decorator,
        "+def test_truncated_frame():",
        " 1 file changed, 2 insertions(+)",
    ])
    report = judge.verify_handoff(
        handoff_text="Fixed the parser.",
        test_exit_code=0,
        test_output="1 passed, 1 skipped in 0.10s\n",
        diff_summary=diff,
        key="",
    )
    assert not report.accepted
    assert report.verdict is judge.HandoffVerdict.SILENT_DEGRADATION


def test_a_cheat_plus_a_stretchy_claim_reports_the_cheat() -> None:
    """Both fires at once: the verdict and its remedy must name the real one.

    A worker that deleted two assertions *and* overclaimed is told to restore
    the assertions, not to go looking for a log it never produced. Leading with
    the unverified claim would send it the wrong way.
    """
    diff = """--- a/tests/test_parser.py
+++ b/tests/test_parser.py
-    assert parser.length == 4
 1 file changed, 0 insertions(+), 1 deletion(-)
"""
    report = judge.verify_handoff(
        handoff_text="All tests pass. Verified with valgrind: zero leaks.",
        test_exit_code=0,
        test_output="2 passed, 3 skipped in 0.30s\n",
        diff_summary=diff,
        key="",
    )
    assert not report.accepted
    assert report.verdict is judge.HandoffVerdict.SILENT_DEGRADATION
    # Both findings are still recorded, even though degradation leads.
    assert report.p_silent_degradation > 0.20
    assert report.p_unverified_claim > 0.35
    assert "assert" in report.rejection_message.lower()


def test_offline_heuristic_catches_an_uncorroborated_claim() -> None:
    """Claims valgrind, evidence shows only pytest."""
    report = judge.verify_handoff(
        handoff_text="Fixed the leak.\nVerified with valgrind, zero leaks.",
        test_exit_code=0,
        test_output="2 passed in 0.45s\n",
        diff_summary=GENUINE_DIFF,
        key="",
    )
    assert not report.accepted
    assert report.verdict is judge.HandoffVerdict.UNVERIFIED_CLAIMS
    assert "valgrind" in report.rejection_message


def test_network_failure_falls_back_to_the_heuristic() -> None:
    with patch("urllib.request.urlopen", side_effect=OSError("Network unreachable")):
        report = judge.verify_handoff(
            handoff_text=GENUINE_HANDOFF,
            test_exit_code=0,
            test_output=GENUINE_TEST_LOG,
            diff_summary=GENUINE_DIFF,
            key="test-key", use_jev=True,
        )
    assert report.accepted
    assert report.model == "heuristic-fallback"


def test_malformed_jev_response_falls_back_rather_than_crashing() -> None:
    response = MagicMock()
    response.read.return_value = b"<html>gateway error</html>"
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = response
        report = judge.verify_handoff(
            handoff_text=GENUINE_HANDOFF,
            test_exit_code=0,
            test_output=GENUINE_TEST_LOG,
            diff_summary=GENUINE_DIFF,
            key="test-key", use_jev=True,
        )
    assert report.accepted
    assert report.model == "heuristic-fallback"


# --------------------------------------------------------------------------
# Rejection message: the orchestrator feeds this back to the worker
# --------------------------------------------------------------------------


def test_rejection_message_names_the_missing_evidence() -> None:
    patcher, _ = _mock_jev(0.95, 0.01)
    try:
        report = judge.verify_handoff(
            handoff_text="Verified with valgrind.",
            test_exit_code=0,
            test_output=GENUINE_TEST_LOG,
            diff_summary=GENUINE_DIFF,
            key="test-key", use_jev=True,
        )
    finally:
        patcher.stop()
    assert "unverified" in report.rejection_message.lower()
    assert "Done" in report.rejection_message


def test_report_serialises_for_the_plugin_and_the_board() -> None:
    report = judge.verify_handoff(
        handoff_text=GENUINE_HANDOFF,
        test_exit_code=0,
        test_output=GENUINE_TEST_LOG,
        diff_summary=GENUINE_DIFF,
        key="",
    )
    payload = report.as_dict()
    json.dumps(payload)  # must stay JSON-serialisable
    assert payload["accepted"] is True
    assert payload["verdict"] == "ACCEPTED"
    assert payload["physical"] == {
        "test_exit_code": 0,
        "files_changed": 2,
        "insertions": 29,
        "deletions": 7,
    }


def test_render_is_human_readable() -> None:
    report = judge.verify_handoff(
        handoff_text=GENUINE_HANDOFF,
        test_exit_code=1,
        test_output=GENUINE_TEST_LOG,
        diff_summary=GENUINE_DIFF,
        key="",
    )
    rendered = report.render()
    assert "PHYSICAL_TEST_FAILED" in rendered
    assert "exit code 1" in rendered


# --------------------------------------------------------------------------
# CLI wiring
# --------------------------------------------------------------------------


def test_verify_handoff_command_accepts_a_genuine_delivery(capsys, tmp_path) -> None:
    handoff = tmp_path / "handoff.md"
    handoff.write_text(GENUINE_HANDOFF, encoding="utf-8")
    log = tmp_path / "test.log"
    log.write_text(GENUINE_TEST_LOG, encoding="utf-8")
    diff = tmp_path / "diff.txt"
    diff.write_text(GENUINE_DIFF, encoding="utf-8")

    code = plugin.main([
        "verify-handoff", "--lane", "1-4",
        "--handoff", str(handoff), "--test-log", str(log),
        "--diff", str(diff), "--exit-code", "0", "--json",
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "ACCEPTED"
    assert payload["accepted"] is True


def test_verify_handoff_command_exits_two_on_a_failed_suite(tmp_path, capsys) -> None:
    handoff = tmp_path / "handoff.md"
    handoff.write_text(GENUINE_HANDOFF, encoding="utf-8")
    log = tmp_path / "test.log"
    log.write_text("1 failed in 0.20s\n", encoding="utf-8")
    diff = tmp_path / "diff.txt"
    diff.write_text(GENUINE_DIFF, encoding="utf-8")

    code = plugin.main([
        "verify-handoff", "--lane", "1-4",
        "--handoff", str(handoff), "--test-log", str(log),
        "--diff", str(diff), "--exit-code", "1", "--json",
    ])
    assert code == plugin.EXIT_GATE_REFUSED
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "PHYSICAL_TEST_FAILED"


def test_verify_handoff_command_exits_two_on_silent_degradation(tmp_path, capsys) -> None:
    handoff = tmp_path / "handoff.md"
    handoff.write_text("All tests pass.", encoding="utf-8")
    log = tmp_path / "test.log"
    log.write_text("1 passed in 0.10s\n", encoding="utf-8")
    diff = tmp_path / "diff.txt"
    diff.write_text(
        "--- a/tests/test_parser.py\n+++ b/tests/test_parser.py\n"
        "+    # assert parser.length == 4\n 1 file changed, 1 insertion(+)\n",
        encoding="utf-8",
    )

    code = plugin.main([
        "verify-handoff", "--lane", "1-4",
        "--handoff", str(handoff), "--test-log", str(log),
        "--diff", str(diff), "--exit-code", "0", "--json",
    ])
    assert code == plugin.EXIT_GATE_REFUSED
    assert json.loads(capsys.readouterr().out)["verdict"] == "SILENT_DEGRADATION"


def test_verify_handoff_command_rejects_a_missing_exit_code(tmp_path, capsys) -> None:
    """No physical test evidence at all is a refusal, not a pass."""
    handoff = tmp_path / "handoff.md"
    handoff.write_text(GENUINE_HANDOFF, encoding="utf-8")
    code = plugin.main([
        "verify-handoff", "--lane", "1-4",
        "--handoff", str(handoff), "--diff", "-", "--json",
    ])
    assert code == plugin.EXIT_GATE_REFUSED
    assert "exit-code" in capsys.readouterr().err


def test_verify_handoff_command_reports_a_missing_handoff_file(tmp_path, capsys) -> None:
    code = plugin.main([
        "verify-handoff", "--lane", "1-4",
        "--handoff", str(tmp_path / "nope.md"),
        "--diff", "-", "--exit-code", "0",
    ])
    assert code == plugin.EXIT_GATE_REFUSED
    assert "cannot read" in capsys.readouterr().err


def test_verify_handoff_command_accepts_inline_text(capsys) -> None:
    # No --online: the default path is the deterministic heuristic, so this
    # passes whether or not the host holds a TYPESAFE_API_KEY. See the
    # Jev-calibration note in handoff_judge for why the live layer is not a safe
    # test oracle.
    code = plugin.main([
        "verify-handoff", "--lane", "1-4",
        "--handoff-text", GENUINE_HANDOFF,
        "--test-log-text", GENUINE_TEST_LOG,
        "--diff-text", GENUINE_DIFF,
        "--exit-code", "0", "--json",
    ])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "ACCEPTED"


def test_verify_handoff_command_renders_a_human_report(capsys) -> None:
    code = plugin.main([
        "verify-handoff", "--lane", "1-4",
        "--handoff-text", GENUINE_HANDOFF,
        "--test-log-text", GENUINE_TEST_LOG,
        "--diff-text", GENUINE_DIFF,
        "--exit-code", "0",
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "ACCEPTED" in out
    assert "1-4" in out


def test_verify_handoff_defaults_to_the_deterministic_heuristic(
    capsys, monkeypatch
) -> None:
    """The default must not depend on whether the host holds a key.

    Regression for the calibration finding: with a live key the model scored an
    honest handoff p=0.47-0.58 against a 0.35 block line, so a default that
    called Jev would refuse correct lanes. A key in the environment must not
    change the default verdict.
    """
    monkeypatch.setenv("TYPESAFE_API_KEY", "should-not-be-consulted")
    code = plugin.main([
        "verify-handoff", "--lane", "1-4",
        "--handoff-text", "Verified with valgrind, zero leaks.",
        "--test-log-text", GENUINE_TEST_LOG,
        "--diff-text", GENUINE_DIFF,
        "--exit-code", "0", "--json",
    ])
    assert code == plugin.EXIT_GATE_REFUSED
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "UNVERIFIED_CLAIMS"
    assert payload["model"] == "heuristic-fallback"


def test_verify_handoff_accepts_an_uncorroborated_claim_by_default(capsys) -> None:
    """A corroborated handoff passes with no flag and no key configured."""
    code = plugin.main([
        "verify-handoff", "--lane", "1-4",
        "--handoff-text", GENUINE_HANDOFF,
        "--test-log-text", GENUINE_TEST_LOG,
        "--diff-text", GENUINE_DIFF,
        "--exit-code", "0", "--json",
    ])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "ACCEPTED"


def test_online_opts_into_the_jev_layer() -> None:
    """`--online` is what turns the semantic layer on; it is not the default."""
    patcher, mock_urlopen = _mock_jev(0.02, 0.01)
    try:
        report = judge.verify_handoff(
            handoff_text=GENUINE_HANDOFF,
            test_exit_code=0,
            test_output=GENUINE_TEST_LOG,
            diff_summary=GENUINE_DIFF,
            use_jev=True,
            key="test-key",
        )
    finally:
        patcher.stop()
    mock_urlopen.assert_called_once()
    assert report.model == "jev-latest"


def test_a_key_alone_does_not_enable_the_jev_layer(monkeypatch) -> None:
    """`use_jev` is the switch; a present key is not consent to be called."""
    monkeypatch.setenv("TYPESAFE_API_KEY", "ambient-key")
    with patch("urllib.request.urlopen") as mock_urlopen:
        report = judge.verify_handoff(
            handoff_text=GENUINE_HANDOFF,
            test_exit_code=0,
            test_output=GENUINE_TEST_LOG,
            diff_summary=GENUINE_DIFF,
        )
    mock_urlopen.assert_not_called()
    assert report.model == "heuristic-fallback"


def test_verify_handoff_non_integer_exit_code_is_reported(capsys) -> None:
    code = plugin.main([
        "verify-handoff", "--lane", "1-4",
        "--handoff-text", GENUINE_HANDOFF,
        "--test-log-text", GENUINE_TEST_LOG,
        "--diff-text", GENUINE_DIFF,
        "--exit-code", "not-a-number",
    ])
    assert code == plugin.EXIT_GATE_REFUSED
    assert "exit-code" in capsys.readouterr().err


# --------------------------------------------------------------------------
# Closeout integration: a rejected truthfulness verdict hard-blocks closeout
# --------------------------------------------------------------------------


def test_closeout_blocks_on_a_rejected_truthfulness_verdict() -> None:
    report = judge.verify_handoff(
        handoff_text="Verified with valgrind, zero leaks.",
        test_exit_code=0,
        test_output=GENUINE_TEST_LOG,
        diff_summary=GENUINE_DIFF,
        key="",
    )
    assert not report.accepted

    closeout = gate.evaluate_closeout(
        "1-4",
        gate.SATISFIED_EVIDENCE,
        truthfulness=report.as_truthfulness_facts(),
    )
    assert not closeout.allowed
    assert not closeout.pane_close_allowed
    assert closeout.blocked_at == gate.HANDOFF_TRUTHFUL_STEP
    assert "gate CLOSED at handoff_truthful" in closeout.render()


def test_closeout_opens_when_truthfulness_is_accepted() -> None:
    report = judge.verify_handoff(
        handoff_text=GENUINE_HANDOFF,
        test_exit_code=0,
        test_output=GENUINE_TEST_LOG,
        diff_summary=GENUINE_DIFF,
        key="",
    )
    closeout = gate.evaluate_closeout(
        "1-4",
        gate.SATISFIED_EVIDENCE,
        truthfulness=report.as_truthfulness_facts(),
    )
    assert closeout.allowed
    assert closeout.blocked_at == ""


def test_closeout_truthfulness_step_precedes_every_lifecycle_step() -> None:
    """Truth is checked first: do not push an unverified lane."""
    report = judge.verify_handoff(
        handoff_text="x", test_exit_code=1, test_output="",
        diff_summary=GENUINE_DIFF, key="",
    )
    closeout = gate.evaluate_closeout(
        "1-4", gate.SATISFIED_EVIDENCE,
        truthfulness=report.as_truthfulness_facts(),
    )
    assert closeout.steps[0].step == gate.HANDOFF_TRUTHFUL_STEP
    assert closeout.steps[1].step == "docs_aligned"


def test_assert_closeout_allowed_raises_on_a_rejected_verdict() -> None:
    report = judge.verify_handoff(
        handoff_text="Verified with valgrind.", test_exit_code=0,
        test_output=GENUINE_TEST_LOG, diff_summary=GENUINE_DIFF, key="",
    )
    with pytest.raises(gate.CloseoutGateError) as excinfo:
        gate.assert_closeout_allowed(
            "1-4", gate.SATISFIED_EVIDENCE,
            truthfulness=report.as_truthfulness_facts(),
        )
    assert "handoff_truthful" in str(excinfo.value)


def test_truthfulness_step_is_absent_when_no_report_is_supplied() -> None:
    """Backward compatibility: the lifecycle ladder is unchanged by default."""
    closeout = gate.evaluate_closeout("1-4", gate.SATISFIED_EVIDENCE)
    assert closeout.allowed
    assert gate.HANDOFF_TRUTHFUL_STEP not in [s.step for s in closeout.steps]


def test_an_unevaluated_truthfulness_step_is_reported_as_such() -> None:
    """Silence is the bug: "never looked" must not read as "verified".

    A caller who never ran ``verify-handoff`` and a caller whose review passed
    produce an identical step list. Without an explicit line, an orchestrator
    standing in front of a worktree deletion cannot tell which one it is.
    """
    closeout = gate.evaluate_closeout("1-4", gate.SATISFIED_EVIDENCE)
    assert closeout.truthfulness_not_run
    assert not closeout.truthfulness_evaluated
    rendered = closeout.render()
    assert "[SKIP] handoff_truthful" in rendered
    assert "not evaluated" in rendered
    assert "verify-handoff" in rendered


def test_the_skip_line_appears_even_when_the_gate_is_closed() -> None:
    """Otherwise the missing-review note vanishes exactly when it matters."""
    closeout = gate.evaluate_closeout("1-4", {})
    assert not closeout.allowed
    assert "[SKIP] handoff_truthful" in closeout.render()


def test_a_passing_truthfulness_review_clears_the_skip_line() -> None:
    report = judge.verify_handoff(
        handoff_text=GENUINE_HANDOFF,
        test_exit_code=0,
        test_output=GENUINE_TEST_LOG,
        diff_summary=GENUINE_DIFF,
    )
    closeout = gate.evaluate_closeout(
        "1-4", gate.SATISFIED_EVIDENCE,
        truthfulness=report.as_truthfulness_facts(),
    )
    assert not closeout.truthfulness_not_run
    assert closeout.truthfulness_evaluated
    assert "SKIP" not in closeout.render()
    assert "[PASS] handoff_truthful" in closeout.render()


def test_the_report_payload_carries_the_evaluation_flag() -> None:
    """A board rendering as_dict() must be able to show the same distinction."""
    skipped = gate.evaluate_closeout("1-4", gate.SATISFIED_EVIDENCE).as_dict()
    assert skipped["truthfulness_evaluated"] is False
    assert skipped["truthfulness_not_run"] is True

    report = judge.verify_handoff(
        handoff_text=GENUINE_HANDOFF,
        test_exit_code=0,
        test_output=GENUINE_TEST_LOG,
        diff_summary=GENUINE_DIFF,
    )
    checked = gate.evaluate_closeout(
        "1-4", gate.SATISFIED_EVIDENCE,
        truthfulness=report.as_truthfulness_facts(),
    ).as_dict()
    assert checked["truthfulness_evaluated"] is True
    assert checked["truthfulness_not_run"] is False


def test_assert_closeout_allowed_reports_the_skip_line_when_raising() -> None:
    report = judge.verify_handoff(
        handoff_text=GENUINE_HANDOFF, test_exit_code=1, test_output="",
        diff_summary=GENUINE_DIFF,
    )
    with pytest.raises(gate.CloseoutGateError) as excinfo:
        gate.assert_closeout_allowed(
            "1-4", {}, truthfulness=report.as_truthfulness_facts()
        )
    assert "SKIP" not in str(excinfo.value)


def test_truthfulness_facts_reject_a_verdict_that_is_not_accepted() -> None:
    facts = {
        "handoff_verdict": "UNVERIFIED_CLAIMS",
        "handoff_accepted": False,
    }
    result = gate.evaluate_step(gate.HANDOFF_TRUTHFUL_STEP, facts)
    assert not result.passed
    assert "UNVERIFIED_CLAIMS" in result.detail


def test_truthfulness_facts_reject_an_unknown_verdict() -> None:
    """An unproven verdict is not an acceptance."""
    facts = {"handoff_verdict": "ACCEPTED", "handoff_accepted": True, "verified": False}
    assert not gate.evaluate_step(gate.HANDOFF_TRUTHFUL_STEP, facts).passed
    facts = {"handoff_verdict": "MAYBE", "handoff_accepted": True}
    assert not gate.evaluate_step(gate.HANDOFF_TRUTHFUL_STEP, facts).passed


def test_closeout_command_honours_a_truthfulness_report(tmp_path, capsys) -> None:
    report = judge.verify_handoff(
        handoff_text="Verified with valgrind.", test_exit_code=0,
        test_output=GENUINE_TEST_LOG, diff_summary=GENUINE_DIFF, key="",
    )
    report_path = tmp_path / "truth.json"
    report_path.write_text(json.dumps(report.as_dict()), encoding="utf-8")

    code = plugin.main([
        "closeout", "--lane", "1-4",
        "--evidence", json.dumps(gate.SATISFIED_EVIDENCE),
        "--handoff-report", str(report_path),
    ])
    assert code == plugin.EXIT_GATE_REFUSED
    out = capsys.readouterr().out
    assert "gate CLOSED at handoff_truthful" in out


def test_closeout_command_rejects_a_malformed_truthfulness_report(tmp_path, capsys) -> None:
    bad = tmp_path / "truth.json"
    bad.write_text("{not json", encoding="utf-8")
    code = plugin.main([
        "closeout", "--lane", "1-4",
        "--evidence", json.dumps(gate.SATISFIED_EVIDENCE),
        "--handoff-report", str(bad),
    ])
    assert code == 2
    assert "not valid JSON" in capsys.readouterr().err


# --------------------------------------------------------------------------
# Zero new external dependencies
# --------------------------------------------------------------------------


def test_module_uses_only_the_standard_library() -> None:
    source = (LIB / "handoff_judge.py").read_text(encoding="utf-8")
    for third_party in ("import requests", "import numpy", "import pydantic", "import openai"):
        assert third_party not in source


# --------------------------------------------------------------------------
# Key resolution and the Jev state contract
# --------------------------------------------------------------------------


def test_an_explicit_empty_key_forces_the_offline_path(monkeypatch) -> None:
    """The documented escape hatch, independent of the ambient environment."""
    monkeypatch.setenv("TYPESAFE_API_KEY", "should-be-ignored")
    assert judge.resolve_api_key("") == ""


def test_no_key_argument_reads_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "  ambient-key  ")
    assert judge.resolve_api_key() == "ambient-key"


def test_an_explicit_key_beats_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "ambient")
    assert judge.resolve_api_key("explicit") == "explicit"


def test_the_jev_state_carries_the_physical_exit_code() -> None:
    """The model should see the one fact that code already proved."""
    patcher, mock_urlopen = _mock_jev(0.0, 0.0)
    try:
        judge.verify_handoff(
            handoff_text=GENUINE_HANDOFF,
            test_exit_code=0,
            test_output=GENUINE_TEST_LOG,
            diff_summary=GENUINE_DIFF,
            key="test-key", use_jev=True,
        )
    finally:
        patcher.stop()
    state = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))["state"]
    assert state["captured_test_exit_code"] == 0


def test_offline_needs_no_api_key_at_all() -> None:
    """A machine with no TypeSafe key still gets a real verdict."""
    assert judge.resolve_api_key("") == ""
    report = judge.verify_handoff(
        handoff_text=GENUINE_HANDOFF,
        test_exit_code=0,
        test_output=GENUINE_TEST_LOG,
        diff_summary=GENUINE_DIFF,
        key="",
    )
    assert report.accepted


def test_closeout_command_accepts_an_inline_handoff_report(capsys) -> None:
    """The report may be piped as JSON, not only read from a file."""
    report = judge.verify_handoff(
        handoff_text=GENUINE_HANDOFF,
        test_exit_code=0,
        test_output=GENUINE_TEST_LOG,
        diff_summary=GENUINE_DIFF,
        key="",
    )
    code = plugin.main([
        "closeout", "--lane", "1-4",
        "--evidence", json.dumps(gate.SATISFIED_EVIDENCE),
        "--handoff-report", json.dumps(report.as_dict()),
    ])
    assert code == 0
    assert "gate OPEN" in capsys.readouterr().out


def test_closeout_command_rejects_a_report_without_a_verdict(capsys) -> None:
    code = plugin.main([
        "closeout", "--lane", "1-4",
        "--evidence", json.dumps(gate.SATISFIED_EVIDENCE),
        "--handoff-report", json.dumps({"accepted": True}),
    ])
    assert code == 2
    assert "verdict" in capsys.readouterr().err


def test_a_bare_accepted_flag_cannot_unlock_closeout() -> None:
    """A report claiming success without naming a verdict is not evidence."""
    facts = {"handoff_accepted": True, "verified": True}
    assert not gate.evaluate_step(gate.HANDOFF_TRUTHFUL_STEP, facts).passed
