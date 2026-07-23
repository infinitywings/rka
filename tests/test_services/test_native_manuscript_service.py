"""Native manuscript aggregate, spine, and readiness tests."""

from __future__ import annotations

import pytest

from rka.infra.ids import generate_id
from rka.models.manuscript_native import (
    ManuscriptCheckpointCreate,
    ManuscriptCheckpointResolve,
    ManuscriptCreate,
    ManuscriptReferenceManifestReplace,
    ManuscriptUpdate,
)
from rka.services.manuscript_native import (
    ManuscriptRevisionConflict,
    NativeManuscriptService,
)


async def _seed_ready_claim(db, *, project_id: str = "proj_default") -> str:
    journal_id = generate_id("journal")
    claim_id = generate_id("claim")
    await db.execute(
        """INSERT INTO journal
           (id, type, content, source, confidence, importance, status, project_id)
           VALUES (?, 'log', 'Measured 14 percent lower latency.',
                   'executor', 'tested', 'high', 'active', ?)""",
        [journal_id, project_id],
    )
    await db.execute(
        """INSERT INTO claims
           (id, source_entry_id, claim_type, content, confidence, verified,
            evidence_status, stale, project_id)
           VALUES (?, ?, 'result', 'Latency was 14 percent lower.',
                   0.9, 1, 'supported', 0, ?)""",
        [claim_id, journal_id, project_id],
    )
    await db.commit()
    return claim_id


async def _seed_pi_decision(
    db,
    *,
    chosen: str,
    project_id: str = "proj_default",
) -> str:
    decision_id = generate_id("decision")
    await db.execute(
        """INSERT INTO decisions
           (id, phase, question, chosen, rationale, decided_by, status, project_id)
           VALUES (?, 'paper_writing', 'Ratify wording?', ?, 'PI selected it.',
                   'pi', 'active', ?)""",
        [decision_id, chosen, project_id],
    )
    await db.commit()
    return decision_id


async def _seed_literature(
    db,
    *,
    title: str = "A cited study",
    doi: str | None = "10.1000/example",
    project_id: str = "proj_default",
) -> str:
    literature_id = generate_id("literature")
    await db.execute(
        """INSERT INTO literature
           (id, title, authors, year, doi, status, added_by, project_id)
           VALUES (?, ?, '["A. Author"]', 2025, ?, 'cited', 'pi', ?)""",
        [literature_id, title, doi, project_id],
    )
    await db.commit()
    return literature_id


async def _seed_reference_validation(
    db,
    *,
    manuscript_id: str,
    literature_id: str,
    status: str = "VERIFIED",
    input_doi: str | None = "10.1000/example",
    input_title: str | None = "A cited study",
    completed_at: str = "2026-07-22T11:00:01Z",
    project_id: str = "proj_default",
) -> str:
    validation_id = generate_id("reference_validation")
    await db.execute(
        """INSERT INTO reference_validation_attestations
           (id, project_id, manuscript_id, canonical_manuscript_id,
            literature_id, input_doi, input_title, input_authors, status,
            retraction_check_enabled, retraction_checked, sources_tried,
            sources_confirmed, notes, stage_trace, full_json_payload,
            pipeline_version, started_at, completed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, '["A. Author"]', ?, 1, 1,
                   '["crossref"]', '["crossref"]', '[]', '{}', '{}',
                   'test/v1', '2026-07-22T11:00:00Z', ?)""",
        [
            validation_id,
            project_id,
            manuscript_id,
            manuscript_id,
            literature_id,
            input_doi,
            input_title,
            status,
            completed_at,
        ],
    )
    await db.commit()
    return validation_id


def _spine(claim_id: str, *, wording: str = "The system reduced latency.") -> dict:
    return {
        "claims": [
            {
                "claim_id": "C1",
                "claim_type": "empirical",
                "status": "active",
                "text": wording,
                "allowed_wording": wording,
                "prohibited_wording": ["The system always eliminates latency."],
                "evidence_ids": [claim_id],
                "qualifier_ids": [],
                "counterevidence_ids": [],
                "unit_links": [{"unit_key": "R1", "relationship": "tests"}],
            }
        ],
        "units": [
            {
                "unit_id": "R1",
                "kind": "result",
                "location": "sections/results.tex#latency",
                "artifact_ref": "artifacts/latency.csv",
                "allowed_interpretation": "Latency was lower in the tested setting.",
                "prohibited_interpretation": "Latency is lower in every setting.",
                "evidence_ids": [claim_id],
            }
        ],
    }


