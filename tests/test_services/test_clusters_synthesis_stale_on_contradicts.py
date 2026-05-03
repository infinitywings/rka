"""Regression test for v2.4 Improvement 3 — synthesis_stale fire on contradicts edge.

Per dec_01KQQPE47H56E40A8KBDDT4BZT (mis_01KQQS3DYQ2EVJV288PNHX0CMY).

When a `contradicts` edge is inserted in claim_edges and one of its endpoints
is a member of an evidence_cluster, that cluster must have
`needs_reprocessing = 1` set so the maintenance manifest surfaces it for Brain
review (cluster's existing synthesis is now contradicted by new evidence).
"""

from __future__ import annotations

import pytest_asyncio

from rka.infra.database import Database
from rka.models.claim import ClaimCreate, ClaimEdgeCreate
from rka.models.journal import JournalEntryCreate
from rka.models.project import ProjectCreate
from rka.services.claims import ClaimService
from rka.services.notes import NoteService
from rka.services.project import ProjectService

PROJECT_ID = "proj_test_synthesis_stale"


@pytest_asyncio.fixture
async def cluster_with_member_claims(db: Database):
    """Project + journal entry + 2 claims as cluster members + 1 external claim."""
    project_svc = ProjectService(db)
    await project_svc.create_project(
        ProjectCreate(id=PROJECT_ID, name="Test Synthesis Stale", description="test"),
        actor="system",
    )

    note_svc = NoteService(db, project_id=PROJECT_ID)
    entry = await note_svc.create(
        JournalEntryCreate(
            content="Source entry for member claims.",
            type="finding",
            source="executor",
            confidence="tested",
        ),
        actor="executor",
    )

    claims_svc = ClaimService(db, project_id=PROJECT_ID)

    # 2 member claims
    c1 = await claims_svc.create(ClaimCreate(
        source_entry_id=entry.id, claim_type="evidence", content="Member claim 1.",
    ))
    c2 = await claims_svc.create(ClaimCreate(
        source_entry_id=entry.id, claim_type="evidence", content="Member claim 2.",
    ))
    # 1 external claim (not in cluster)
    c_ext = await claims_svc.create(ClaimCreate(
        source_entry_id=entry.id, claim_type="evidence", content="External contradicting claim.",
    ))

    # Create a cluster directly via SQL (no public ClusterService.create here; minimal-diff fixture).
    cluster_id = "ecl_test_synthesis_stale_001"
    await db.execute(
        """INSERT INTO evidence_clusters
           (id, label, synthesis, confidence, claim_count, needs_reprocessing,
            project_id, created_at, updated_at)
           VALUES (?, 'Test Cluster', 'Initial synthesis paragraph.',
                   'moderate', 0, 0, ?,
                   strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
                   strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))""",
        [cluster_id, PROJECT_ID],
    )
    await db.commit()

    # Wire member_of edges via the same generic create_edge path (so
    # claim_count gets bumped by the engine, not by the test).
    await claims_svc.create_edge(ClaimEdgeCreate(
        source_claim_id=c1.id, cluster_id=cluster_id, relation="member_of", confidence=1.0,
    ))
    await claims_svc.create_edge(ClaimEdgeCreate(
        source_claim_id=c2.id, cluster_id=cluster_id, relation="member_of", confidence=1.0,
    ))

    return {
        "db": db,
        "claims_svc": claims_svc,
        "cluster_id": cluster_id,
        "member_claim_id": c1.id,
        "external_claim_id": c_ext.id,
    }


async def _get_needs_reprocessing(db: Database, cluster_id: str) -> int:
    row = await db.fetchone(
        "SELECT needs_reprocessing FROM evidence_clusters WHERE id = ? AND project_id = ?",
        [cluster_id, PROJECT_ID],
    )
    return int(row["needs_reprocessing"]) if row else -1


class TestSynthesisStaleOnContradicts:
    async def test_member_of_insertion_does_not_fire_flag(self, cluster_with_member_claims):
        """Sanity check: member_of insertions (the fixture) do NOT set needs_reprocessing."""
        f = cluster_with_member_claims
        flag = await _get_needs_reprocessing(f["db"], f["cluster_id"])
        assert flag == 0, "Member_of insertions should not flag clusters as needing reprocessing."

    async def test_contradicts_to_member_fires_flag(self, cluster_with_member_claims):
        """Inserting a contradicts edge from a cluster member to an external claim
        sets needs_reprocessing=1 on the cluster."""
        f = cluster_with_member_claims
        await f["claims_svc"].create_edge(ClaimEdgeCreate(
            source_claim_id=f["member_claim_id"],
            target_claim_id=f["external_claim_id"],
            relation="contradicts",
            confidence=0.8,
        ))
        flag = await _get_needs_reprocessing(f["db"], f["cluster_id"])
        assert flag == 1, "Contradicts edge from cluster member must flag cluster."

    async def test_contradicts_from_external_to_member_fires_flag(self, cluster_with_member_claims):
        """Direction-symmetric: contradicts edge from external claim TO a cluster
        member also flags the cluster (the helper checks both endpoints)."""
        f = cluster_with_member_claims
        await f["claims_svc"].create_edge(ClaimEdgeCreate(
            source_claim_id=f["external_claim_id"],
            target_claim_id=f["member_claim_id"],
            relation="contradicts",
            confidence=0.8,
        ))
        flag = await _get_needs_reprocessing(f["db"], f["cluster_id"])
        assert flag == 1, "Contradicts edge into cluster member must also flag cluster (symmetric)."

    async def test_supports_does_not_fire_flag(self, cluster_with_member_claims):
        """Negative case: supports edges (also between cluster members) do NOT
        set needs_reprocessing — only contradicts does."""
        f = cluster_with_member_claims
        await f["claims_svc"].create_edge(ClaimEdgeCreate(
            source_claim_id=f["member_claim_id"],
            target_claim_id=f["external_claim_id"],
            relation="supports",
            confidence=0.8,
        ))
        flag = await _get_needs_reprocessing(f["db"], f["cluster_id"])
        assert flag == 0, "Supports edges must not flag the cluster."

    async def test_contradicts_with_direct_cluster_id_fires_flag(self, cluster_with_member_claims):
        """Atypical-but-schema-allowed: contradicts edge with cluster_id directly
        set rather than resolving via member_of."""
        f = cluster_with_member_claims
        await f["claims_svc"].create_edge(ClaimEdgeCreate(
            source_claim_id=f["external_claim_id"],
            cluster_id=f["cluster_id"],
            relation="contradicts",
            confidence=0.8,
        ))
        flag = await _get_needs_reprocessing(f["db"], f["cluster_id"])
        assert flag == 1, "Contradicts with direct cluster_id must flag the cluster."
