"""Tests for [NOTIFY] escape normalisation and standard report formatting.

The defect: `herdr agent prompt w3:p1 '\\n[NOTIFY] ...'` keeps the backslash-n
as two literal characters, because bash single quotes do not expand escapes.
The worker received escape sequences instead of line breaks and the report
rendered as one long single-line string.

Most of these tests feed text that *looks* dangerous, because the failure mode
here is silent corruption of a message that still appears to have been sent.
A mangled Chinese report is worse than no report: it is read and believed.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "multiplexer" / "herdr-dispatch"
LIB = PLUGIN_ROOT / "lib"
BIN = PLUGIN_ROOT / "bin"
PROBE = REPO_ROOT / "scripts" / "notify-format-probe.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(LIB))
herdr = _load("dispatch_herdr_client", LIB / "herdr_client.py")
proto = _load("dispatch_prompt_protocol", LIB / "prompt_protocol.py")
plugin = _load("dispatch_plugin", BIN / "dispatch_plugin.py")

LITERAL = (
    "\\n[NOTIFY] [w5:p1_opencode_mac-bootstrap]"
    "\\nDONE: 换行修复完成"
    "\\nHandoff: /tmp/x.md"
    "\\n回调目标坐标: w3:p1"
    "\\n\\n[核心成果]"
    "\\n- 要点 1"
)


# --------------------------------------------------------------------------
# The defect, as a regression test
# --------------------------------------------------------------------------


def test_literal_backslash_n_becomes_a_real_newline() -> None:
    out = proto.normalise_escapes("\\n[NOTIFY]")
    assert out.startswith("\n")
    assert "\\n" not in out
    assert out.count(chr(10)) == 1


def test_newlines_are_real_zero_x_0a() -> None:
    """The contract asks for byte 0x0A, not a lookalike."""
    out = proto.normalise_escapes("a\\nb")
    assert out == "a\nb"
    assert b"\x0a" in out.encode("utf-8")


def test_a_full_literal_report_becomes_multi_line() -> None:
    out = proto.normalise_escapes(LITERAL)
    assert "\\n" not in out
    assert len(out.splitlines()) >= 7


# --------------------------------------------------------------------------
# UTF-8 safety — the reason we do not use unicode_escape
# --------------------------------------------------------------------------


def test_chinese_survives_byte_for_byte() -> None:
    """`unicode_escape` would return mojibake here; that is why we don't."""
    text = "修复完成，中文测试 —— 排版美观"
    assert proto.normalise_escapes(text) == text


def test_chinese_survives_interleaved_with_escapes() -> None:
    out = proto.normalise_escapes("\\nDONE: 修复完成\\nHandoff: 路径")
    assert "修复完成" in out
    assert "\\n" not in out


def test_emoji_and_combining_marks_survive() -> None:
    text = "✅ 通过 — café 🎯"
    assert proto.normalise_escapes("\\n" + text) == "\n" + text


def test_unicode_escape_would_have_corrupted_it() -> None:
    """Pins *why* the obvious one-liner is not used, so nobody reinvents it."""
    text = "修复完成"
    corrupted = text.encode("utf-8").decode("unicode_escape")
    assert corrupted != text  # the hazard is real
    assert proto.normalise_escapes(text) == text  # and we avoid it


# --------------------------------------------------------------------------
# Fenced code blocks must not be deformed
# --------------------------------------------------------------------------


def test_fenced_code_block_keeps_its_literal_escapes() -> None:
    """A shell sample showing `'\\n[NOTIFY]'` must survive verbatim."""
    text = "报告:\n\\n示例:\n```\nherdr agent prompt w3:p1 '\\n[NOTIFY] x'\n```\n结束"
    out = proto.normalise_escapes(text)
    assert "'\\n[NOTIFY] x'" in out, "code block was deformed"
    assert "结束" in out
    assert out.startswith("报告:\n")


def test_tilde_fences_are_protected_too() -> None:
    text = "说明\n\\n~~~\nprintf 'a\\tb'\n~~~\n结束"
    out = proto.normalise_escapes(text)
    assert "printf 'a\\tb'" in out


def test_prose_around_a_fence_is_still_expanded() -> None:
    text = "前\\n中\n```\nkeep\\nhere\n```\n后\\n尾"
    out = proto.normalise_escapes(text)
    assert out.startswith("前\n中\n")
    assert out.endswith("后\n尾")
    assert "keep\\nhere" in out