@pytest.mark.asyncio
async def test_create_update_and_legacy_alias(db_with_project) -> None:
    legacy_id = generate_id("journal")
    await db_with_project.execute(
        """INSERT INTO journal
           (id, type, content, source, confidence, importance, status, project_id)
           VALUES (?, 'note', 'Legacy manuscript', 'executor',
                   'hypothesis', 'normal', 'active', 'proj_default')""",
        [legacy_id],
    )
    await db_with_project.execute(
        """INSERT INTO tags (tag, entity_type, entity_id, project_id)
           VALUES ('manuscript', 'journal', ?, 'proj_default')""",
        [legacy_id],
    )
    await db_with_project.commit()

    service = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await service.create(
        ManuscriptCreate(
            title="Native paper",
            venue="USENIX Security",
            legacy_journal_id=legacy_id,
        )
    )
    assert manuscript.id.startswith("man_")
    assert await service.get(legacy_id) == manuscript

    updated = await service.update(
        manuscript.id,
        ManuscriptUpdate(
            expected_revision=1,
            abstract="A bounded abstract.",
        ),
    )
    assert updated.revision == 2
    assert updated.abstract == "A bounded abstract."

    with pytest.raises(ManuscriptRevisionConflict):
        await service.update(
            manuscript.id,
            ManuscriptUpdate(expected_revision=1, venue="CHI"),
        )
    with pytest.raises(ValueError, match="lifecycle fields"):
        await service.update(
            manuscript.id,
            ManuscriptUpdate(expected_revision=2, phase="submitted"),
        )


@pytest.mark.asyncio
async def test_spine_upsert_is_atomic_and_versions_wording(db_with_project) -> None:
    evidence_id = await _seed_ready_claim(db_with_project)
    service = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await service.create(
        ManuscriptCreate(title="Atomic spine", venue="IEEE S&P")
    )

    invalid = _spine(evidence_id)
    invalid["claims"][0]["unit_links"][0]["unit_key"] = "missing"
    with pytest.raises(ValueError, match="unknown unit"):
        await service.upsert_argument_spine(
            manuscript.id,
            expected_revision=1,
            spine=invalid,
        )
    after_failure = await service.get_context(manuscript.id)
    assert after_failure["manuscript"]["revision"] == 1
    assert after_failure["claims"] == []
    assert after_failure["units"] == []

    first = await service.upsert_argument_spine(
        manuscript.id,
        expected_revision=1,
        spine=_spine(evidence_id),
    )
    assert first["manuscript"]["revision"] == 2
    assert first["claims"][0]["version"] == 1

    same = await service.upsert_argument_spine(
        manuscript.id,
        expected_revision=2,
        spine=_spine(evidence_id),
    )
    assert same["manuscript"]["revision"] == 3
    assert same["claims"][0]["version"] == 1

    changed = await service.upsert_argument_spine(
        manuscript.id,
        expected_revision=3,
        spine=_spine(evidence_id, wording="Latency was lower in our testbed."),
    )
    assert changed["manuscript"]["revision"] == 4
    assert changed["claims"][0]["version"] == 2


