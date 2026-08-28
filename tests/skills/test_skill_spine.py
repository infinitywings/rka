"""The three Core role skills must share a spine and agree with the tool surface.

Two drift classes this locks down, both observed on 2026-08-23:

1. **Structural drift.** The role skills had *no* H2 heading in common —
   not because content was missing but because the same concept was titled
   differently in each ("Tool Surface (v2.7.0+) — No-Compromise Typed-Arg
   Dispatch" vs "Tool Surface", "Retrieval Strategy — Drive RKA…" vs
   "Retrieving Context — Drive RKA…"). A reader comparing two roles could
   not tell whether a section was absent or merely renamed.

2. **Reference drift.** A skill citing an operation that no longer exists
   sends an agent to a dead call. The v2.6 → v2.7 surface change made this
   a live risk.

`Guardrails` (limits of a role's authority) and `Anti-Patterns` (ways to
misuse the tool) are deliberately NOT unified — they are different things,
and collapsing them would lose the distinction.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS = REPO_ROOT / "rka" / "skills"
ROLES = ("brain", "executor", "pi")

# Concepts every role skill must carry, under exactly this heading.
REQUIRED_SECTIONS = ("Tool Surface", "Session Start")


def _headings(role: str) -> list[str]:
    text = (SKILLS / role / "SKILL.md").read_text(encoding="utf-8")
    return [h.strip() for h in re.findall(r"^##\s+(.+)$", text, re.M)]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("section", REQUIRED_SECTIONS)
def test_every_role_skill_carries_the_shared_spine(role: str, section: str) -> None:
    assert section in _headings(role), (
        f"{role}/SKILL.md is missing the '{section}' section, or titles it "
        f"differently. Present headings: {_headings(role)}"
    )


def test_retrieval_guidance_exists_for_every_role() -> None:
    """Every Core role must say how to retrieve."""
    for role in ROLES:
        text = (SKILLS / role / "SKILL.md").read_text(encoding="utf-8")
        assert "Retrieval Strategy" in text or "collect_report_context" in text, role


def test_skills_cite_only_operations_that_exist() -> None:
    from rka.mcp.operations_schema import OPERATIONS_SCHEMA

    cited: dict[str, set[str]] = {}
    for path in SKILLS.rglob("*.md"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        found = set(re.findall(r'"operation"\s*:\s*"([a-z_]+)"', text))
        found |= set(re.findall(r'operation=["\']([a-z_]+)["\']', text))
        if found:
            cited[str(path.relative_to(SKILLS))] = found

    unknown = {
        rel: sorted(ops - set(OPERATIONS_SCHEMA))
        for rel, ops in cited.items()
        if ops - set(OPERATIONS_SCHEMA)
    }
    assert not unknown, f"skills cite operations that do not exist: {unknown}"


def test_currency_operations_are_documented_somewhere() -> None:
    """The tools that answer "is this still true?" must be discoverable.

    These are the operations most directly aimed at not acting on overturned
    knowledge, and every one of them was undocumented before 2026-08-23.
    """
    corpus = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in SKILLS.rglob("*.md")
    )
    for op in ("belief_as_of", "staleness_impact", "changes_since",
               "contradictions", "mission_guard"):
        assert op in corpus, f"no skill mentions {op}"