def test_has_literal_escape_reports_what_survived() -> None:
    """After expansion, a surviving escape is inside a fence -- and that is fine.

    Prose escapes are always expanded, so this returning True means "there is a
    fenced code sample containing escapes", which the caller reports as an
    informational note rather than a problem.
    """
    assert proto.has_literal_escape("plain\\nprose") is False
    assert proto.has_literal_escape("plain\\n```\\na\\nb\\n```\\n") is True
    assert proto.has_literal_escape("clean text") is False


# --------------------------------------------------------------------------
# Conservative expansion
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a\\nb", "a\nb"),
        ("a\\tb", "a\tb"),
        ("a\\rb", "a\rb"),
    ],
)
def test_standard_escapes_expand(raw: str, expected: str) -> None:
    assert proto.normalise_escapes(raw) == expected


@pytest.mark.parametrize(
    "raw", [r"a\x41b", r"a\u00e9b", r"a\qb", r"a\0b", r"C:\\Users\\dev", r"re\\d+"]
)
def test_unknown_escapes_are_preserved_not_invented(raw: str) -> None:
    """Interpreting them would fabricate meaning the caller never expressed."""
    assert proto.normalise_escapes(raw) == raw


def test_escaped_backslash_is_left_to_the_shell() -> None:
    """`$'...'` already collapses a doubled backslash before this runs.

    Expanding it here would make `\\\\n` ambiguous between "escaped backslash
    plus n" and "backslash-n escape", and silently break idempotence:
    `path\\\\name` would come back as `path<newline>ame`.
    """
    assert proto.normalise_escapes("path\\\\name") == "path\\\\name"
    assert proto.normalise_escapes("\\\\n") == "\\\\n"


def test_expansion_is_idempotent() -> None:
    once = proto.normalise_escapes(LITERAL)
    assert proto.normalise_escapes(once) == once


def test_expansion_is_idempotent_with_a_fence() -> None:
    text = "a\\nb\n```\nc\\nd\n```\ne\\nf"
    once = proto.normalise_escapes(text)
    assert proto.normalise_escapes(once) == once


def test_empty_and_real_text_pass_through() -> None:
    assert proto.normalise_escapes("") == ""
    assert proto.normalise_escapes("already\nreal\nnewlines") == "already\nreal\nnewlines"


def test_trailing_backslash_is_not_dropped() -> None:
    assert proto.normalise_escapes("ends with\\") == "ends with\\"


# --------------------------------------------------------------------------
# Standard report formatting
# --------------------------------------------------------------------------


def test_build_notify_has_the_standard_shape() -> None:
    out = proto.build_notify(
        "w5:p1_opencode_mac-bootstrap",
        "换行修复完成",
        "/tmp/h.md",
        "w3:p1",
        highlights=["真实换行", "中文保真"],
        risks=["无"],
    )
    assert out.startswith("[NOTIFY] [w5:p1_opencode_mac-bootstrap]")
    assert "DONE: 换行修复完成" in out
    assert "Handoff: /tmp/h.md" in out
    assert "w3:p1" in out
    assert "[核心成果与证据]" in out
    assert "- 真实换行" in out
    assert "[风险与遗留]" in out


def test_build_notify_output_is_genuinely_multi_line() -> None:
    out = proto.build_notify("sig", "d", "/tmp/h.md", "w3:p1", highlights=["a", "b"])
    assert len(out.splitlines()) >= 8
    assert "\\n" not in out


def test_build_notify_fills_empty_sections() -> None:
    out = proto.build_notify("sig", "d", "/tmp/h.md", "w3:p1")
    assert "- 无" in out


def test_build_notify_accepts_extra_sections() -> None:
    out = proto.build_notify(
        "sig", "d", "/tmp/h.md", "w3:p1", sections={"验证": ["pytest 1145", "ts 154"]}
    )
    assert "[验证]" in out
    assert "- pytest 1145" in out


def test_build_notify_normalises_by_default_and_can_opt_out() -> None:
    out = proto.build_notify("sig", "行1\\n行2", "/tmp/h.md", "w3:p1")
    assert "行1\n行2" in out
    raw = proto.build_notify("sig", "行1\\n行2", "/tmp/h.md", "w3:p1", normalise=False)
    assert "行1\\n行2" in raw