@pytest.mark.asyncio
async def test_reference_manifest_replacement_is_atomic_and_historical(
    db_with_project,
) -> None:
    service = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await service.create(
        ManuscriptCreate(title="Reference replacement")
    )
    first_literature = await _seed_literature(
        db_with_project,
        title="First study",
        doi="10.1000/first",
    )
    second_literature = await _seed_literature(
        db_with_project,
        title="Second study",
        doi="10.1000/second",
    )

    with pytest.raises(ValueError, match="not available in this project"):
        await service.replace_reference_manifest(
            manuscript.id,
            ManuscriptReferenceManifestReplace(
                expected_revision=1,
                members=[
                    {
                        "citation_key": "missing2026",
                        "literature_id": "lit_missing",
                    }
                ],
            ),
        )
    unchanged = await service.get_reference_manifest(manuscript.id)
    assert unchanged["manuscript_revision"] == 1
    assert unchanged["members"] == []

    installed = await service.replace_reference_manifest(
        manuscript.id,
        ManuscriptReferenceManifestReplace(
            expected_revision=1,
            members=[
                {
                    "citation_key": "first2026",
                    "literature_id": first_literature,
                },
                {
                    "citation_key": "second2026",
                    "literature_id": second_literature,
                },
            ],
        ),
    )
    assert installed["manuscript_revision"] == 2
    assert installed["active_citation_keys"] == ["first2026", "second2026"]

    no_op = await service.replace_reference_manifest(
        manuscript.id,
        ManuscriptReferenceManifestReplace(
            expected_revision=2,
            members=[
                {
                    "citation_key": "second2026",
                    "literature_id": second_literature,
                },
                {
                    "citation_key": "first2026",
                    "literature_id": first_literature,
                },
            ],
        ),
    )
    assert no_op["manuscript_revision"] == 2

    replaced = await service.replace_reference_manifest(
        manuscript.id,
        ManuscriptReferenceManifestReplace(
            expected_revision=2,
            members=[
                {
                    "citation_key": "second-study2026",
                    "literature_id": second_literature,
                }
            ],
        ),
    )
    assert replaced["manuscript_revision"] == 3
    assert replaced["active_citation_keys"] == ["second-study2026"]
    rows = await db_with_project.fetchall(
        """SELECT citation_key, state
           FROM manuscript_reference_members
           WHERE manuscript_id = ?
           ORDER BY citation_key""",
        [manuscript.id],
    )
    assert rows == [
        {"citation_key": "first2026", "state": "retired"},
        {"citation_key": "second-study2026", "state": "active"},
        {"citation_key": "second2026", "state": "retired"},
    ]


@pytest.mark.asyncio
async def test_reference_readiness_uses_latest_exact_bound_validation(
    db_with_project,
) -> None:
    service = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await service.create(
        ManuscriptCreate(title="Reference readiness")
    )
    literature_id = await _seed_literature(db_with_project)

    absent = await service.get_readiness(manuscript.id, target_phase="review")
    assert "REFERENCE_MANIFEST_REQUIRED" in {
        finding["code"] for finding in absent["findings"]
    }

    await service.replace_reference_manifest(
        manuscript.id,
        ManuscriptReferenceManifestReplace(
            expected_revision=1,
            members=[
                {
                    "citation_key": "author2025study",
                    "literature_id": literature_id,
                }
            ],
        ),
    )
    missing = await service.get_readiness(manuscript.id, target_phase="review")
    assert "REFERENCE_VALIDATION_MISSING" in {
        finding["code"] for finding in missing["findings"]
    }

    verified_id = await _seed_reference_validation(
        db_with_project,
        manuscript_id=manuscript.id,
        literature_id=literature_id,
        completed_at="2099-01-01T11:00:01Z",
    )
    verified = await service.get_reference_manifest(manuscript.id)
    assert verified["approved_citation_keys"] == ["author2025study"]
    assert verified["members"][0]["validation"]["id"] == verified_id
    assert verified["members"][0]["validation"]["identity_matches"] is True

    failed_id = await _seed_reference_validation(
        db_with_project,
        manuscript_id=manuscript.id,
        literature_id=literature_id,
        status="UNVERIFIED",
        completed_at="2099-01-01T12:00:01Z",
    )
    failed = await service.get_reference_manifest(manuscript.id)
    assert failed["approved_citation_keys"] == []
    assert failed["members"][0]["validation"]["id"] == failed_id
    failed_readiness = await service.get_readiness(
        manuscript.id,
        target_phase="review",
    )
    assert "REFERENCE_NOT_VERIFIED" in {
        finding["code"] for finding in failed_readiness["findings"]
    }

    mismatched_id = await _seed_reference_validation(
        db_with_project,
        manuscript_id=manuscript.id,
        literature_id=literature_id,
        input_doi="10.1000/different-paper",
        completed_at="2099-01-01T13:00:01Z",
    )
    mismatched = await service.get_reference_manifest(manuscript.id)
    assert mismatched["approved_citation_keys"] == []
    assert mismatched["members"][0]["validation"]["id"] == mismatched_id
    assert (
        mismatched["members"][0]["validation"]["identity_matches"] is False
    )
    mismatch_readiness = await service.get_readiness(
        manuscript.id,
        target_phase="review",
    )
    assert "REFERENCE_IDENTITY_MISMATCH" in {
        finding["code"] for finding in mismatch_readiness["findings"]
    }


