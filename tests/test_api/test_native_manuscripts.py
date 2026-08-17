"""REST contracts for canonical manuscripts and bulk entity resolution."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig


DEFAULT_HEADERS = {"X-RKA-Project": "proj_default"}
OTHER_HEADERS = {"X-RKA-Project": "proj_native_other"}


@pytest_asyncio.fixture
async def api_client(tmp_path: Path):
    config = RKAConfig(
        project_dir=tmp_path,
        db_path=Path("native-manuscripts-api.db"),
        llm_enabled=False,
        embeddings_enabled=False,
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/projects",
                json={"id": "proj_native_other", "name": "Other Project"},
            )
            assert response.status_code == 200
            yield client
    finally:
        await lifespan.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_legacy_registration_dual_writes_canonical_manuscript(
    api_client: httpx.AsyncClient,
) -> None:
    response = await api_client.post(
        "/api/manuscripts",
        headers=DEFAULT_HEADERS,
        json={"venue": "USENIX Security", "title": "Compatibility manuscript"},
    )
    assert response.status_code == 201
    created = response.json()
    assert created["id"].startswith("jrn_")
    assert created["canonical_id"].startswith("man_")
    assert created["deprecated_id"] is True

    canonical = await api_client.get(
        f"/api/manuscripts/{created['canonical_id']}",
        headers=DEFAULT_HEADERS,
    )
    assert canonical.status_code == 200
    assert canonical.json()["legacy_journal_id"] == created["id"]
    assert canonical.json()["project_id"] == "proj_default"

    legacy = await api_client.get(
        f"/api/manuscripts/{created['id']}",
        headers=DEFAULT_HEADERS,
    )
    assert legacy.status_code == 200
    assert legacy.json()["canonical_id"] == created["canonical_id"]


@pytest.mark.asyncio
async def test_native_spine_is_atomic_and_revision_guarded(
    api_client: httpx.AsyncClient,
) -> None:
    created = await api_client.post(
        "/api/manuscripts/native",
        headers=DEFAULT_HEADERS,
        json={
            "title": "Native manuscript",
            "venue": "IEEE S&P",
            "workspace_ref": "papers/native",
        },
    )
    assert created.status_code == 201
    manuscript = created.json()
    assert manuscript["id"].startswith("man_")
    assert manuscript["revision"] == 1

    spine = {
        "claims": [{
            "claim_id": "C1",
            "claim_type": "methodological",
            "status": "active",
            "text": "The method isolates the intended threat-model factor.",
            "allowed_wording": "The method isolates the evaluated factor.",
            "prohibited_wording": ["The method proves universal isolation."],
            "manuscript_units": ["M1"],
        }],
        "units": [{
            "unit_id": "M1",
            "kind": "method",
            "location": "sections/method.tex#design",
            "status": "planned",
        }],
    }
    updated = await api_client.put(
        f"/api/manuscripts/{manuscript['id']}/argument-spine",
        headers=DEFAULT_HEADERS,
        json={"expected_revision": 1, "spine": spine},
    )
    assert updated.status_code == 200
    assert updated.json()["manuscript"]["revision"] == 2
    assert updated.json()["claims"][0]["local_key"] == "C1"

    conflict = await api_client.put(
        f"/api/manuscripts/{manuscript['id']}/argument-spine",
        headers=DEFAULT_HEADERS,
        json={"expected_revision": 1, "spine": spine},
    )
    assert conflict.status_code == 409

    projection = await api_client.get(
        f"/api/manuscripts/{manuscript['id']}/spine",
        headers=DEFAULT_HEADERS,
    )
    assert projection.status_code == 200
    assert projection.json()["authoritative_source"] == "rka"
    assert projection.json()["manuscript_revision"] == 2

    candidates = await api_client.get(
        f"/api/manuscripts/{manuscript['id']}/writing-candidates",
        headers=DEFAULT_HEADERS,
    )
    assert candidates.status_code == 200
    assert (
        candidates.json()["schema_version"]
        == "rka.writing-evidence-candidates/v1"
    )
    assert candidates.json()["manuscript_id"] == manuscript["id"]
    assert candidates.json()["candidate_spine"]["claims"] == []


@pytest.mark.asyncio
async def test_reference_manifest_routes_are_scoped_and_revision_guarded(
    api_client: httpx.AsyncClient,
) -> None:
    created = await api_client.post(
        "/api/manuscripts/native",
        headers=DEFAULT_HEADERS,
        json={"title": "Reference manifest"},
    )
    literature = await api_client.post(
        "/api/literature",
        headers=DEFAULT_HEADERS,
        json={"title": "Scoped paper", "doi": "10.1000/scoped"},
    )
    foreign_literature = await api_client.post(
        "/api/literature",
        headers=OTHER_HEADERS,
        json={"title": "Foreign paper", "doi": "10.1000/foreign"},
    )
    assert (
        created.status_code
        == literature.status_code
        == foreign_literature.status_code
        == 201
    )
    manuscript_id = created.json()["id"]
    replaced = await api_client.put(
        f"/api/manuscripts/{manuscript_id}/references",
        headers=DEFAULT_HEADERS,
        json={
            "expected_revision": 1,
            "members": [
                {
                    "citation_key": "smith2026scoped",
                    "literature_id": literature.json()["id"],
                }
            ],
        },
    )
    assert replaced.status_code == 200
    assert replaced.json()["manuscript_revision"] == 2
    assert replaced.json()["active_citation_keys"] == ["smith2026scoped"]
    assert replaced.json()["approved_citation_keys"] == []

    fetched = await api_client.get(
        f"/api/manuscripts/{manuscript_id}/references",
        headers=DEFAULT_HEADERS,
    )
    assert fetched.status_code == 200
    assert fetched.json() == replaced.json()

    stale = await api_client.put(
        f"/api/manuscripts/{manuscript_id}/references",
        headers=DEFAULT_HEADERS,
        json={"expected_revision": 1, "members": []},
    )
    assert stale.status_code == 409

    foreign = await api_client.put(
        f"/api/manuscripts/{manuscript_id}/references",
        headers=DEFAULT_HEADERS,
        json={
            "expected_revision": 2,
            "members": [
                {
                    "citation_key": "foreign2026",
                    "literature_id": foreign_literature.json()["id"],
                }
            ],
        },
    )
    assert foreign.status_code == 422
    assert "not available in this project" in foreign.text


@pytest.mark.asyncio
async def test_metadata_routes_cannot_bypass_lifecycle_gates(
    api_client: httpx.AsyncClient,
) -> None:
    invalid_create = await api_client.post(
        "/api/manuscripts/native",
        headers=DEFAULT_HEADERS,
        json={"title": "Bypass", "phase": "submitted", "state": "accepted"},
    )
    assert invalid_create.status_code == 422

    created = await api_client.post(
        "/api/manuscripts/native",
        headers=DEFAULT_HEADERS,
        json={"title": "Lifecycle guarded"},
    )
    assert created.status_code == 201
    manuscript = created.json()
    invalid_update = await api_client.patch(
        f"/api/manuscripts/{manuscript['id']}",
        headers=DEFAULT_HEADERS,
        json={
            "expected_revision": manuscript["revision"],
            "phase": "submitted",
            "state": "accepted",
        },
    )
    assert invalid_update.status_code == 422

    unchanged = await api_client.get(
        f"/api/manuscripts/{manuscript['id']}",
        headers=DEFAULT_HEADERS,
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["phase"] == "planning"
    assert unchanged.json()["state"] == "active"


@pytest.mark.asyncio
async def test_native_mutations_record_transport_actor(
    api_client: httpx.AsyncClient,
) -> None:
    direct = await api_client.post(
        "/api/manuscripts/native",
        headers=DEFAULT_HEADERS,
        json={"title": "Direct REST actor"},
    )
    assert direct.status_code == 201
    direct_spine = await api_client.put(
        f"/api/manuscripts/{direct.json()['id']}/argument-spine",
        headers=DEFAULT_HEADERS,
        json={
            "expected_revision": 1,
            "spine": {
                "claims": [],
                "units": [{
                    "unit_id": "INTRO",
                    "kind": "introduction",
                    "location": "sections/introduction.tex",
                }],
            },
        },
    )
    assert direct_spine.status_code == 200
    assert direct_spine.json()["semantic_patch_proposal_id"].startswith("spp_")
    direct_audit = await api_client.get(
        "/api/audit",
        headers=DEFAULT_HEADERS,
        params={
            "entity_type": "manuscript",
            "entity_id": direct.json()["id"],
        },
    )
    assert direct_audit.status_code == 200
    assert {entry["actor"] for entry in direct_audit.json()} == {"web_ui"}
    assert {entry["action"] for entry in direct_audit.json()} == {
        "create",
        "update",
    }

    blocked_direct_spine = await api_client.put(
        f"/api/manuscripts/{direct.json()['id']}/argument-spine",
        headers={**DEFAULT_HEADERS, "X-RKA-Actor": "executor"},
        json={"expected_revision": 2, "spine": {"claims": [], "units": []}},
    )
    assert blocked_direct_spine.status_code == 403

    mcp_headers = {**DEFAULT_HEADERS, "X-RKA-Actor": "executor"}
    proxied = await api_client.post(
        "/api/manuscripts/native",
        headers=mcp_headers,
        json={"title": "MCP-proxied actor"},
    )
    assert proxied.status_code == 201
    proxied_audit = await api_client.get(
        "/api/audit",
        headers=DEFAULT_HEADERS,
        params={
            "entity_type": "manuscript",
            "entity_id": proxied.json()["id"],
        },
    )
    assert proxied_audit.status_code == 200
    assert {entry["actor"] for entry in proxied_audit.json()} == {"executor"}

    queued = await api_client.post(
        f"/api/manuscripts/{proxied.json()['id']}/validate-reference",
        headers=mcp_headers,
        json={"title": "Transport-attributed reference"},
    )
    assert queued.status_code == 202
    queued_audit = await api_client.get(
        "/api/audit",
        headers=DEFAULT_HEADERS,
        params={
            "entity_type": "reference_validation_job",
            "entity_id": queued.json()["job_id"],
        },
    )
    assert queued_audit.status_code == 200
    assert {entry["actor"] for entry in queued_audit.json()} == {"executor"}

    rejected = await api_client.post(
        "/api/manuscripts/native",
        headers={**DEFAULT_HEADERS, "X-RKA-Actor": "pi"},
        json={"title": "Spoofed identity"},
    )
    assert rejected.status_code == 422


@pytest.mark.asyncio
async def test_native_manuscript_routes_return_uniform_not_found(
    api_client: httpx.AsyncClient,
) -> None:
    """A missing same-project aggregate is 404 on every manuscript route."""
    manuscript_id = "man_missing"
    attestation = {
        "claim_id": "mcl_missing",
        "claim_version": 1,
        "overall_verdict": "block",
        "grounding_verdict": "block",
        "evidence_verdict": "not_checked",
        "contradiction_verdict": "not_checked",
        "currency_verdict": "not_checked",
        "ratification_verdict": "not_checked",
        "unit_coverage_verdict": "not_checked",
        "full_json_payload": {"findings": ["missing manuscript"]},
        "started_at": "2026-07-23T12:00:00Z",
        "completed_at": "2026-07-23T12:00:01Z",
    }
    requests = [
        ("GET", f"/api/manuscripts/{manuscript_id}", None),
        ("GET", f"/api/manuscripts/{manuscript_id}/context", None),
        ("GET", f"/api/manuscripts/{manuscript_id}/readiness", None),
        ("GET", f"/api/manuscripts/{manuscript_id}/spine", None),
        ("GET", f"/api/manuscripts/{manuscript_id}/references", None),
        (
            "GET",
            f"/api/manuscripts/{manuscript_id}/writing-candidates",
            None,
        ),
        ("GET", f"/api/manuscripts/{manuscript_id}/impact", None),
        (
            "PATCH",
            f"/api/manuscripts/{manuscript_id}",
            {"expected_revision": 1, "title": "Missing"},
        ),
        (
            "PUT",
            f"/api/manuscripts/{manuscript_id}/argument-spine",
            {
                "expected_revision": 1,
                "spine": {"claims": [], "units": []},
            },
        ),
        (
            "PUT",
            f"/api/manuscripts/{manuscript_id}/references",
            {"expected_revision": 1, "members": []},
        ),
        (
            "POST",
            f"/api/manuscripts/{manuscript_id}/claims/C1/ratifications",
            {"expected_revision": 1, "decision_id": "dec_missing"},
        ),
        (
            "POST",
            f"/api/manuscripts/{manuscript_id}/transition",
            {"expected_revision": 1, "target_phase": "drafting"},
        ),
        (
            "POST",
            f"/api/manuscripts/{manuscript_id}/checkpoints",
            {"expected_revision": 1, "kind": "venue"},
        ),
        (
            "POST",
            "/api/manuscripts/checkpoints/mcp_missing/resolve",
            {
                "expected_revision": 1,
                "decision_id": "dec_missing",
                "status": "resolved",
                "resolved_at": "2026-07-23T12:00:01Z",
            },
        ),
        (
            "POST",
            f"/api/manuscripts/{manuscript_id}/verification-attestations",
            {"expected_revision": 1, "attestation": attestation},
        ),
        (
            "POST",
            f"/api/manuscripts/{manuscript_id}/validate-reference",
            {"title": "Missing manuscript reference"},
        ),
    ]

    for method, path, payload in requests:
        response = await api_client.request(
            method,
            path,
            headers=DEFAULT_HEADERS,
            json=payload,
        )
        assert response.status_code == 404, (
            f"{method} {path} returned {response.status_code}: {response.text}"
        )


@pytest.mark.asyncio
async def test_native_domain_validation_remains_unprocessable(
    api_client: httpx.AsyncClient,
) -> None:
    created = await api_client.post(
        "/api/manuscripts/native",
        headers=DEFAULT_HEADERS,
        json={"title": "Domain validation"},
    )
    assert created.status_code == 201

    response = await api_client.post(
        f"/api/manuscripts/{created.json()['id']}/transition",
        headers=DEFAULT_HEADERS,
        json={"expected_revision": 1, "target_phase": "planning"},
    )
    assert response.status_code == 422
    assert "must advance" in response.text


@pytest.mark.asyncio
async def test_foreign_manuscript_is_hidden_as_not_found(
    api_client: httpx.AsyncClient,
) -> None:
    foreign = await api_client.post(
        "/api/manuscripts/native",
        headers=OTHER_HEADERS,
        json={"title": "Foreign manuscript"},
    )
    assert foreign.status_code == 201
    manuscript_id = foreign.json()["id"]

    requests = [
        ("GET", f"/api/manuscripts/{manuscript_id}/readiness", None),
        ("GET", f"/api/manuscripts/{manuscript_id}/impact", None),
        (
            "PATCH",
            f"/api/manuscripts/{manuscript_id}",
            {"expected_revision": 1, "title": "Hidden"},
        ),
    ]
    for method, path, payload in requests:
        response = await api_client.request(
            method,
            path,
            headers=DEFAULT_HEADERS,
            json=payload,
        )
        assert response.status_code == 404, (
            f"{method} {path} returned {response.status_code}: {response.text}"
        )


@pytest.mark.asyncio
async def test_bulk_resolver_attests_scope_and_withholds_foreign_content(
    api_client: httpx.AsyncClient,
) -> None:
    default_note = await api_client.post(
        "/api/notes",
        headers=DEFAULT_HEADERS,
        json={"content": "default secret", "source": "executor"},
    )
    foreign_note = await api_client.post(
        "/api/notes",
        headers=OTHER_HEADERS,
        json={"content": "foreign secret", "source": "executor"},
    )
    assert default_note.status_code == foreign_note.status_code == 201

    response = await api_client.post(
        "/api/entities/resolve",
        headers=DEFAULT_HEADERS,
        json={
            "ids": [
                foreign_note.json()["id"],
                default_note.json()["id"],
                "bogus_id",
                default_note.json()["id"],
            ],
            "include_edges": True,
        },
    )
    assert response.status_code == 200
    packet = response.json()
    assert packet["schema_version"] == "rka-entity-resolution/v1"
    assert packet["project_id"] == "proj_default"
    assert packet["requested_ids"] == sorted(set(packet["requested_ids"]))

    resolved = packet["entities"][default_note.json()["id"]]
    assert resolved["outcome"] == "resolved"
    assert resolved["record"]["content"] == "default secret"

    foreign = packet["entities"][foreign_note.json()["id"]]
    assert foreign["outcome"] == "wrong_project"
    assert foreign["record"] is None
    assert "foreign secret" not in str(foreign)
    assert packet["entities"]["bogus_id"]["outcome"] == "unknown_type"


@pytest.mark.asyncio
async def test_outline_rest_projection_and_proposal_are_separate_from_apply(
    api_client: httpx.AsyncClient,
) -> None:
    created = await api_client.post(
        "/api/manuscripts/native",
        headers=DEFAULT_HEADERS,
        json={"title": "Outline REST manuscript"},
    )
    manuscript_id = created.json()["id"]
    spine = await api_client.put(
        f"/api/manuscripts/{manuscript_id}/argument-spine",
        headers=DEFAULT_HEADERS,
        json={
            "expected_revision": 1,
            "spine": {
                "claims": [],
                "units": [{
                    "unit_id": "INTRO",
                    "kind": "introduction",
                    "location": "sections/introduction.tex",
                    "title": "Introduction",
                }],
            },
        },
    )
    assert spine.status_code == 200

    outline = await api_client.get(
        f"/api/manuscripts/{manuscript_id}/outline",
        headers=DEFAULT_HEADERS,
    )
    assert outline.status_code == 200
    assert outline.json()["units"][0]["missing"] == [
        "communicative_job",
        "intended_takeaway",
        "intended_claim",
        "evidence_plan",
    ]

    proposal = await api_client.post(
        f"/api/manuscripts/{manuscript_id}/outline/proposals",
        headers=DEFAULT_HEADERS,
        json={
            "expected_revision": 2,
            "action": "edit",
            "reason": "Record the introduction rationale.",
            "unit_key": "INTRO",
            "patch": {
                "communicative_job": "Establish the scoped problem.",
                "intended_takeaway": "The problem is concrete.",
                "evidence_plan": ["Connect a reviewed claim before checkpointing."],
            },
        },
    )
    assert proposal.status_code == 201
    assert proposal.json()["proposal"]["status"] == "proposed"
    unchanged = await api_client.get(
        f"/api/manuscripts/{manuscript_id}/outline",
        headers=DEFAULT_HEADERS,
    )
    assert unchanged.json()["units"][0]["communicative_job"] is None
