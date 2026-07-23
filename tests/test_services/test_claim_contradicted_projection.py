"""Claim reads derive contradiction state from same-project claim edges."""

from __future__ import annotations

import pytest

from rka.models.claim import Claim, ClaimCreate, ClaimEdgeCreate, EvidenceClusterCreate
from rka.services.claims import ClaimService
from rka.services.clusters import ClusterService


PROJECT_ID = "proj_default"


def test_contradicted_is_a_required_server_projection() -> None:
    assert Claim.model_fields["contradicted"].is_required()


async def _seed_source(db, entry_id: str) -> None:
    await db.execute(
        """INSERT INTO journal
           (id, project_id, type, content, source, confidence)
           VALUES (?, ?, 'note', 'Measured evidence.', 'executor', 'tested')""",
        [entry_id, PROJECT_ID],
    )
    await db.commit()


@pytest.mark.asyncio
async def test_get_and_lists_project_both_contradiction_endpoints(db) -> None:
    await _seed_source(db, "jrn_contradiction_projection")
    service = ClaimService(db, project_id=PROJECT_ID)
    source = await service.create(
        ClaimCreate(
            source_entry_id="jrn_contradiction_projection",
            claim_type="result",
            content="The primary result.",
        )
    )
    target = await service.create(
        ClaimCreate(
            source_entry_id="jrn_contradiction_projection",
            claim_type="observation",
            content="The conflicting observation.",
        )
    )
    unrelated = await service.create(
        ClaimCreate(
            source_entry_id="jrn_contradiction_projection",
            claim_type="observation",
            content="An unrelated observation.",
        )
    )

    assert source.contradicted is False
    assert target.contradicted is False
    assert unrelated.contradicted is False

    await service.create_edge(
        ClaimEdgeCreate(
            source_claim_id=source.id,
            target_claim_id=target.id,
            relation="contradicts",
        )
    )
    # A malformed edge owned by another project must not affect this project's
    # response, even if it names an otherwise in-project claim.
    await db.execute(
        """INSERT INTO claim_edges
           (id, source_claim_id, target_claim_id, relation, project_id)
           VALUES ('cle_foreign_contradiction', ?, ?, 'contradicts', 'proj_other')""",
        [unrelated.id, source.id],
    )
    await db.commit()

    assert (await service.get(source.id)).contradicted is True
    assert (await service.get(target.id)).contradicted is True
    assert (await service.get(unrelated.id)).contradicted is False

    listed = {claim.id: claim.contradicted for claim in await service.list()}
    assert listed == {
        source.id: True,
        target.id: True,
        unrelated.id: False,
    }

    cluster = await ClusterService(db, project_id=PROJECT_ID).create(
        EvidenceClusterCreate(label="Contradiction projection")
    )
    await service.create_edge(
        ClaimEdgeCreate(
            source_claim_id=target.id,
            cluster_id=cluster.id,
            relation="member_of",
        )
    )
    cluster_claims = await service.list(cluster_id=cluster.id)
    assert [(claim.id, claim.contradicted) for claim in cluster_claims] == [
        (target.id, True)
    ]