@pytest.mark.asyncio
async def test_ratification_and_checkpoint_readiness(db_with_project) -> None:
    evidence_id = await _seed_ready_claim(db_with_project)
    service = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await service.create(
        ManuscriptCreate(title="Ready paper", venue="USENIX Security")
    )
    context = await service.upsert_argument_spine(
        manuscript.id,
        expected_revision=1,
        spine=_spine(evidence_id),
    )
    claim = context["claims"][0]
    decision_id = await _seed_pi_decision(
        db_with_project,
        chosen=claim["exact_wording"],
    )
    ratification = await service.ratify_claim(
        manuscript.id,
        local_key="C1",
        decision_id=decision_id,
        expected_revision=2,
    )
    assert ratification.claim_version == 1

    before_checkpoints = await service.get_readiness(
        manuscript.id, target_phase="drafting"
    )
    assert before_checkpoints["verdict"] == "BLOCK"
    assert {
        finding["code"] for finding in before_checkpoints["findings"]
    } == {"CHECKPOINT_REQUIRED"}

    revision = 3
    for kind in ("venue", "outline"):
        checkpoint = await service.create_checkpoint(
            ManuscriptCheckpointCreate(
                manuscript_id=manuscript.id,
                kind=kind,
            ),
            expected_revision=revision,
        )
        revision += 1
        checkpoint_decision = await _seed_pi_decision(
            db_with_project,
            chosen=f"Accept {kind}",
        )
        await service.resolve_checkpoint(
            checkpoint.id,
            ManuscriptCheckpointResolve(
                decision_id=checkpoint_decision,
                status="resolved",
                resolved_at="2026-07-22T12:00:00Z",
            ),
            expected_revision=revision,
        )
        revision += 1

    readiness = await service.get_readiness(
        manuscript.id, target_phase="drafting"
    )
    assert readiness["verdict"] == "PASS"
    assert readiness["ready"] is True
    assert readiness["findings"] == []

    transitioned = await service.transition_phase(
        manuscript.id,
        expected_revision=revision,
        target_phase="drafting",
    )
    assert transitioned.phase == "drafting"
    assert transitioned.revision == revision + 1


@pytest.mark.asyncio
async def test_projection_omits_superseded_ratification(db_with_project) -> None:
    evidence_id = await _seed_ready_claim(db_with_project)
    service = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await service.create(
        ManuscriptCreate(title="Ratification currency", venue="USENIX Security")
    )
    context = await service.upsert_argument_spine(
        manuscript.id,
        expected_revision=1,
        spine=_spine(evidence_id),
    )
    decision_id = await _seed_pi_decision(
        db_with_project,
        chosen=context["claims"][0]["exact_wording"],
    )
    await service.ratify_claim(
        manuscript.id,
        local_key="C1",
        decision_id=decision_id,
        expected_revision=2,
    )

    current = await service.export_spine_projection(manuscript.id)
    assert current["claims"][0]["ratified_by"] == decision_id

    successor_id = await _seed_pi_decision(
        db_with_project,
        chosen="Reconsider the manuscript claim wording.",
    )
    await db_with_project.execute(
        """UPDATE decisions
           SET superseded_by = ?, status = 'superseded'
           WHERE id = ? AND project_id = 'proj_default'""",
        [successor_id, decision_id],
    )
    await db_with_project.commit()

    stale = await service.export_spine_projection(manuscript.id)
    assert stale["claims"][0]["ratified_by"] is None
    readiness = await service.get_readiness(manuscript.id)
    assert any(
        finding["code"] == "CLAIM_NOT_RATIFIED"
        for finding in readiness["findings"]
    )


