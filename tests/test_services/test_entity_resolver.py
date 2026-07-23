"""Focused contract tests for project-attested bulk entity resolution."""

from __future__ import annotations

import json

import pytest

from rka.infra.database import Database
from rka.services.entity_resolver import EntityResolverService


PROJECT_ID = "proj_default"
OTHER_PROJECT_ID = "prj_resolver_other"


async def _insert_journal(
    db: Database,
    entry_id: str,
    project_id: str,
    *,
    confidence: str = "tested",
    status: str = "active",
    superseded_by: str | None = None,
) -> None:
    await db.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence, status, superseded_by)
           VALUES (?, ?, 'note', ?, 'executor', ?, ?, ?)""",
        [
            entry_id,
            project_id,
            f"Source content for {entry_id}",
            confidence,
            status,
            superseded_by,
        ],
    )


async def _insert_claim(
    db: Database,
    claim_id: str,
    source_id: str,
    project_id: str,
    *,
    verified: int = 1,
    staleness: str = "green",
) -> None:
    await db.execute(
        """INSERT INTO claims
           (id, source_entry_id, claim_type, content, verified, evidence_status,
            stale, staleness, project_id)
           VALUES (?, ?, 'result', ?, ?, 'supported', 0, ?, ?)""",
        [
            claim_id,
            source_id,
            f"Claim content for {claim_id}",
            verified,
            staleness,
            project_id,
        ],
    )


@pytest.mark.asyncio
async def test_bulk_resolution_is_project_attested_read_only_and_closes_claim_sources(
    db: Database,
) -> None:
    source_id = "jrn_resolver_source"
    claim_id = "clm_resolver_primary"
    counterclaim_id = "clm_resolver_counter"
    await _insert_journal(db, source_id, PROJECT_ID)
    await _insert_claim(db, claim_id, source_id, PROJECT_ID)
    await _insert_claim(db, counterclaim_id, source_id, PROJECT_ID)
    await db.execute(
        """INSERT INTO tags (tag, entity_type, entity_id, project_id)
           VALUES ('manuscript-ready', 'journal', ?, ?)""",
        [source_id, PROJECT_ID],
    )
    await db.execute(
        """INSERT INTO entity_links
           (id, source_type, source_id, link_type, target_type, target_id,
            created_by, project_id)
           VALUES (
               'lnk_resolver_source',
               'claim',
               ?,
               'derived_from',
               'journal',
               ?,
               'system',
               ?
           )""",
        [claim_id, source_id, PROJECT_ID],
    )
    await db.execute(
        """INSERT INTO claim_edges
           (id, source_claim_id, target_claim_id, relation, project_id)
           VALUES ('ced_resolver_contradiction', ?, ?, 'contradicts', ?)""",
        [claim_id, counterclaim_id, PROJECT_ID],
    )
    await db.commit()

    changes_before = db.conn.total_changes
    packet = await EntityResolverService(db).resolve_entities(
        PROJECT_ID,
        [claim_id, claim_id],
        include_sources=True,
        include_edges=True,
    )
    changes_after = db.conn.total_changes

    assert changes_after == changes_before
    assert packet["schema_version"] == "rka-entity-resolution/v1"
    assert packet["project_id"] == PROJECT_ID
    assert packet["requested_ids"] == [claim_id]
    assert list(packet["entities"]) == sorted([claim_id, source_id])
    assert packet["summary"] == {
        "requested": 1,
        "duplicates_removed": 1,
        "resolved": 1,
        "missing": 0,
        "wrong_project": 0,
        "unscoped": 0,
        "unknown_type": 0,
    }

    claim = packet["entities"][claim_id]
    assert claim["found"] is True
    assert claim["outcome"] == "resolved"
    assert claim["type"] == "claim"
    assert claim["project_id"] == PROJECT_ID
    assert claim["verified"] is True
    assert claim["contradicted"] is True
    assert claim["record"]["contradicted"] is True
    assert claim["currentness"] == {
        "is_current": True,
        "state": "current",
        "reasons": [],
        "warnings": [],
    }
    assert claim["revision"]["fingerprint"].startswith("sha256:")

    source = packet["entities"][source_id]
    assert source["type"] == "journal"
    assert source["record"]["type"] == "note"
    assert source["tags"] == ["manuscript-ready"]
    assert packet["terminal_sources"] == {
        claim_id: {
            "claim_id": claim_id,
            "source_entry_id": source_id,
            "outcome": "resolved",
            "terminal": True,
        }
    }
    assert [row["id"] for row in packet["entity_links"]] == [
        "lnk_resolver_source"
    ]
    assert [row["id"] for row in packet["claim_edges"]] == [
        "ced_resolver_contradiction"
    ]

    second_packet = await EntityResolverService(db).resolve_entities(
        PROJECT_ID,
        [claim_id],
        include_sources=True,
    )
    assert (
        second_packet["entities"][claim_id]["revision"]
        == claim["revision"]
    )


@pytest.mark.asyncio
async def test_resolution_distinguishes_missing_wrong_project_and_unknown_type(
    db: Database,
) -> None:
    await db.execute(
        """INSERT INTO projects (id, name, created_by)
           VALUES (?, 'Resolver Other Project', 'system')""",
        [OTHER_PROJECT_ID],
    )
    await _insert_journal(db, "jrn_resolver_foreign", OTHER_PROJECT_ID)
    await db.commit()

    packet = await EntityResolverService(db).resolve_entities(
        PROJECT_ID,
        [
            "zzz_resolver_unknown",
            "jrn_resolver_missing",
            "jrn_resolver_foreign",
        ],
    )

    assert packet["requested_ids"] == [
        "jrn_resolver_foreign",
        "jrn_resolver_missing",
        "zzz_resolver_unknown",
    ]
    foreign = packet["entities"]["jrn_resolver_foreign"]
    assert foreign == {
        "id": "jrn_resolver_foreign",
        "found": False,
        "outcome": "wrong_project",
        "type": "journal",
        "project_id": None,
        "revision": None,
        "currentness": {
            "is_current": False,
            "state": "unresolved",
            "reasons": ["wrong_project"],
            "warnings": [],
        },
        "tags": [],
        "record": None,
    }
    assert packet["entities"]["jrn_resolver_missing"]["outcome"] == "missing"
    assert packet["entities"]["zzz_resolver_unknown"]["outcome"] == "unknown_type"
    assert packet["summary"]["wrong_project"] == 1
    assert packet["summary"]["missing"] == 1
    assert packet["summary"]["unknown_type"] == 1


@pytest.mark.asyncio
async def test_currentness_fails_closed_on_expired_retracted_and_invalid_metadata(
    db: Database,
) -> None:
    await _insert_journal(
        db,
        "jrn_resolver_retracted",
        PROJECT_ID,
        confidence="retracted",
        status="retracted",
    )
    await _insert_journal(db, "jrn_resolver_claim_source", PROJECT_ID)
    await _insert_claim(
        db,
        "clm_resolver_invalid_staleness",
        "jrn_resolver_claim_source",
        PROJECT_ID,
        staleness="mystery",
    )
    await db.execute(
        """UPDATE claims
           SET valid_until = '2000-01-01T00:00:00Z'
           WHERE id = 'clm_resolver_invalid_staleness'"""
    )
    await db.commit()

    packet = await EntityResolverService(db).resolve_entities(
        PROJECT_ID,
        ["jrn_resolver_retracted", "clm_resolver_invalid_staleness"],
    )

    journal_currency = packet["entities"]["jrn_resolver_retracted"]["currentness"]
    assert journal_currency["is_current"] is False
    assert journal_currency["reasons"] == [
        "confidence:retracted",
        "status:retracted",
    ]
    claim_currency = packet["entities"]["clm_resolver_invalid_staleness"][
        "currentness"
    ]
    assert claim_currency["is_current"] is False
    assert claim_currency["reasons"] == [
        "expired",
        "invalid_staleness:mystery",
    ]


@pytest.mark.asyncio
async def test_same_type_ids_are_loaded_in_one_batch_and_json_is_normalized(
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision_ids = [
        "dec_resolver_charlie",
        "dec_resolver_alpha",
        "dec_resolver_bravo",
    ]
    for index, decision_id in enumerate(decision_ids, start=1):
        await db.execute(
            """INSERT INTO decisions
               (id, phase, question, decided_by, project_id, related_journal,
                scope_version)
               VALUES (?, 'planning', ?, 'pi', ?, ?, ?)""",
            [
                decision_id,
                f"Question {index}",
                PROJECT_ID,
                json.dumps(["jrn_resolver_manuscript"]),
                index,
            ],
        )
    await db.commit()

    original_fetchall = db.fetchall
    queries: list[str] = []

    async def tracked_fetchall(sql: str, params=None):
        queries.append(sql)
        return await original_fetchall(sql, params)

    monkeypatch.setattr(db, "fetchall", tracked_fetchall)
    packet = await EntityResolverService(db).resolve_entities(
        PROJECT_ID,
        list(reversed(decision_ids)),
    )

    decision_queries = [
        query
        for query in queries
        if "SELECT * FROM decisions WHERE id IN" in query
    ]
    assert len(decision_queries) == 1
    assert packet["requested_ids"] == sorted(decision_ids)
    for index, decision_id in enumerate(decision_ids, start=1):
        entity = packet["entities"][decision_id]
        assert entity["related_journal"] == ["jrn_resolver_manuscript"]
        assert entity["revision"]["version"] == index


@pytest.mark.asyncio
async def test_unknown_project_and_malformed_identity_inputs_are_rejected(
    db: Database,
) -> None:
    resolver = EntityResolverService(db)

    with pytest.raises(ValueError, match="Unknown project_id"):
        await resolver.resolve_entities("prj_does_not_exist", [])
    with pytest.raises(ValueError, match="surrounding whitespace"):
        await resolver.resolve_entities(PROJECT_ID, [" jrn_bad"])
    with pytest.raises(ValueError, match="non-empty strings"):
        await resolver.resolve_entities(PROJECT_ID, [""])
    with pytest.raises(ValueError, match="sequence of entity-id strings"):
        await resolver.resolve_entities(PROJECT_ID, "jrn_not_a_sequence")


@pytest.mark.asyncio
async def test_source_closure_preserves_unresolved_claim_outcome(db: Database) -> None:
    packet = await EntityResolverService(db).resolve_entities(
        PROJECT_ID,
        ["clm_resolver_missing"],
        include_sources=True,
    )

    assert packet["terminal_sources"]["clm_resolver_missing"] == {
        "claim_id": "clm_resolver_missing",
        "source_entry_id": None,
        "outcome": "claim_unresolved",
        "terminal": False,
    }


@pytest.mark.asyncio
async def test_native_manuscript_entities_resolve_with_revision_and_state_currency(
    db: Database,
) -> None:
    await db.execute(
        """INSERT INTO manuscripts
           (id, project_id, title, phase, state, revision)
           VALUES (
               'man_resolver_native',
               ?,
               'Native Resolver Manuscript',
               'drafting',
               'on_hold',
               4
           )""",
        [PROJECT_ID],
    )
    await db.execute(
        """INSERT INTO manuscript_claims
           (id, manuscript_id, project_id, local_key, kind, state)
           VALUES (
               'mcl_resolver_native',
               'man_resolver_native',
               ?,
               'C1',
               'empirical',
               'retired'
           )""",
        [PROJECT_ID],
    )
    await db.execute(
        """INSERT INTO literature
           (id, title, status, added_by, project_id)
           VALUES (
               'lit_resolver_native',
               'Resolver reference',
               'cited',
               'pi',
               ?
           )""",
        [PROJECT_ID],
    )
    await db.execute(
        """INSERT INTO manuscript_reference_members
           (id, manuscript_id, project_id, citation_key, literature_id)
           VALUES (
               'mrf_resolver_native',
               'man_resolver_native',
               ?,
               'resolver2026',
               'lit_resolver_native'
           )""",
        [PROJECT_ID],
    )
    await db.commit()

    packet = await EntityResolverService(db).resolve_entities(
        PROJECT_ID,
        [
            "mcl_resolver_native",
            "man_resolver_native",
            "mrf_resolver_native",
        ],
    )

    manuscript = packet["entities"]["man_resolver_native"]
    assert manuscript["type"] == "manuscript"
    assert manuscript["revision"]["version"] == 4
    assert manuscript["record"]["revision"] == 4
    assert manuscript["currentness"] == {
        "is_current": True,
        "state": "current",
        "reasons": [],
        "warnings": ["state:on_hold"],
    }

    claim = packet["entities"]["mcl_resolver_native"]
    assert claim["type"] == "manuscript_claim"
    assert claim["currentness"] == {
        "is_current": False,
        "state": "not_current",
        "reasons": ["state:retired"],
        "warnings": [],
    }
    reference = packet["entities"]["mrf_resolver_native"]
    assert reference["type"] == "manuscript_reference"
    assert reference["citation_key"] == "resolver2026"
    assert reference["literature_id"] == "lit_resolver_native"
    assert reference["currentness"]["is_current"] is True
