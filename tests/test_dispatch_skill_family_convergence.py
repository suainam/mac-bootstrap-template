"""The dispatch skill family must not fork again — TB-07.

Five driver skills used to carry their own copies of `plan.md` and
`supervise.md`. They were never byte-identical: the copies drifted until
`supervise.md` ranged from 84 to 199 lines and the `claude` variant had lost
most of the false-DONE checks entirely. Every fix had to be applied five times
and was usually applied four.

The family now shares one `_shared/` copy per document, reached by relative
symlink so the OS resolves it through the wired skill directories. These tests
pin that arrangement, because the failure mode is silent: a real file in place
of a symlink still reads fine and only drifts months later.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "agent-skills" / "local" / "mac-bootstrap"
SHARED = SKILL_ROOT / "_shared"

# The drivers that used to fork these documents.
DRIVERS = ("agy", "claude", "codex", "omp", "opencode")
SHARED_DOCS = ("plan.md", "supervise.md")


def _symlink_target(path: Path) -> str:
    return str(path.readlink())


# --------------------------------------------------------------------------
# The shared documents exist and are real content
# --------------------------------------------------------------------------


@pytest.mark.parametrize("doc", SHARED_DOCS)
def test_shared_document_exists(doc: str) -> None:
    target = SHARED / doc
    assert target.is_file(), f"missing shared document: {target}"
    # A stub would satisfy existence while reintroducing the drift problem.
    assert len(target.read_text(encoding="utf-8").splitlines()) > 80, doc


# --------------------------------------------------------------------------
# Every driver references them rather than copying them
# --------------------------------------------------------------------------


@pytest.mark.parametrize("driver", DRIVERS)
@pytest.mark.parametrize("doc", SHARED_DOCS)
def test_driver_reference_is_a_symlink(driver: str, doc: str) -> None:
    path = SKILL_ROOT / f"dispatch-{driver}" / "references" / doc
    assert path.exists(), f"{path} does not resolve"
    assert path.is_symlink(), (
        f"{path} is a real file again; that is how the family forked. "
        "Replace it with a symlink to ../../_shared/"
    )
    assert _symlink_target(path) == f"../../_shared/{doc}"


@pytest.mark.parametrize("driver", DRIVERS)
@pytest.mark.parametrize("doc", SHARED_DOCS)
def test_driver_reference_resolves_to_the_shared_copy(driver: str, doc: str) -> None:
    path = SKILL_ROOT / f"dispatch-{driver}" / "references" / doc
    assert path.resolve() == (SHARED / doc).resolve()


# --------------------------------------------------------------------------
# No agent identity leaked into the shared copies
# --------------------------------------------------------------------------


@pytest.mark.parametrize("doc", SHARED_DOCS)
def test_shared_document_is_agent_neutral(doc: str) -> None:
    """Agent identity belongs in driver.md, not in the shared half.

    This is what let the copies diverge: each one baked in its own name.
    """
    text = (SHARED / doc).read_text(encoding="utf-8")
    for agent in ("codex", "opencode", "agy", "claude"):
        assert agent not in text.lower(), f"{doc} still names {agent}"


@pytest.mark.parametrize("doc", SHARED_DOCS)
def test_shared_document_uses_the_skill_name_placeholder(doc: str) -> None:
    text = (SHARED / doc).read_text(encoding="utf-8")
    assert "<skill-name>" in text, f"{doc} lost its skill-name placeholder"


def test_plan_records_the_agent_kind_placeholder() -> None:
    """plan.md writes agent_kind into the state file, so it needs the token.

    supervise.md deliberately does not: it works purely in <lane> and <run-id>
    terms, so requiring an agent-kind placeholder there would be cargo cult.
    """
    assert "<agent-kind>" in (SHARED / "plan.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# The drivers keep their own agent-specific half
# --------------------------------------------------------------------------


@pytest.mark.parametrize("driver", DRIVERS)
def test_driver_keeps_its_own_driver_doc(driver: str) -> None:
    """Converging the shared half must not swallow the agent-specific half."""
    path = SKILL_ROOT / f"dispatch-{driver}" / "references" / "driver.md"
    assert path.is_file(), f"{path} disappeared"
    assert not path.is_symlink(), "driver.md is agent-specific; it must stay real"
    assert len(path.read_text(encoding="utf-8").splitlines()) > 50, driver


@pytest.mark.parametrize("driver", DRIVERS)
def test_driver_doc_names_its_own_agent(driver: str) -> None:
    """The knowledge that used to be duplicated must live somewhere."""
    text = (
        SKILL_ROOT / f"dispatch-{driver}" / "references" / "driver.md"
    ).read_text(encoding="utf-8").lower()
    assert driver in text, f"driver.md no longer mentions {driver}"


# --------------------------------------------------------------------------
# Size sanity: the point of all this
# --------------------------------------------------------------------------


def test_family_no_longer_duplicates_the_shared_half() -> None:
    total_shared = sum(
        len((SHARED / doc).read_text(encoding="utf-8").splitlines())
        for doc in SHARED_DOCS
    )
    # Five forks of these documents used to total 1375 lines. One canonical
    # copy plus symlinks must be dramatically less than the fork total.
    assert total_shared < 400, total_shared