@pytest.mark.asyncio
async def test_ratification_rejects_nonmatching_decision(db_with_project) -> None:
    evidence_id = await _seed_ready_claim(db_with_project)
    service = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await service.create(ManuscriptCreate(title="Mismatch"))
    await service.upsert_argument_spine(
        manuscript.id,
        expected_revision=1,
        spine=_spine(evidence_id),
    )
    wrong_decision = await _seed_pi_decision(
        db_with_project,
        chosen="Different wording.",
    )
    with pytest.raises(Exception, match="claim ratification requires"):
        await service.ratify_claim(
            manuscript.id,
            local_key="C1",
            decision_id=wrong_decision,
            expected_revision=2,
        )
    current = await service.get(manuscript.id)
    assert current is not None
    assert current.revision == 2


@pytest.mark.asyncio
async def test_explicit_counterevidence_blocks_claim_and_result_unit(
    db_with_project,
) -> None:
    support_id = await _seed_ready_claim(db_with_project)
    counterevidence_id = await _seed_ready_claim(db_with_project)
    spine = _spine(support_id)
    spine["claims"][0]["counterevidence_ids"] = [counterevidence_id]
    spine["units"][0]["counterevidence_ids"] = [counterevidence_id]

    service = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await service.create(
        ManuscriptCreate(title="Counterevidence", venue="USENIX Security")
    )
    await service.upsert_argument_spine(
        manuscript.id,
        expected_revision=1,
        spine=spine,
    )

    readiness = await service.get_readiness(
        manuscript.id,
        target_phase="planning",
    )
    codes = {finding["code"] for finding in readiness["findings"]}
    assert "COUNTEREVIDENCE_REQUIRES_DISPOSITION" in codes
    assert "RESULT_COUNTEREVIDENCE_REQUIRES_DISPOSITION" in codes


@pytest.mark.asyncio
async def test_canonical_legacy_alias_remains_manuscript_evidence_after_tag_removal(
    db_with_project,
) -> None:
    legacy_id = generate_id("journal")
    evidence_id = generate_id("claim")
    await db_with_project.execute(
        """INSERT INTO journal
           (id, type, content, source, confidence, importance, status, project_id)
           VALUES (?, 'note', 'Draft manuscript prose.', 'executor',
                   'tested', 'high', 'active', 'proj_default')""",
        [legacy_id],
    )
    await db_with_project.execute(
        """INSERT INTO tags (tag, entity_type, entity_id, project_id)
           VALUES ('manuscript', 'journal', ?, 'proj_default')""",
        [legacy_id],
    )
    await db_with_project.execute(
        """INSERT INTO claims
           (id, source_entry_id, claim_type, content, confidence, verified,
            evidence_status, stale, project_id)
           VALUES (?, ?, 'result', 'A sentence copied from the draft.',
                   0.9, 1, 'supported', 0, 'proj_default')""",
        [evidence_id, legacy_id],
    )
    await db_with_project.commit()

    service = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await service.create(
        ManuscriptCreate(
            title="Canonical source",
            venue="USENIX Security",
            legacy_journal_id=legacy_id,
        )
    )
    await db_with_project.execute(
        """DELETE FROM tags
           WHERE entity_type = 'journal' AND entity_id = ?
             AND project_id = 'proj_default'""",
        [legacy_id],
    )
    await db_with_project.commit()

    context = await service.upsert_argument_spine(
        manuscript.id,
        expected_revision=1,
        spine=_spine(evidence_id),
    )
    assert context["claims"][0]["evidence"][0]["source_is_manuscript"] == 1
    readiness = await service.get_readiness(
        manuscript.id,
        target_phase="planning",
    )
    assert any(
        finding["code"] == "EVIDENCE_NOT_MANUSCRIPT_READY"
        for finding in readiness["findings"]
    )


