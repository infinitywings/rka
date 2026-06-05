"""Tests for `rka.services.admin_repair` (v2.7.0.6).

The admin repair module surfaces two operations:

    list_orphan_supersedes(db, project_id) -> read-only discovery
    repair_orphan_supersedes(db, project_id, mapping, dry_run, actor)
        -> backfill missing supersede side effects per pair

The repair path REPLAYS steps 2-5 of the canonical
`DecisionService.supersede_decision` sequence (FK update, supersedes
entity_link, scope_version bump, staleness cascade, event +
review_queue) WITHOUT creating a new decision row (the new row already
exists from the v2.7.0.4 cockpit workaround).

Test coverage targets all four invariants from the v2.7.0.6 design:
    1. Discovery query finds the v2.7.0.4-shape orphans.
    2. Dry-run plans without mutating.
    3. Apply replays all 5 steps end-to-end.
    4. Re-run is idempotent (no duplicate links, no duplicate event,
       no duplicate review row, no scope-bump-twice).
    5. Pre-validation refuses cross-project / non-orphan / typo pairs.
    6. Per-pair transaction rollback on mid-flow failure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio

from rka.infra.database import Database
from rka.services.admin_repair import (
    _deterministic_link_id,
    _deterministic_review_id,
    _find_affected_entries,
    _validate_pair,
    list_orphan_supersedes,
    repair_orphan_supersedes,
)

_PROJECT = "proj_default"
_NOW = "2026-06-05T12:00:00Z"


@pytest_asyncio.fixture
async def corrupted_db(db: Database) -> Database:
    """Seed a v2.7.0.4-shape orphan supersede.

    Cockpit-workaround pattern:
      1. dec_OLD created with status='active'
      2. dec_NEW created (no supersedes link)
      3. dec_OLD.status flipped to 'superseded' via update_decision
         — but no superseded_by FK, no entity_link, no scope bump,
         no staleness cascade.
    """
    # OLD decision — already had a journal entry linking to it +
    # a claim sourced from that journal entry.
    await db.execute(
        """INSERT INTO decisions
           (id, project_id, question, chosen, rationale, decided_by, kind,
            phase, status, scope_version, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ["dec_old", _PROJECT, "Should we use A?", "yes",
         "initial framing", "brain", "decision", "design",
         "superseded", 1, _NOW, _NOW],
    )
    # NEW decision (created via cockpit workaround — no supersedes link)
    await db.execute(
        """INSERT INTO decisions
           (id, project_id, question, chosen, rationale, decided_by, kind,
            phase, status, scope_version, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ["dec_new", _PROJECT, "Reframed: should we use B?", "yes",
         "new evidence", "brain", "decision", "design",
         "active", 1, _NOW, _NOW],
    )
    # Journal entry referencing dec_old (via related_decisions JSON).
    await db.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence,
            related_decisions)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ["jrn_evidence", _PROJECT, "finding", "Evidence that supports OLD",
         "brain", "tested", json.dumps(["dec_old"])],
    )
    # Claim sourced from that journal entry. `content` is the text column;
    # `claim_type='evidence'` satisfies the NOT NULL + CHECK constraints.
    await db.execute(
        """INSERT INTO claims
           (id, project_id, source_entry_id, content, claim_type,
            stale, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ["clm_1", _PROJECT, "jrn_evidence",
         "A is the right choice", "evidence", 0, _NOW, _NOW],
    )
    await db.commit()
    return db


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_orphan_finds_the_pair(corrupted_db: Database):
    rows = await list_orphan_supersedes(corrupted_db, _PROJECT)
    assert len(rows) == 1
    assert rows[0]["id"] == "dec_old"
    assert rows[0]["question"] == "Should we use A?"


@pytest.mark.asyncio
async def test_list_orphan_excludes_legit_supersede(corrupted_db: Database):
    """An OLD row whose superseded_by is already set is NOT an orphan."""
    await corrupted_db.execute(
        "UPDATE decisions SET superseded_by = ? WHERE id = ?",
        ["dec_new", "dec_old"],
    )
    await corrupted_db.commit()
    rows = await list_orphan_supersedes(corrupted_db, _PROJECT)
    assert rows == []


@pytest.mark.asyncio
async def test_list_orphan_scoped_by_project(corrupted_db: Database):
    """Listing only returns rows for the requested project."""
    rows = await list_orphan_supersedes(corrupted_db, "prj_other")
    assert rows == []


# ---------------------------------------------------------------------------
# Dry-run preview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_emits_would_without_mutating(corrupted_db: Database):
    """Dry-run shows the WOULD plan but does not mutate the DB."""
    reports = await repair_orphan_supersedes(
        corrupted_db, _PROJECT, {"dec_old": "dec_new"}, dry_run=True,
    )
    assert len(reports) == 1
    r = reports[0]
    assert not r.applied
    states = {s.name: s.state for s in r.steps}
    assert states["scope_version_bump"] == "WOULD"
    assert states["superseded_by_fk"] == "WOULD"
    assert states["supersedes_entity_link"] == "WOULD"
    assert states["staleness_cascade"] == "WOULD"
    assert states["review_queue_row"] == "WOULD"

    # DB state unchanged.
    old = await corrupted_db.fetchone(
        "SELECT superseded_by, scope_version FROM decisions WHERE id = ?",
        ["dec_old"],
    )
    assert old["superseded_by"] is None
    new = await corrupted_db.fetchone(
        "SELECT scope_version FROM decisions WHERE id = ?", ["dec_new"],
    )
    assert new["scope_version"] == 1
    links = await corrupted_db.fetchall(
        "SELECT id FROM entity_links WHERE link_type = 'supersedes'",
    )
    assert links == []
    claims = await corrupted_db.fetchone(
        "SELECT stale FROM claims WHERE id = ?", ["clm_1"],
    )
    assert claims["stale"] == 0


# ---------------------------------------------------------------------------
# Apply path — all 5 steps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_repairs_all_five_steps(corrupted_db: Database):
    reports = await repair_orphan_supersedes(
        corrupted_db, _PROJECT, {"dec_old": "dec_new"},
        dry_run=False, actor="pi",
    )
    assert len(reports) == 1
    r = reports[0]
    assert r.applied
    assert not r.rolled_back
    states = {s.name: s.state for s in r.steps}
    assert states["scope_version_bump"] == "DONE"
    assert states["superseded_by_fk"] == "DONE"
    assert states["supersedes_entity_link"] == "DONE"
    assert states["staleness_cascade"] == "DONE"
    assert states["review_queue_row"] == "DONE"
    assert states["decision_superseded_event"] == "DONE"

    # FK + scope_version on the decisions rows.
    old = await corrupted_db.fetchone(
        "SELECT superseded_by, scope_version, status FROM decisions WHERE id = ?",
        ["dec_old"],
    )
    assert old["superseded_by"] == "dec_new"
    assert old["status"] == "superseded"
    new = await corrupted_db.fetchone(
        "SELECT scope_version FROM decisions WHERE id = ?", ["dec_new"],
    )
    assert new["scope_version"] == 2  # old.scope_version (1) + 1

    # entity_links row.
    link = await corrupted_db.fetchone(
        """SELECT id, source_id, target_id, created_by FROM entity_links
           WHERE link_type = 'supersedes' AND source_id = 'dec_new'""",
    )
    assert link is not None
    assert link["target_id"] == "dec_old"
    assert link["created_by"] == "pi"

    # Staleness cascade — claim marked stale=1.
    claim = await corrupted_db.fetchone(
        "SELECT stale FROM claims WHERE id = ?", ["clm_1"],
    )
    assert claim["stale"] == 1

    # decision_superseded event.
    event = await corrupted_db.fetchone(
        """SELECT entity_id, summary FROM events
           WHERE event_type = 'decision_superseded' AND entity_id = 'dec_old'""",
    )
    assert event is not None
    assert "dec_new" in event["summary"]

    # review_queue row with deterministic id.
    review_id = _deterministic_review_id("dec_old", "dec_new")
    review = await corrupted_db.fetchone(
        "SELECT item_id, flag, context FROM review_queue WHERE id = ?",
        [review_id],
    )
    assert review is not None
    assert review["item_id"] == "dec_new"
    assert review["flag"] == "re_distill_review"
    ctx = json.loads(review["context"])
    assert ctx["old_decision_id"] == "dec_old"
    assert "jrn_evidence" in ctx["affected_entries"]


# ---------------------------------------------------------------------------
# Idempotency — re-run does not duplicate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rerun_is_idempotent(corrupted_db: Database):
    """Apply twice. Second run shows ALREADY markers; no duplicate
    links, no duplicate event, no duplicate review row, no double
    scope_version bump."""
    await repair_orphan_supersedes(
        corrupted_db, _PROJECT, {"dec_old": "dec_new"}, dry_run=False,
    )
    reports = await repair_orphan_supersedes(
        corrupted_db, _PROJECT, {"dec_old": "dec_new"}, dry_run=False,
    )
    r = reports[0]
    states = {s.name: s.state for s in r.steps}
    assert states["scope_version_bump"] == "ALREADY"
    assert states["superseded_by_fk"] == "ALREADY"
    assert states["supersedes_entity_link"] == "ALREADY"
    assert states["review_queue_row"] == "ALREADY"
    # Event MUST also be ALREADY on the no-mutation rerun (needs_event
    # guard — closes the duplicate-event adversarial amendment).
    assert states["decision_superseded_event"] == "ALREADY"

    # exactly ONE entity_links row.
    links = await corrupted_db.fetchall(
        "SELECT id FROM entity_links WHERE link_type = 'supersedes'",
    )
    assert len(links) == 1

    # exactly ONE event.
    events = await corrupted_db.fetchall(
        "SELECT id FROM events WHERE event_type = 'decision_superseded' "
        "AND entity_id = 'dec_old'",
    )
    assert len(events) == 1

    # exactly ONE review_queue row.
    reviews = await corrupted_db.fetchall(
        "SELECT id FROM review_queue WHERE item_id = 'dec_new'",
    )
    assert len(reviews) == 1

    # new.scope_version did not double-bump (still old+1, not old+2).
    new = await corrupted_db.fetchone(
        "SELECT scope_version FROM decisions WHERE id = ?", ["dec_new"],
    )
    assert new["scope_version"] == 2


# ---------------------------------------------------------------------------
# Pre-validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refuses_when_old_not_superseded(corrupted_db: Database):
    """If old.status != 'superseded', the pair is not an orphan."""
    await corrupted_db.execute(
        "UPDATE decisions SET status = 'active' WHERE id = 'dec_old'"
    )
    await corrupted_db.commit()
    reports = await repair_orphan_supersedes(
        corrupted_db, _PROJECT, {"dec_old": "dec_new"}, dry_run=False,
    )
    assert reports[0].rolled_back
    assert "not 'superseded'" in (reports[0].failure_reason or "")


@pytest.mark.asyncio
async def test_refuses_when_superseded_by_points_elsewhere(
    corrupted_db: Database,
):
    """A legit supersede link must not be overwritten."""
    # Seed an actual decision dec_other so the FK is satisfiable.
    await corrupted_db.execute(
        """INSERT INTO decisions
           (id, project_id, question, decided_by, kind, phase, status,
            scope_version, created_at, updated_at)
           VALUES ('dec_other', ?, 'Other', 'brain', 'decision', 'design',
                   'active', 1, ?, ?)""",
        [_PROJECT, _NOW, _NOW],
    )
    await corrupted_db.execute(
        "UPDATE decisions SET superseded_by = 'dec_other' WHERE id = 'dec_old'"
    )
    await corrupted_db.commit()
    reports = await repair_orphan_supersedes(
        corrupted_db, _PROJECT, {"dec_old": "dec_new"}, dry_run=False,
    )
    assert reports[0].rolled_back
    assert "pointing at a different decision" in (
        reports[0].failure_reason or ""
    )


@pytest.mark.asyncio
async def test_refuses_when_new_decision_missing(corrupted_db: Database):
    """Typo in --map shows up here."""
    reports = await repair_orphan_supersedes(
        corrupted_db, _PROJECT, {"dec_old": "dec_does_not_exist"},
        dry_run=False,
    )
    assert reports[0].rolled_back
    assert "not found" in (reports[0].failure_reason or "")


@pytest.mark.asyncio
async def test_pairs_with_different_projects_refused(corrupted_db: Database):
    """Cross-project pair: old in proj_default, new in prj_other —
    refused at validation."""
    await corrupted_db.execute(
        """INSERT INTO decisions
           (id, project_id, question, decided_by, kind, phase, status,
            created_at, updated_at)
           VALUES ('dec_other_proj', 'prj_other', 'Other', 'brain',
                   'decision', 'design', 'active', ?, ?)""",
        [_NOW, _NOW],
    )
    await corrupted_db.commit()
    reports = await repair_orphan_supersedes(
        corrupted_db, _PROJECT, {"dec_old": "dec_other_proj"},
        dry_run=False,
    )
    assert reports[0].rolled_back
    assert "not found in project" in (reports[0].failure_reason or "")


# ---------------------------------------------------------------------------
# Per-pair rollback on mid-flow failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_on_mid_pair_failure(
    corrupted_db: Database, monkeypatch
):
    """Monkeypatch db.execute to raise on the staleness cascade.
    Verify old.superseded_by reverts to NULL, scope_version reverts,
    entity_link absent, no review_queue row. Per-pair atomicity."""
    original_execute = corrupted_db.execute
    call_counter = {"n": 0}

    async def flaky_execute(sql, params=None):
        call_counter["n"] += 1
        # First several calls succeed (BEGIN, scope_bump, FK, link); the
        # staleness cascade UPDATE on claims raises.
        if "UPDATE claims" in sql:
            raise RuntimeError("simulated cascade failure")
        return await original_execute(sql, params)

    monkeypatch.setattr(corrupted_db, "execute", flaky_execute)

    reports = await repair_orphan_supersedes(
        corrupted_db, _PROJECT, {"dec_old": "dec_new"}, dry_run=False,
    )
    assert reports[0].rolled_back
    assert "simulated cascade failure" in (reports[0].failure_reason or "")

    # Restore for verification queries.
    monkeypatch.setattr(corrupted_db, "execute", original_execute)
    old = await corrupted_db.fetchone(
        "SELECT superseded_by FROM decisions WHERE id = ?", ["dec_old"],
    )
    assert old["superseded_by"] is None, (
        "ROLLBACK should revert the FK update"
    )
    new = await corrupted_db.fetchone(
        "SELECT scope_version FROM decisions WHERE id = ?", ["dec_new"],
    )
    assert new["scope_version"] == 1, (
        "ROLLBACK should revert the scope_version bump"
    )
    links = await corrupted_db.fetchall(
        "SELECT id FROM entity_links WHERE link_type = 'supersedes'",
    )
    assert links == []
    reviews = await corrupted_db.fetchall(
        "SELECT id FROM review_queue WHERE item_id = 'dec_new'",
    )
    assert reviews == []