def test_format_notify_lines_quotes_each_line() -> None:
    """Callers that build their own shell command must not lose spaces."""
    out = proto.format_notify_lines("sig", "有 空格 的结论", "/tmp/h.md", "w3:p1")
    # shlex.quote wraps the whole line, so the marker travels with it.
    assert "'DONE: 有 空格 的结论'" in out


# --------------------------------------------------------------------------
# Delivery semantics
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_live_herdr(monkeypatch: pytest.MonkeyPatch):
    def refuse(*args, **kwargs):
        raise AssertionError("test attempted a live Herdr call; patch plugin.herdr.run_herdr")

    monkeypatch.setattr(plugin.herdr, "run_herdr", refuse)


def test_send_delivers_expanded_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """The defect fix: what lands on the wire has real newlines."""
    calls: list[list[str]] = []
    monkeypatch.setattr(plugin.herdr, "run_herdr", lambda a, **k: calls.append(list(a)) or {})
    assert plugin.main(["prompt", "--text", LITERAL, "--send", "--target", "w3:p1"]) == 0
    delivered = calls[0][3]
    assert "\\n" not in delivered
    assert delivered.count("\n") >= 6
    # UTF-8 payload must survive the transform the delivery path applies.
    assert "换行修复完成" in delivered


def test_keep_escapes_delivers_byte_for_byte(monkeypatch: pytest.MonkeyPatch) -> None:
    """The opt-out: sometimes two characters are what you actually meant."""
    calls: list[list[str]] = []
    monkeypatch.setattr(plugin.herdr, "run_herdr", lambda a, **k: calls.append(list(a)) or {})
    assert plugin.main(
        ["prompt", "--text", LITERAL, "--send", "--target", "w3:p1", "--keep-escapes"]
    ) == 0
    assert calls[0][3] == LITERAL


def test_send_still_validates_before_delivering(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(plugin.herdr, "run_herdr", lambda a, **k: calls.append(list(a)) or {})
    assert plugin.main(["prompt", "--text", "bare prose", "--send", "--target", "w3:p1"]) == 2
    assert calls == []


def test_notify_command_sends_the_formatted_report(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(plugin.herdr, "run_herdr", lambda a, **k: calls.append(list(a)) or {})
    code = plugin.main([
        "notify", "--signature", "w5:p1_opencode_mac-bootstrap",
        "--done", "完成", "--handoff", "/tmp/h.md", "--target", "w3:p1",
        "--highlight", "要点甲", "--risk", "遗留乙", "--send",
    ])
    assert code == 0
    text = calls[0][3]
    assert text.startswith("[NOTIFY] [w5:p1_opencode_mac-bootstrap]")
    assert "DONE: 完成" in text
    assert "- 要点甲" in text
    assert "- 遗留乙" in text
    assert "\\n" not in text


def test_notify_command_prints_without_send(capsys: pytest.CaptureFixture) -> None:
    code = plugin.main([
        "notify", "--signature", "sig", "--done", "d",
        "--handoff", "/tmp/h.md", "--target", "w3:p1",
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert out.startswith("[NOTIFY] [sig]")
    assert len(out.splitlines()) >= 7


def test_notify_requires_its_arguments() -> None:
    """argparse exits rather than returning, so the refusal must be a SystemExit."""
    with pytest.raises(SystemExit) as excinfo:
        plugin.main(["notify", "--signature", "sig"])
    assert excinfo.value.code == 2


# --------------------------------------------------------------------------
# Validation still judges the caller's text
# --------------------------------------------------------------------------


def test_validation_is_unaffected_by_expansion() -> None:
    """Normalisation is a delivery concern; the contract check is separate."""
    assert not proto.validate_prompt("bare prose").ok
    assert proto.validate_prompt(LITERAL).ok


# --------------------------------------------------------------------------
# The feedback loop
# --------------------------------------------------------------------------


def test_the_probe_goes_green() -> None:
    proc = subprocess.run([sys.executable, str(PROBE)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "newline/format contract holds" in proc.stdout


def test_the_probe_is_not_vacuously_green() -> None:
    """Negative control: the probe must be able to fail."""
    source = PROBE.read_text(encoding="utf-8")
    assert "literal backslash-n" in source
    assert "mojibake" in source
    assert source.count("results.append(check(") >= 5