@pytest.mark.asyncio
async def test_checkpoint_resolution_requires_paper_writing_decision_and_snapshot(
    db_with_project,
) -> None:
    service = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await service.create(
        ManuscriptCreate(title="Checkpoint snapshots", venue="IEEE S&P")
    )
    checkpoint = await service.create_checkpoint(
        ManuscriptCheckpointCreate(
            manuscript_id=manuscript.id,
            kind="venue",
        ),
        expected_revision=1,
    )
    wrong_phase = generate_id("decision")
    await db_with_project.execute(
        """INSERT INTO decisions
           (id, phase, question, chosen, rationale, decided_by, status, project_id)
           VALUES (?, 'design', 'Approve venue?', 'IEEE S&P', 'PI choice.',
                   'pi', 'active', 'proj_default')""",
        [wrong_phase],
    )
    await db_with_project.commit()
    with pytest.raises(ValueError, match="paper_writing PI decision"):
        await service.resolve_checkpoint(
            checkpoint.id,
            ManuscriptCheckpointResolve(
                decision_id=wrong_phase,
                status="resolved",
                resolved_at="2026-07-22T12:00:00Z",
            ),
            expected_revision=2,
        )

    decision_id = await _seed_pi_decision(
        db_with_project,
        chosen="IEEE S&P",
    )
    resolved = await service.resolve_checkpoint(
        checkpoint.id,
        ManuscriptCheckpointResolve(
            decision_id=decision_id,
            status="resolved",
            resolved_at="2026-07-22T12:01:00Z",
        ),
        expected_revision=2,
    )
    assert resolved.dependency_snapshot["kind"] == "venue"
    assert len(resolved.dependency_snapshot["sha256"]) == 64

    await db_with_project.execute(
        """UPDATE decisions SET chosen = 'USENIX Security'
           WHERE id = ? AND project_id = 'proj_default'""",
        [decision_id],
    )
    await db_with_project.commit()
    readiness = await service.get_readiness(
        manuscript.id,
        target_phase="drafting",
    )
    assert any(
        finding["code"] == "CHECKPOINT_REQUIRED"
        for finding in readiness["findings"]
    )


@pytest.mark.asyncio
async def test_title_change_invalidates_resolved_final_layout(
    db_with_project,
) -> None:
    service = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await service.create(ManuscriptCreate(title="Original title"))
    checkpoint = await service.create_checkpoint(
        ManuscriptCheckpointCreate(
            manuscript_id=manuscript.id,
            kind="final_layout",
        ),
        expected_revision=1,
    )
    decision_id = await _seed_pi_decision(
        db_with_project,
        chosen="Approve final layout",
    )
    await service.resolve_checkpoint(
        checkpoint.id,
        ManuscriptCheckpointResolve(
            decision_id=decision_id,
            status="resolved",
            resolved_at="2026-07-22T12:01:00Z",
        ),
        expected_revision=2,
    )

    await service.update(
        manuscript.id,
        ManuscriptUpdate(expected_revision=3, title="Revised title"),
    )
    context = await service.get_context(manuscript.id)
    assert context["checkpoints"][0]["status"] == "superseded"