# ---------------------------------------------------------------------------
# Project-id scoping on affected-entry discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_affected_entries_filters_by_project_id(corrupted_db: Database):
    """A cross-project journal entry linking to dec_old (somehow) must
    NOT be picked up by the affected-entry discovery — only entries
    in the same project are eligible for staleness cascade."""
    # Seed a "cross-project" journal entry — unusual but possible if the
    # DB was migrated from a pre-project-scoping era.
    await corrupted_db.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence,
            related_decisions)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ["jrn_other_proj", "prj_other", "finding", "x", "brain", "tested",
         json.dumps(["dec_old"])],
    )
    await corrupted_db.commit()
    affected = await _find_affected_entries(
        corrupted_db, _PROJECT, "dec_old",
    )
    assert "jrn_evidence" in affected
    assert "jrn_other_proj" not in affected, (
        "cross-project journal entries must not be cascaded"
    )


# ---------------------------------------------------------------------------
# Deterministic ID helpers
# ---------------------------------------------------------------------------


def test_deterministic_link_id_stable_across_calls():
    a = _deterministic_link_id("dec_new", "dec_old")
    b = _deterministic_link_id("dec_new", "dec_old")
    assert a == b
    assert a.startswith("link_")


def test_deterministic_review_id_stable_across_calls():
    a = _deterministic_review_id("dec_old", "dec_new")
    b = _deterministic_review_id("dec_old", "dec_new")
    assert a == b
    assert a.startswith("review_")


def test_deterministic_link_id_distinct_per_pair():
    """Different pairs get different IDs (collision check)."""
    assert _deterministic_link_id("dec_a", "dec_b") != _deterministic_link_id(
        "dec_a", "dec_c"
    )
    assert _deterministic_link_id("dec_a", "dec_b") != _deterministic_link_id(
        "dec_b", "dec_a"
    )


# ---------------------------------------------------------------------------
# Empty mapping is a no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_mapping_returns_empty_reports(corrupted_db: Database):
    reports = await repair_orphan_supersedes(
        corrupted_db, _PROJECT, {}, dry_run=False,
    )
    assert reports == []
