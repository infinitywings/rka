"""Cluster claims must carry `scope_readiness`.

`scope_readiness` is derived, not stored: it comes from joining a claim's
current scope contract and assessing it. `get_claims_for_cluster` hand-built
its result dicts and omitted the field, while the research-map UI rendered it
as a required string — so opening any cluster threw
`Cannot read properties of undefined (reading 'replaceAll')` and blanked the
page. Every claim in every cluster, since the field was introduced.

The type said the field was there, which is why nothing caught it: the
frontend contract and the endpoint disagreed and neither side could see the
other.
"""

from __future__ import annotations

import pytest

from rka.services.claims import ClaimService
from rka.services.research_map import ResearchMapService

PROJECT = "proj_default"


async def _seed_cluster_with_claim(db) -> tuple[str, str]:
    await db.execute(
        "INSERT INTO journal (id, project_id, content, type, source) "
        "VALUES ('jrn_scope_probe', ?, 'source entry', 'finding', 'executor')",
        [PROJECT],
    )
    await db.execute(
        "INSERT INTO evidence_clusters (id, project_id, label) "
        "VALUES ('ecl_scope_probe', ?, 'probe cluster')",
        [PROJECT],
    )
    await db.execute(
        "INSERT INTO claims (id, project_id, source_entry_id, claim_type, content, confidence) "
        "VALUES ('clm_scope_probe', ?, 'jrn_scope_probe', 'evidence', 'a claim', 0.7)",
        [PROJECT],
    )
    await db.execute(
        "INSERT INTO claim_edges (id, project_id, source_claim_id, cluster_id, relation) "
        "VALUES ('cle_scope_probe', ?, 'clm_scope_probe', 'ecl_scope_probe', 'member_of')",
        [PROJECT],
    )
    await db.commit()
    return "ecl_scope_probe", "clm_scope_probe"


@pytest.mark.asyncio
async def test_cluster_claims_include_scope_readiness(db):
    cluster_id, _ = await _seed_cluster_with_claim(db)
    svc = ResearchMapService(db, project_id=PROJECT)

    claims = await svc.get_claims_for_cluster(cluster_id)

    assert claims, "seeded claim should be returned"
    for claim in claims:
        assert "scope_readiness" in claim, (
            "the research-map UI renders this as a required string; omitting it "
            "throws on undefined and blanks the page"
        )
        assert isinstance(claim["scope_readiness"], str)
        assert claim["scope_readiness"]


@pytest.mark.asyncio
async def test_a_claim_with_no_scope_contract_reads_missing(db):
    """Not an error state — most claims have no contract yet."""
    cluster_id, _ = await _seed_cluster_with_claim(db)
    svc = ResearchMapService(db, project_id=PROJECT)

    (claim,) = await svc.get_claims_for_cluster(cluster_id)

    assert claim["scope_readiness"] == "missing"


@pytest.mark.asyncio
async def test_readiness_agrees_with_the_claims_service(db):
    """One definition of readiness, not two.

    A second implementation here would drift the moment the assessment rules
    change, and the drift would be invisible — both sides would return a
    plausible string.
    """
    cluster_id, claim_id = await _seed_cluster_with_claim(db)

    from_map = (await ResearchMapService(db, project_id=PROJECT).get_claims_for_cluster(cluster_id))[0]
    from_claims = await ClaimService(db, project_id=PROJECT).get(claim_id)

    assert from_map["scope_readiness"] == from_claims.scope_readiness


@pytest.mark.asyncio
async def test_cluster_detail_carries_it_too(db):
    """The detail endpoint reuses the same projection."""
    cluster_id, _ = await _seed_cluster_with_claim(db)
    detail = await ResearchMapService(db, project_id=PROJECT).get_cluster_detail(cluster_id)

    assert detail is not None
    assert all("scope_readiness" in c for c in detail["claims"])