@pytest.mark.asyncio
async def test_writing_candidates_smooth_claims_through_reviewed_cluster_and_rq(
    db_with_project,
) -> None:
    service = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await service.create(
        ManuscriptCreate(title="Smoothed candidates")
    )
    rq_id = generate_id("decision")
    cluster_id = generate_id("cluster")
    journal_id = generate_id("journal")
    claim_ids = [generate_id("claim"), generate_id("claim")]
    await db_with_project.execute(
        """INSERT INTO decisions
           (id, phase, question, chosen, rationale, decided_by, status, kind,
            project_id)
           VALUES (?, 'design', 'Does the control reduce exploitability?',
                   'Evaluate bounded exploitability.', 'PI research question.',
                   'pi', 'active', 'research_question', 'proj_default')""",
        [rq_id],
    )
    await db_with_project.execute(
        """INSERT INTO evidence_clusters
           (id, research_question_id, label, synthesis, confidence,
            claim_count, needs_reprocessing, synthesized_by, staleness,
            project_id)
           VALUES (?, ?, 'Bounded exploitability',
                   'The control reduced exploitability in the evaluated setting.',
                   'strong', 2, 0, 'brain', 'green', 'proj_default')""",
        [cluster_id, rq_id],
    )
    await db_with_project.execute(
        """INSERT INTO journal
           (id, type, content, source, confidence, importance, status, project_id)
           VALUES (?, 'finding', 'Two repeated extraction spans.', 'executor',
                   'tested', 'high', 'active', 'proj_default')""",
        [journal_id],
    )
    for claim_id in claim_ids:
        await db_with_project.execute(
            """INSERT INTO claims
               (id, source_entry_id, claim_type, content, confidence, verified,
                evidence_status, stale, staleness, project_id)
               VALUES (?, ?, 'result', 'Exploitability fell in the testbed.',
                       0.9, 1, 'supported', 0, 'green', 'proj_default')""",
            [claim_id, journal_id],
        )
        await db_with_project.execute(
            """INSERT INTO claim_edges
               (id, source_claim_id, cluster_id, relation, confidence,
                project_id)
               VALUES (?, ?, ?, 'member_of', 1.0, 'proj_default')""",
            [generate_id("claim_edge"), claim_id, cluster_id],
        )
    await db_with_project.commit()

    proposal = await service.get_writing_candidates(manuscript.id)
    assert proposal["summary"] == {
        "clusters_total": 1,
        "clusters_eligible": 1,
        "clusters_needing_review": 0,
        "claims_excluded": 0,
    }
    candidate = proposal["candidate_spine"]["claims"][0]
    assert candidate["status"] == "candidate"
    assert candidate["ratified_by"] is None
    assert candidate["evidence_ids"] == sorted(claim_ids)
    cluster = proposal["clusters"][0]
    assert cluster["disposition"] == "eligible"
    assert cluster["duplicate_support_groups"] == [sorted(claim_ids)]

    await db_with_project.execute(
        """INSERT INTO claim_edges
           (id, source_claim_id, target_claim_id, relation, confidence,
            project_id)
           VALUES (?, ?, ?, 'contradicts', 0.9, 'proj_default')""",
        [
            generate_id("claim_edge"),
            claim_ids[0],
            claim_ids[1],
        ],
    )
    await db_with_project.commit()
    blocked = await service.get_writing_candidates(manuscript.id)
    assert blocked["candidate_spine"]["claims"] == []
    assert "UNRESOLVED_COUNTEREVIDENCE" in blocked["clusters"][0]["blockers"]
    assert blocked["summary"]["claims_excluded"] == 2


