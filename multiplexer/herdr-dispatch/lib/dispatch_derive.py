"""Derive dispatch parameters instead of demanding them — Issue #136.

The bus's value is that it *takes away* the orchestrator's freedom to skip
steps. Six hand-assembled arguments quietly gave that freedom back: every one
of them was a chance to type the lane twice and get the two copies disagree, or
to paste a worktree path from an earlier run and have the claim gate audit a
directory nobody is working in.

So the parameters that are already implied by other parameters are derived here,
and a derivation that cannot be completed is a **refusal**, never an empty
value. That distinction is the whole point: an empty ``worktree`` skips the
claim gate, and a skipped claim gate is how two interactive agents end up
sharing one worktree — the failure 1 Lane = 1 Worktree = 1 Branch exists to
prevent.

Three derivations, in the order they become available:

1. ``--lane`` from ``--lane-name``. The name is already constrained to
   ``<wave>-<lane>-<slug>``, so the coordinates are a prefix, not new
   information. One source, so the two can never disagree.
2. highlights / risks from the task contract's own semantic sections. The
   contract already states what the outcome is and what could go wrong; asking
   the orchestrator to also type it into a flag is asking for a second copy
   that can drift from the first.
3. worktree / branch from the target pane. The pane already has a cwd and that
   cwd already has a checked-out branch; asking for them separately means
   asking for a value that is stale the moment it is typed.

Deliberately *not* here: any gate. This module reads and computes. It refuses
by raising, and :class:`dispatch_bus.DispatchPlan` turns that into a plan or an
exception — it never commits anything.

Why this is a separate module from ``dispatch_bus``
--------------------------------------------------
``dispatch_bus`` holds a hard invariant: it composes argv arrays and never
shells out (a test asserts the absence of ``subprocess`` in its source). Git
and Herdr both require a subprocess. Putting the derivation here keeps that
invariant testable instead of aspirational — the bus still never builds a
command line, it only asks this module what the answer is.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Mapping, Optional, Sequence, Tuple

# The lane coordinates are the first two dash-separated segments of the name.
# The name pattern already guarantees they exist; the regex is here so the
# derivation cannot silently return a wrong prefix if the pattern ever loosens.
LANE_COORD_RE = re.compile(r"^([0-9]+-[0-9]+)-")

# Semantic section headings, matched case-insensitively against the heading text
# with any markdown decoration stripped. Order within each tuple is the
# preference order.
HIGHLIGHT_SECTIONS: Tuple[str, ...] = (
    "核心成果与证据",
    "核心成果",
    "成果与证据",
    "成果",
    "highlights",
    "highlight",
)
RISK_SECTIONS: Tuple[str, ...] = (
    "风险与遗留",
    "风险遗留",
    "风险",
    "risks",
    "risk",
)
# The contract's own outcome and constraint sections. Used only when no
# dedicated report section exists, because the 7-section contract guarantees
# these two are present while the report sections are optional.
FALLBACK_HIGHLIGHT_SECTION = "目标"
FALLBACK_RISK_SECTION = "约束"

# A bullet, however the author spelled it.
BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*\S)\s*$")
# Any heading, any level.
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s*(.+?)\s*#*\s*$")

# Sentence terminators, both scripts. Used only to shorten a long outcome
# paragraph into one readable line, never to truncate a fact.
SENTENCE_END = "。！？!?;；"

# Guard rails. A task contract is a human document; an unbounded read of one
# would let a pasted log turn into an unreadable report.
MAX_ITEMS = 5
MAX_ITEM_CHARS = 200

GIT_TIMEOUT = 10


class DerivationRefused(RuntimeError):
    """A parameter could not be derived, so the dispatch must not proceed.

    Raised rather than returning a partial value on purpose: every field this
    module produces feeds a gate, and a gate fed "" is a gate that did not run.
    """


@dataclass(frozen=True)
class Placement:
    """Where a lane works: its worktree path and its checked-out branch."""

    worktree: str
    branch: str

    def as_dict(self) -> Mapping[str, str]:
        return {"worktree": self.worktree, "branch": self.branch}


# --------------------------------------------------------------------------
# 1. lane coordinates
# --------------------------------------------------------------------------


def lane_from_name(lane_name: str) -> str:
    """Return the ``<wave>-<lane>`` coordinates implied by ``lane_name``.

    ``1-3-dispatch`` -> ``1-3``. The caller validates the name against the
    project pattern first, so a name that reaches here without a coordinate
    prefix is a pattern regression rather than user error — it still refuses,
    because the alternative is a lane keyed under a name that cannot be parsed.
    """
    match = LANE_COORD_RE.match(lane_name or "")
    if not match:
        raise DerivationRefused(
            f"cannot derive lane coordinates from {lane_name!r}: expected the "
            "name to begin with <wave>-<lane>, e.g. 1-3-dispatch"
        )
    return match.group(1)


# --------------------------------------------------------------------------
# 2. report sections from the task contract
# --------------------------------------------------------------------------


def _clean_heading(raw: str) -> str:
    """Strip markdown decoration and bracketed suffixes from a heading."""
    text = re.sub(r"[*_`]", "", raw or "")
    text = re.sub(r"[（(].*?[)）]\s*$", "", text)
    return text.strip().strip(":：").lower()


def split_sections(text: str) -> List[Tuple[str, List[str]]]:
    """Return ``(heading, body lines)`` for every heading in the document.

    Level-aware, via an explicit stack: a ``###`` heading nested under a ``##``
    does not terminate the ``##``, so a contract that nests its checklists keeps
    them in the section they belong to. A flat split would drop them.

    A fenced block is literal content, so a ``# comment`` inside a shell snippet
    does not become a heading.
    """
    sections: List[Tuple[str, List[str]]] = []
    # (level, body) for every heading still open, outermost first.
    stack: List[Tuple[int, List[str]]] = []
    # (opening marker, the lines it swallowed). Buffered rather than dropped, so
    # an unbalanced fence can be put back — see below.
    fence: Optional[Tuple[str, List[str]]] = None

    def body() -> Optional[List[str]]:
        return stack[-1][1] if stack else None

    for line in (text or "").splitlines():
        stripped = line.strip()

        # Inside a fence the text is literal: a `# comment` is a comment, and a
        # `- ` line is shell, not a report bullet. Neither belongs in a report,
        # so fenced lines are dropped rather than collected — collecting them
        # would let a pasted shell snippet masquerade as a stated outcome.
        if fence:
            if stripped.startswith(fence[0]):
                fence = None
            else:
                fence[1].append(line)
            continue

        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = (stripped[:3], [])
            continue

        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            fresh: List[str] = []
            sections.append((heading.group(2), fresh))
            stack.append((level, fresh))
            continue

        target = body()
        if target is not None:
            target.append(line)

    # An unclosed fence means the rest of the document was never interpreted as
    # structure. Put those lines back rather than silently returning a section
    # that is empty because the author mistyped a closing marker: a report that
    # says "- 无" when the contract actually states three risks is worse than a
    # slightly mis-parsed one.
    if fence:
        target = body()
        if target is not None:
            target.extend(fence[1])

    return sections


def _section_body(sections: Sequence[Tuple[str, List[str]]], wanted: Sequence[str]) -> List[str]:
    """Body of the first section whose heading matches any of ``wanted``."""
    for name in wanted:
        for heading, body in sections:
            if _clean_heading(heading) == _clean_heading(name):
                return body
    # Second pass: substring match, so "## 风险与遗留 (Risks)" still resolves
    # even when the decorator stripper leaves something behind.
    for name in wanted:
        for heading, body in sections:
            cleaned = _clean_heading(heading)
            if _clean_heading(name) and _clean_heading(name) in cleaned:
                return body
    return []


def _items_from_body(body: Sequence[str]) -> List[str]:
    """Bullets from a section body, or its prose lines when there are none."""
    bullets = [m.group(1).strip() for line in body if (m := BULLET_RE.match(line))]
    if bullets:
        return [dequote_placeholders(item) for item in bullets if item]

    items: List[str] = []
    for line in body:
        text = line.strip()
        # Skip structural leftovers: the next heading, a horizontal rule, a
        # bare table separator.
        if not text or HEADING_RE.match(text) or re.fullmatch(r"[-*_|\s:]+", text):
            continue
        if text.startswith("|"):
            continue
        items.append(dequote_placeholders(text))
    return items


def _clip(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= MAX_ITEM_CHARS:
        return text
    return text[: MAX_ITEM_CHARS - 1].rstrip() + "…"


# Template syntax that the prompt gate refuses. A contract is full of it — the
# dispatch SKILL.md is written in `${ORCH_PANE}` and `<pane_id>` throughout,
# because a contract is an instruction to an orchestrator.
SHELL_VAR_RE = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?")
ANGLE_PLACEHOLDER_RE = re.compile(r"<[a-z][a-z0-9_-]*(?: [a-z]+)?>")


def dequote_placeholders(text: str) -> str:
    """Strip unresolved template syntax from a *derived* report bullet.

    Only derived text goes through here, never a `--highlight` the caller typed.
    That asymmetry is the whole point:

    - a derived bullet is contract **prose**, quoted by a machine rather than
      written for a report. `"运行前先设置 $GATE"` is an instruction to the
      orchestrator; forwarding it into the worker's envelope would both be
      meaningless to the worker and trip the prompt gate, so the dispatch would
      be refused for quoting a sentence nobody chose. The caller cannot fix
      this, because the text came from their contract's Constraints section and
      they never chose it.
    - a `--highlight` the caller typed is *theirs*. If it contains `$GATE`, the
      gate refusing it is correct — it is a placeholder that would reach a
      worker unexpanded, and only the caller can say what it meant.
    """
    cleaned = ANGLE_PLACEHOLDER_RE.sub("…", SHELL_VAR_RE.sub("…", text or ""))
    return _clip(cleaned)


def first_sentence(text: str) -> str:
    """The first sentence of a paragraph, for a one-line report bullet."""
    flat = re.sub(r"\s+", " ", text or "").strip()
    for index, char in enumerate(flat):
        if char in SENTENCE_END:
            return _clip(flat[: index + 1])
    return _clip(flat)


def extract_report_items(
    sections: Sequence[Tuple[str, List[str]]],
    *,
    dedicated: Sequence[str],
    fallback: str,
) -> List[str]:
    """Report bullets for one half of the envelope.

    A dedicated section wins. Otherwise the contract's own outcome/constraint
    section is reduced to its first sentence, so a lane with no report section
    still says something true instead of reporting a blank.

    An empty result is legitimate: the envelope's formatter renders it as
    ``- 无``, which is honest where an invented bullet would not be.
    """
    items = _items_from_body(_section_body(sections, dedicated))
    if items:
        return items[:MAX_ITEMS]

    fallback_body = _items_from_body(_section_body(sections, [fallback]))
    if not fallback_body:
        return []
    return [first_sentence(fallback_body[0])][:1]


def report_items_from_task(task: Path) -> Tuple[List[str], List[str]]:
    """Return ``(highlights, risks)`` parsed from a task contract."""
    try:
        text = Path(task).read_text(encoding="utf-8")
    except OSError as exc:
        # The contract lint already refused an unreadable task by this point;
        # reaching here means the file vanished mid-dispatch, which is a
        # refusal rather than an empty report.
        raise DerivationRefused(f"cannot read task contract {task} ({exc})") from exc

    sections = split_sections(text)
    return (
        extract_report_items(
            sections, dedicated=HIGHLIGHT_SECTIONS, fallback=FALLBACK_HIGHLIGHT_SECTION
        ),
        extract_report_items(
            sections, dedicated=RISK_SECTIONS, fallback=FALLBACK_RISK_SECTION
        ),
    )


# --------------------------------------------------------------------------
# 3. placement from the target pane
# --------------------------------------------------------------------------


def default_pane_lookup(target: str) -> str:
    """Read a pane's cwd from Herdr.

    A transport failure raises rather than returning "": the caller turns an
    empty string into "Herdr reported no cwd for this pane", which sends an
    operator to recreate a perfectly good pane when the real cause was that the
    `herdr` binary is not on PATH or the server did not answer. Collapsing four
    different causes into one diagnosis makes the exit code right and the
    remedy actively wrong, twice.

    Imported lazily: this module is importable without the Herdr client, and a
    caller that injects its own ``pane_lookup`` needs nothing else.
    """
    try:
        import herdr_client as herdr
    except ImportError as exc:  # pragma: no cover - the plugin always ships it
        raise DerivationRefused(
            f"cannot read the cwd of pane {target}: the Herdr client module is "
            "not importable, so the plugin is not fully installed"
        ) from exc

    try:
        pane = herdr.pane_info(target)
    except herdr.HerdrError as exc:
        raise DerivationRefused(
            f"cannot read pane {target} from Herdr: {exc}. This is a transport "
            "or lookup failure (Herdr not running, the pane not existing, or "
            "the herdr binary not on PATH) rather than a pane without a "
            "working directory."
        ) from exc
    return str(pane.get("cwd") or pane.get("foreground_cwd") or "")


def _git_toplevel(cwd: str) -> str:
    """Return the physical Git worktree root containing ``cwd``, or refuse."""
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise DerivationRefused(
            "cannot derive the Git worktree: the git binary is not on PATH"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DerivationRefused(
            f"cannot derive the Git worktree: git in {cwd} did not answer within {GIT_TIMEOUT}s"
        ) from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise DerivationRefused(
            f"cannot derive the Git worktree from {cwd}: "
            + (detail[0] if detail else f"git exited {proc.returncode}")
        )
    root = proc.stdout.strip()
    if not root:
        raise DerivationRefused(f"cannot derive the Git worktree from {cwd}: empty top-level")
    return str(Path(root).expanduser().resolve())


def _git_branch(cwd: str) -> str:
    """``git -C <cwd> rev-parse --abbrev-ref HEAD``, or raise."""
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise DerivationRefused(
            "cannot derive the branch: the git binary is not on PATH"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DerivationRefused(
            f"cannot derive the branch: git in {cwd} did not answer within {GIT_TIMEOUT}s"
        ) from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise DerivationRefused(
            f"cannot derive the branch from {cwd}: "
            + (detail[0] if detail else f"git exited {proc.returncode}")
        )
    return proc.stdout.strip()


def normalise_worktree(raw: str) -> str:
    """Resolve a *named* worktree path, or raise.

    Applied to overrides as well as to derived values. Skipping it on the
    supplied path would let two spellings of one directory reach the state file
    and the receipt differently from every derived worktree — and a path that
    does not exist would become a claim on a directory nobody is working in,
    which is the collision the gate exists to catch.
    """
    text = (raw or "").strip()
    if not text:
        raise DerivationRefused("a worktree path is required, or omit it and let the pane supply one")
    candidate = Path(text).expanduser()
    if not candidate.is_dir():
        raise DerivationRefused(
            f"cannot claim {text!r}: it is not a directory. A claim on a path "
            "that does not exist isolates nothing, so the collision it was "
            "meant to catch would go undetected."
        )
    return str(candidate.resolve())


def checked_branch(raw: str, worktree: str) -> str:
    """Validate a *named* branch for a claim, or raise.

    Applied to overrides as well as to derived values. Skipping it on the
    supplied path would leave the documented remedy for a refused derivation —
    pass the values explicitly — reproducing the refusal instead of fixing it: a
    pane on a detached HEAD yields the literal branch ``HEAD``, which would pass
    straight through and isolate nothing.
    """
    branch = (raw or "").strip()
    if not branch:
        raise DerivationRefused(
            f"cannot claim {worktree!r} with no branch. 1 Lane = 1 Worktree = "
            "1 Branch needs a real branch to claim."
        )
    if branch == "HEAD":
        raise DerivationRefused(
            f"cannot claim {worktree}: it has a detached HEAD, so there is no "
            "branch to isolate the lane on. Check out a branch first."
        )
    return branch


def branch_at(
    worktree: str,
    *,
    reader: Optional[Callable[[str], str]] = None,
) -> str:
    """The branch checked out in a *named* directory, or raise.

    Separate from :func:`derive_placement` because the caller may have supplied
    one half of the pair. Deriving the missing half from the supplied directory
    keeps both halves describing the same tree — reading the branch from the
    pane while claiming a different worktree produces a pair that looks valid
    and isolates nothing.
    """
    resolved = normalise_worktree(worktree)
    return checked_branch((reader or _git_branch)(resolved), resolved)


def derive_placement(
    target: str,
    *,
    pane_lookup: Optional[Callable[[str], str]] = None,
    worktree_reader: Optional[Callable[[str], str]] = None,
    branch_reader: Optional[Callable[[str], str]] = None,
) -> Placement:
    """Derive ``(worktree, branch)`` for the pane at ``target``.

    Every failure raises. An empty ``Placement`` would look exactly like "this
    lane claims nothing", and the claim gate skips a lane that claims nothing —
    so a failure here must never be representable as a success.
    """
    if not target:
        raise DerivationRefused(
            "cannot derive a worktree or branch without a target pane"
        )

    lookup = pane_lookup or default_pane_lookup
    try:
        cwd = (lookup(target) or "").strip()
    except Exception as exc:  # noqa: BLE001 - a probe failure is a refusal
        raise DerivationRefused(
            f"cannot read the cwd of pane {target}: {exc}"
        ) from exc

    if not cwd:
        raise DerivationRefused(
            f"cannot derive the worktree for lane pane {target}: Herdr reported "
            "no cwd for it. The pane must exist and have a working directory "
            "before its lane can claim one — dispatching anyway would leave the "
            "lane unclaimed and two lanes free to share a worktree."
        )

    worktree = Path(cwd).expanduser()
    if not worktree.is_dir():
        raise DerivationRefused(
            f"cannot derive the worktree for lane pane {target}: {cwd} is not a "
            "directory. Herdr's cwd for that pane is stale."
        )
    pane_cwd = str(worktree.resolve())
    resolved = (worktree_reader or _git_toplevel)(pane_cwd)
    resolved = str(Path(resolved).expanduser().resolve())
    branch = checked_branch((branch_reader or _git_branch)(resolved), resolved)
    return Placement(worktree=resolved, branch=branch)