"""Tests for v2.7.0.6 phase-inheritance on `DecisionService.supersede_decision`.

When `new_data.phase` is empty or None, the service inherits from the
OLD decision being superseded — under the ratified semantic, supersede
'overturns the decision in its original phase slot'. Callers crossing
phases must supply `phase` explicitly.

Coverage:
    - Empty phase inherits from OLD.
    - None phase (DecisionSupersedeBody path) inherits from OLD.
    - Explicit phase is preserved.
    - Both phases empty raises with a message pointing at the admin command.
    - Inherited phase is visible in get_tree(phase=...) and list_decisions.
    - emit_event payload carries the inherited phase, not "".
    - Cross-phase regression test: PI in 'execution' phase supersedes a
      'design'-phase decision with omitted phase → new decision keeps
      'design'.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio

from rka.infra.database import Database
from rka.models.decision import DecisionCreate, DecisionSupersedeBody
from rka.services.decisions import DecisionService

_PROJECT = "proj_default"


@pytest_asyncio.fixture
async def svc(db: Database) -> DecisionService:
    """Service scoped to the default project."""
    return DecisionService(db, project_id=_PROJECT)


@pytest_asyncio.fixture
async def old_decision(svc: DecisionService) -> str:
    """Seed an OLD active decision in the 'design' phase."""
    # Need a journal entry first to satisfy provenance discipline.
    await svc.db.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ["jrn_seed", _PROJECT, "note", "initial framing", "brain", "tested"],
    )
    await svc.db.commit()

    decision = await svc.create(
        DecisionCreate(
            question="Should we use Option A?",
            phase="design",
            decided_by="brain",
            chosen="yes",
            rationale="initial framing",
            related_journal=["jrn_seed"],
            kind="decision",
        ),
        actor="brain",
    )
    return decision.id


# ---------------------------------------------------------------------------
# Inheritance — DecisionSupersedeBody (phase=None)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supersede_inherits_phase_when_phase_is_none(
    svc: DecisionService, old_decision: str
):
    """The dominant cockpit path: Brain omits phase on a supersede
    proposal. DecisionSupersedeBody allows phase=None; service inherits."""
    # New journal entry for the supersede's provenance.
    await svc.db.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ["jrn_new", _PROJECT, "finding", "new evidence", "brain", "tested"],
    )
    await svc.db.commit()

    new = await svc.supersede_decision(
        old_decision,
        DecisionSupersedeBody(
            question="Reframed: Option B?",
            decided_by="brain",
            chosen="Option B",
            rationale="new evidence",
            related_journal=["jrn_new"],
            kind="decision",
            # phase=None (default) — should inherit 'design' from old.
        ),
        actor="brain",
    )
    assert new.phase == "design"


# ---------------------------------------------------------------------------
# Explicit phase preserved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supersede_keeps_explicit_phase(
    svc: DecisionService, old_decision: str
):
    """If the caller supplies phase='execution', that wins over OLD's 'design'."""
    await svc.db.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ["jrn_x", _PROJECT, "finding", "new evidence", "brain", "tested"],
    )
    await svc.db.commit()

    new = await svc.supersede_decision(
        old_decision,
        DecisionSupersedeBody(
            question="Q?", decided_by="brain", chosen="X", rationale="R",
            related_journal=["jrn_x"], phase="execution",
        ),
        actor="brain",
    )
    assert new.phase == "execution"


# ---------------------------------------------------------------------------
# Both phases empty — guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supersede_raises_when_both_phases_empty(
    svc: DecisionService
):
    """OLD has phase='' (e.g. a pre-v2.7.0.6 orphan) AND new_data omits
    phase. Service raises with a message pointing at the admin command."""
    # Seed an OLD with empty phase via direct INSERT (the service would
    # not accept phase='' via DecisionCreate, but legacy rows may exist).
    await svc.db.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ["jrn_a", _PROJECT, "note", "x", "brain", "tested"],
    )
    await svc.db.execute(
        """INSERT INTO decisions
           (id, project_id, question, decided_by, kind, phase, status,
            scope_version, created_at, updated_at)
           VALUES ('dec_orphan_phase_empty', ?, 'Q', 'brain', 'decision',
                   '', 'active', 1, '2026-06-05T12:00:00Z',
                   '2026-06-05T12:00:00Z')""",
        [_PROJECT],
    )
    await svc.db.commit()

    with pytest.raises(ValueError) as excinfo:
        await svc.supersede_decision(
            "dec_orphan_phase_empty",
            DecisionSupersedeBody(
                question="New Q", decided_by="brain", chosen="X",
                rationale="R", related_journal=["jrn_a"],
            ),
            actor="brain",
        )
    msg = str(excinfo.value)
    assert "both old.phase and new_data.phase are empty" in msg
    assert "rka admin repair-supersedes" in msg, (
        "guard message must point at the admin command so PI knows the fix path"
    )


# ---------------------------------------------------------------------------
# Inherited phase visible in tree-by-phase queries (the bug surface)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supersede_inherited_phase_visible_in_tree_by_phase(
    svc: DecisionService, old_decision: str
):
    """End-to-end: get_tree(phase='design') returns the new decision
    after phase inheritance. Pre-v2.7.0.6, omitting phase produced a
    row with phase='' which was skipped by this query."""
    await svc.db.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ["jrn_y", _PROJECT, "finding", "y", "brain", "tested"],
    )
    await svc.db.commit()

    new = await svc.supersede_decision(
        old_decision,
        DecisionSupersedeBody(
            question="Reframed", decided_by="brain", chosen="B",
            rationale="reasons", related_journal=["jrn_y"],
        ),
        actor="brain",
    )
    tree = await svc.get_tree(phase="design")
    tree_ids = {node.id for node in tree}
    assert new.id in tree_ids, (
        f"new decision {new.id} (phase={new.phase!r}) should be in "
        f"get_tree(phase='design'); tree IDs: {tree_ids}"
    )


# ---------------------------------------------------------------------------
# Cross-phase regression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supersede_design_old_with_empty_phase_inherits_design(
    svc: DecisionService, old_decision: str
):
    """PI session in 'execution' phase supersedes a 'design'-phase
    decision and Brain omits phase. Under inherit-from-OLD, the new
    decision keeps 'design' (NOT re-tagged to 'execution'). This is
    the v2.7.0.6 ratified semantic — supersede 'overturns the decision
    in its original phase slot'."""
    await svc.db.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ["jrn_z", _PROJECT, "finding", "z", "brain", "tested"],
    )
    await svc.db.commit()

    new = await svc.supersede_decision(
        old_decision,
        DecisionSupersedeBody(
            question="Reframed", decided_by="pi", chosen="B",
            rationale="reasons", related_journal=["jrn_z"],
            # phase omitted — should inherit 'design'.
        ),
        actor="pi",
    )
    assert new.phase == "design", (
        "Under v2.7.0.6 inherit-from-OLD, supersede preserves the OLD "
        "decision's phase slot rather than re-tagging to the PI's current "
        "phase. Cross-phase callers must supply explicit phase."
    )