@pytest.mark.asyncio
async def test_checkpoint_snapshots_detect_artifact_and_literature_drift(
    db_with_project,
) -> None:
    evidence_id = await _seed_ready_claim(db_with_project)
    artifact_id = generate_id("artifact")
    literature_id = generate_id("literature")
    await db_with_project.execute(
        """INSERT INTO artifacts
           (id, filename, filepath, filetype, content_hash, extraction_status,
            created_by, project_id)
           VALUES (?, 'results.csv', '/tmp/results.csv', 'csv', 'sha256:a',
                   'complete', 'executor', 'proj_default')""",
        [artifact_id],
    )
    await db_with_project.execute(
        """INSERT INTO literature
           (id, title, authors, year, doi, status, added_by, project_id)
           VALUES (?, 'A cited study', '["A. Author"]', 2025,
                   '10.1000/example', 'cited', 'pi', 'proj_default')""",
        [literature_id],
    )
    await db_with_project.commit()

    spine = _spine(evidence_id)
    spine["units"][0]["artifact_ref"] = artifact_id
    service = NativeManuscriptService(db_with_project, project_id="proj_default")
    manuscript = await service.create(
        ManuscriptCreate(title="Dependency drift", venue="IEEE S&P")
    )
    await service.upsert_argument_spine(
        manuscript.id,
        expected_revision=1,
        spine=spine,
    )
    await db_with_project.execute(
        """INSERT INTO reference_validation_attestations
           (id, project_id, manuscript_id, canonical_manuscript_id,
            literature_id, input_doi, input_title, input_authors, status,
            retraction_check_enabled, retraction_checked, sources_tried,
            sources_confirmed, notes, stage_trace, full_json_payload,
            pipeline_version, started_at, completed_at)
           VALUES (?, 'proj_default', ?, ?, ?, '10.1000/example',
                   'A cited study', '["A. Author"]', 'VERIFIED', 1, 1,
                   '["crossref"]', '["crossref"]', '[]', '{}', '{}',
                   'test/v1', '2026-07-22T11:00:00Z',
                   '2026-07-22T11:00:01Z')""",
        [
            generate_id("reference_validation"),
            manuscript.id,
            manuscript.id,
            literature_id,
        ],
    )
    await db_with_project.commit()
    await service.replace_reference_manifest(
        manuscript.id,
        ManuscriptReferenceManifestReplace(
            expected_revision=2,
            members=[
                {
                    "citation_key": "author2025study",
                    "literature_id": literature_id,
                }
            ],
        ),
    )

    revision = 3
    checkpoints: dict[str, str] = {}
    for kind in ("venue", "table_figure_plan", "reference_set"):
        checkpoint = await service.create_checkpoint(
            ManuscriptCheckpointCreate(
                manuscript_id=manuscript.id,
                kind=kind,
            ),
            expected_revision=revision,
        )
        revision += 1
        decision_id = await _seed_pi_decision(
            db_with_project,
            chosen=f"Approve {kind}",
        )
        await service.resolve_checkpoint(
            checkpoint.id,
            ManuscriptCheckpointResolve(
                decision_id=decision_id,
                status="resolved",
                resolved_at="2026-07-22T12:00:00Z",
            ),
            expected_revision=revision,
        )
        revision += 1
        checkpoints[kind] = checkpoint.id

    current = await service.get_context(manuscript.id)
    current_by_id = {row["id"]: row for row in current["checkpoints"]}
    assert all(
        current_by_id[checkpoint_id]["dependency_current"]
        for checkpoint_id in checkpoints.values()
    )

    # Projection synchronization and no-op metadata writes must preserve PI
    # approvals when their normalized semantic dependencies are unchanged.
    await service.upsert_argument_spine(
        manuscript.id,
        expected_revision=revision,
        spine=spine,
    )
    revision += 1
    await service.update(
        manuscript.id,
        ManuscriptUpdate(
            expected_revision=revision,
            venue="IEEE S&P",
        ),
    )
    revision += 1
    after_no_ops = await service.get_context(manuscript.id)
    no_op_by_id = {
        row["id"]: row for row in after_no_ops["checkpoints"]
    }
    assert all(
        no_op_by_id[checkpoint_id]["status"] == "resolved"
        and no_op_by_id[checkpoint_id]["dependency_current"]
        for checkpoint_id in checkpoints.values()
    )

    # A genuine venue change invalidates only fingerprints that include venue.
    await service.update(
        manuscript.id,
        ManuscriptUpdate(
            expected_revision=revision,
            venue="USENIX Security",
        ),
    )
    after_venue = await service.get_context(manuscript.id)
    venue_by_id = {row["id"]: row for row in after_venue["checkpoints"]}
    assert venue_by_id[checkpoints["venue"]]["status"] == "superseded"
    assert venue_by_id[checkpoints["table_figure_plan"]]["status"] == "resolved"
    assert venue_by_id[checkpoints["reference_set"]]["status"] == "resolved"

    await db_with_project.execute(
        """UPDATE artifacts SET content_hash = 'sha256:b'
           WHERE id = ? AND project_id = 'proj_default'""",
        [artifact_id],
    )
    await db_with_project.commit()
    after_artifact = await service.get_context(manuscript.id)
    artifact_by_id = {row["id"]: row for row in after_artifact["checkpoints"]}
    assert (
        artifact_by_id[checkpoints["table_figure_plan"]]["dependency_current"]
        is False
    )
    assert (
        artifact_by_id[checkpoints["reference_set"]]["dependency_current"]
        is True
    )

    await db_with_project.execute(
        """UPDATE literature
           SET title = 'A corrected cited study',
               updated_at = '2026-07-22T13:00:00Z'
           WHERE id = ? AND project_id = 'proj_default'""",
        [literature_id],
    )
    await db_with_project.commit()
    after_literature = await service.get_context(manuscript.id)
    literature_by_id = {
        row["id"]: row for row in after_literature["checkpoints"]
    }
    assert (
        literature_by_id[checkpoints["reference_set"]]["dependency_current"]
        is False
    )
