"""Tests for the eval-v3 theme A-E backend wave (2026-06-12).

Covers: staleness blast-radius, staleness review filing, link-support audit,
mission guard, belief-as-of, research-health metrics, and search query
understanding (temporal/actor constraint parsing).
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from rka.infra.database import Database
from rka.services.graph import GraphService
from rka.services.maintenance import MaintenanceService
from rka.services.search import SearchService
from rka.services.verification import VerificationService

PID = "proj_default"


@pytest_asyncio.fixture
async def seeded(db: Database):
    """A small KB with a supersede chain, dependents, and a contradiction."""
    # journal: evidence -> superseded by corrected entry
    await db.execute(
        "INSERT INTO journal (id, type, content, source, confidence, phase, project_id, "
        "superseded_by) VALUES ('jrn_old', 'note', 'rollback counter lives in internal flash "
        "storage region beside the bootloader metadata page written when manufacture "
        "provisioning completes', 'brain', 'superseded', 'p1', ?, 'jrn_new')", [PID])
    await db.execute(
        "INSERT INTO journal (id, type, content, source, confidence, phase, project_id, "
        "supersedes) VALUES ('jrn_new', 'note', 'rollback counter anchored in secure element "
        "OTP one time programmable region resists physical attacker wipe', 'brain', "
        "'tested', 'p1', ?, 'jrn_old')", [PID])
    # decision justified by the OLD (now superseded) evidence -> impacted
    await db.execute(
        "INSERT INTO decisions (id, question, rationale, decided_by, status, phase, project_id) "
        "VALUES ('dec_dep', 'Where to store the rollback counter?', "
        "'internal flash storage region is sufficient for the counter', 'brain', 'active', "
        "'p1', ?)", [PID])
    await db.execute(
        "INSERT INTO entity_links (id, source_type, source_id, link_type, target_type, "
        "target_id, created_by, project_id) VALUES ('lnk_j', 'decision', 'dec_dep', "
        "'justified_by', 'journal', 'jrn_old', 'brain', ?)", [PID])
    # mission motivated by the dependent decision (depth-2 impact)
    await db.execute(
        "INSERT INTO missions (id, objective, phase, status, project_id) VALUES "
        "('mis_dep', 'Implement flash storage rollback counter for the meter', 'p1', "
        "'pending', ?)", [PID])
    await db.execute(
        "INSERT INTO entity_links (id, source_type, source_id, link_type, target_type, "
        "target_id, created_by, project_id) VALUES ('lnk_m', 'decision', 'dec_dep', "
        "'motivated', 'mission', 'mis_dep', 'brain', ?)", [PID])
    # contradiction between two claims
    await db.execute(
        "INSERT INTO journal (id, type, content, source, confidence, phase, project_id) "
        "VALUES ('jrn_src', 'note', 'rekey cost measurements', 'brain', 'tested', 'p1', ?)",
        [PID])
    for cid, content in (
        ("clm_a", "fleet rekey costs six hours of airtime"),
        ("clm_b", "fleet rekey costs eight minutes of airtime"),
    ):
        await db.execute(
            "INSERT INTO claims (id, source_entry_id, claim_type, content, project_id) "
            "VALUES (?, 'jrn_src', 'result', ?, ?)", [cid, content, PID])
    await db.execute(
        "INSERT INTO claim_edges (id, source_claim_id, target_claim_id, relation, project_id) "
        "VALUES ('ce_c', 'clm_b', 'clm_a', 'contradicts', ?)", [PID])
    await db.commit()
    return db


class TestStalenessImpact:
    @pytest.mark.asyncio
    async def test_dependents_found_with_depth_and_via(self, seeded: Database):
        svc = GraphService(seeded)
        out = await svc.staleness_impact("jrn_old", project_id=PID)
        ids = {n["id"]: n for n in out["impacted"]}
        assert out["root_is_stale"] is True
        assert "dec_dep" in ids and ids["dec_dep"]["depth"] == 1
        assert ids["dec_dep"]["via"]["link_type"] == "justified_by"
        assert "mis_dep" in ids and ids["mis_dep"]["depth"] == 2

    @pytest.mark.asyncio
    async def test_produced_links_do_not_propagate(self, seeded: Database):
        # raw observations are immutable: mission --produced--> journal must NOT
        # mark the journal as impacted when the mission's decision is stale
        await seeded.execute(
            "INSERT INTO journal (id, type, content, source, confidence, phase, project_id) "
            "VALUES ('jrn_raw', 'log', 'raw finding from the mission run', 'executor', "
            "'verified', 'p1', ?)", [PID])
        await seeded.execute(
            "INSERT INTO entity_links (id, source_type, source_id, link_type, target_type, "
            "target_id, created_by, project_id) VALUES ('lnk_p', 'mission', 'mis_dep', "
            "'produced', 'journal', 'jrn_raw', 'executor', ?)", [PID])
        await seeded.commit()
        out = await GraphService(seeded).staleness_impact("jrn_old", project_id=PID)
        assert "jrn_raw" not in {n["id"] for n in out["impacted"]}


class TestStalenessReviewFiling:
    @pytest.mark.asyncio
    async def test_files_and_is_idempotent(self, seeded: Database):
        svc = VerificationService(seeded, project_id=PID)
        out1 = await svc.file_staleness_reviews()
        assert out1["filed"] >= 1
        filed_ids = {i["item_id"] for i in out1["items"]}
        assert "dec_dep" in filed_ids
        # successor of the chain must not be flagged as resting on the root
        assert "jrn_new" not in filed_ids
        out2 = await svc.file_staleness_reviews()
        assert out2["filed"] == 0  # idempotent

    @pytest.mark.asyncio
    async def test_filed_rows_pass_flag_check(self, seeded: Database):
        svc = VerificationService(seeded, project_id=PID)
        await svc.file_staleness_reviews()
        row = await seeded.fetchone(
            "SELECT flag, status FROM review_queue WHERE item_id = 'dec_dep'")
        assert row is not None and row["flag"] == "stale_dependency"


class TestLinkSupportAudit:
    @pytest.mark.asyncio
    async def test_unrelated_rationale_flagged(self, seeded: Database):
        # dec_dep rationale mentions flash storage; replace with unrelated text
        await seeded.execute(
            "UPDATE decisions SET rationale = 'quantum surface code distance thresholds "
            "dominate the logical error rate scaling behaviour entirely' WHERE id = 'dec_dep'")
        await seeded.commit()
        out = await VerificationService(seeded, project_id=PID).audit_link_support()
        assert any(f["item_id"] == "dec_dep" for f in out["unsupported"])

    @pytest.mark.asyncio
    async def test_supported_rationale_not_flagged(self, seeded: Database):
        out = await VerificationService(seeded, project_id=PID).audit_link_support()
        assert not any(f["item_id"] == "dec_dep" for f in out["unsupported"])


class TestMissionGuard:
    @pytest.mark.asyncio
    async def test_superseded_and_contradicted_surfaced(self, seeded: Database):
        svc = VerificationService(seeded, project_id=PID)
        out = await svc.mission_guard("mis_dep")
        kinds = {w["kind"] for w in out["warnings"]}
        # mission objective mentions flash/rollback/counter -> overlaps jrn_old
        assert "superseded" in kinds
        sup = next(w for w in out["warnings"] if w["kind"] == "superseded")
        assert sup["superseded_by"] == "jrn_new"

    @pytest.mark.asyncio
    async def test_unknown_mission_raises(self, seeded: Database):
        with pytest.raises(ValueError):
            await VerificationService(seeded, project_id=PID).mission_guard("mis_nope")


class TestBeliefAsOf:
    @pytest.mark.asyncio
    async def test_supersession_respects_successor_created_at(self, db: Database):
        # successor first: decisions.superseded_by carries a FOREIGN KEY
        await db.execute(
            "INSERT INTO decisions (id, question, chosen, decided_by, status, phase, "
            "project_id, created_at) VALUES ('dec_v2', 'Scheme? (revised)', 'Dilithium2', "
            "'pi', 'active', 'p1', ?, '2026-03-01T00:00:00Z')", [PID])
        await db.execute(
            "INSERT INTO decisions (id, question, chosen, decided_by, status, phase, "
            "project_id, superseded_by, created_at) VALUES ('dec_v1', 'Scheme?', 'Ed25519', "
            "'pi', 'superseded', 'p1', ?, 'dec_v2', '2026-01-10T00:00:00Z')", [PID])
        await db.commit()
        svc = VerificationService(db, project_id=PID)
        # In February: v1 still believed current (successor not yet created)
        feb = await svc.belief_as_of("2026-02-01T00:00:00Z")
        feb_ids = {d["id"] for d in feb["then_current"]["decisions"]}
        assert "dec_v1" in feb_ids and "dec_v2" not in feb_ids
        assert any(c["id"] == "dec_v1" for c in feb["changed_since"])
        # In April: v2 current, v1 not
        apr = await svc.belief_as_of("2026-04-01T00:00:00Z")
        apr_ids = {d["id"] for d in apr["then_current"]["decisions"]}
        assert "dec_v2" in apr_ids and "dec_v1" not in apr_ids


class TestResearchHealth:
    @pytest.mark.asyncio
    async def test_metrics_shape_and_counts(self, seeded: Database):
        out = await MaintenanceService(seeded, project_id=PID).research_health()
        pc = out["provenance_coverage"]
        assert pc["decisions"]["total"] >= 1
        assert pc["claims"]["covered"] == pc["claims"]["total"] == 2
        assert "research_debt_trajectory_weekly" in out
        assert "bookkeeping_overhead" in out


class TestQueryUnderstanding:
    def test_temporal_and_actor_parsed_and_stripped(self):
        q, c = SearchService.parse_query_constraints(
            "PI directives this week about the orchestrator")
        assert c["source"] == "pi" and c["journal_type"] == "directive"
        assert c["created_within"] == "-7 days"
        assert "directives" not in q and "week" not in q and "orchestrator" in q

    def test_plain_query_unconstrained(self):
        q, c = SearchService.parse_query_constraints("embedding backend configuration")
        assert c == {} and q == "embedding backend configuration"

    @pytest.mark.asyncio
    async def test_actor_anchored_search_filters_by_source(self, seeded: Database):
        await seeded.execute(
            "INSERT INTO journal (id, type, content, source, confidence, phase, project_id) "
            "VALUES ('jrn_pi', 'directive', 'orchestrator rollout must wait for ratification', "
            "'pi', 'verified', 'p1', ?)", [PID])
        await seeded.execute(
            "INSERT INTO journal (id, type, content, source, confidence, phase, project_id) "
            "VALUES ('jrn_br', 'note', 'orchestrator rollout design notes', 'brain', "
            "'hypothesis', 'p1', ?)", [PID])
        await seeded.execute(
            "INSERT INTO fts_journal (id, content, summary) VALUES "
            "('jrn_pi', 'orchestrator rollout must wait for ratification', '')")
        await seeded.execute(
            "INSERT INTO fts_journal (id, content, summary) VALUES "
            "('jrn_br', 'orchestrator rollout design notes', '')")
        await seeded.commit()
        svc = SearchService(db=seeded, embeddings=None)
        hits = await svc.search("PI directives about orchestrator rollout", limit=10)
        ids = [h.entity_id for h in hits]
        assert "jrn_pi" in ids
        assert "jrn_br" not in ids  # brain note filtered by the actor anchor
