"""Semantic cursor and manuscript-impact service contracts."""

from __future__ import annotations

import pytest

from rka.services.change_tracking import ChangeTrackingService
from rka.services.manuscript_native import ManuscriptNotFoundError


async def _seed_project(db, project_id: str) -> None:
    await db.execute(
        """INSERT INTO projects (id, name, created_by)
           VALUES (?, ?, 'system')""",
        [project_id, project_id],
    )


async def _seed_core_claim(
    db,
    *,
    project_id: str,
    journal_id: str,
    claim_id: str,
    content: str = "bounded result",
) -> None:
    await db.execute(
        """INSERT INTO journal (
               id, type, content, source, status, confidence, project_id
           ) VALUES (?, 'note', ?, 'executor', 'active', 'verified', ?)""",
        [journal_id, content, project_id],
    )
    await db.execute(
        """INSERT INTO claims (
               id, source_entry_id, claim_type, content, confidence,
               verified, stale, evidence_status, project_id
           ) VALUES (?, ?, 'result', ?, 0.8, 1, 0, 'supported', ?)""",
        [claim_id, journal_id, content, project_id],
    )


async def _seed_native_manuscript(db, project_id: str) -> None:
    await db.execute(
        """INSERT INTO manuscripts (
               id, project_id, title, venue, legacy_journal_id
           ) VALUES (
               'man_cursor', ?, 'Cursor Paper', 'Security Venue', 'jrn_bound'
           )""",
        [project_id],
    )
    await db.execute(
        """INSERT INTO manuscript_claims (
               id, manuscript_id, project_id, local_key, kind, state
           ) VALUES (
               'mcl_cursor', 'man_cursor', ?, 'C1', 'empirical', 'active'
           )""",
        [project_id],
    )
    await db.execute(
        """INSERT INTO manuscript_claim_versions (
               claim_id, version, manuscript_id, project_id,
               exact_wording, allowed_wording, prohibited_wording
           ) VALUES (
               'mcl_cursor', 1, 'man_cursor', ?,
               'The bounded result held in the tested setting.',
               'The result held in the tested setting.',
               '["The result always holds."]'
           )""",
        [project_id],
    )
    await db.execute(
        """INSERT INTO manuscript_units (
               id, manuscript_id, project_id, local_key, kind, location,
               artifact_ref, allowed_interpretation,
               prohibited_interpretation, status
           ) VALUES (
               'mun_cursor', 'man_cursor', ?, 'R1', 'result',
               'sections/results.tex#bounded-result',
               'figures/bounded-result.pdf',
               'The result applies to the evaluated systems.',
               'The result is universal.',
               'drafted'
           )""",
        [project_id],
    )
    await db.execute(
        """INSERT INTO manuscript_claim_evidence (
               manuscript_id, project_id, manuscript_claim_id,
               claim_version, evidence_claim_id, role
           ) VALUES (
               'man_cursor', ?, 'mcl_cursor', 1, 'clm_bound', 'support'
           )""",
        [project_id],
    )
    await db.execute(
        """INSERT INTO manuscript_unit_evidence (
               manuscript_id, project_id, unit_id, evidence_claim_id, role
           ) VALUES (
               'man_cursor', ?, 'mun_cursor', 'clm_bound', 'support'
           )""",
        [project_id],
    )
    await db.execute(
        """INSERT INTO manuscript_claim_units (
               manuscript_id, project_id, manuscript_claim_id,
               claim_version, unit_id, relationship
           ) VALUES (
               'man_cursor', ?, 'mcl_cursor', 1, 'mun_cursor', 'advances'
           )""",
        [project_id],
    )


async def _latest_cursor(db) -> int:
    row = await db.fetchone("SELECT COALESCE(MAX(cursor), 0) AS cursor FROM change_events")
    return int(row["cursor"])


@pytest.mark.asyncio
async def test_change_cursor_is_monotonic_project_scoped_and_tracks_tag_edges(
    db,
) -> None:
    for project_id in ("prj_cursor_a", "prj_cursor_b"):
        await _seed_project(db, project_id)
        await _seed_core_claim(
            db,
            project_id=project_id,
            journal_id=f"jrn_{project_id[-1]}",
            claim_id=f"clm_{project_id[-1]}",
        )
    await db.commit()
    baseline = await _latest_cursor(db)

    await db.execute(
        """INSERT INTO tags (tag, entity_type, entity_id, project_id)
           VALUES ('writing-critical', 'journal', 'jrn_a', 'prj_cursor_a')"""
    )
    after_tag = await _latest_cursor(db)
    assert after_tag > baseline

    await db.execute(
        """INSERT INTO entity_links (
               id, source_type, source_id, link_type, target_type, target_id,
               created_by, project_id
           ) VALUES (
               'lnk_cursor', 'journal', 'jrn_a', 'derived_from',
               'claim', 'clm_a', 'system', 'prj_cursor_a'
           )"""
    )
    after_edge = await _latest_cursor(db)
    assert after_edge > after_tag

    await db.execute(
        """INSERT INTO tags (tag, entity_type, entity_id, project_id)
           VALUES ('foreign', 'journal', 'jrn_b', 'prj_cursor_b')"""
    )
    await db.commit()

    service = ChangeTrackingService(db, project_id="prj_cursor_a")
    page = await service.changes_since(baseline)

    assert page["schema_version"] == "rka-change-cursor/v1"
    assert page["project_id"] == "prj_cursor_a"
    assert page["next_cursor"] == after_edge
    assert page["latest_cursor"] == after_edge
    assert page["has_more"] is False
    assert [change["source_table"] for change in page["changes"]] == [
        "tags",
        "entity_links",
    ]
    assert [change["cursor"] for change in page["changes"]] == sorted(
        change["cursor"] for change in page["changes"]
    )

    first_page = await service.changes_since(baseline, limit=1)
    assert first_page["has_more"] is True
    second_page = await service.changes_since(first_page["next_cursor"], limit=1)
    assert second_page["has_more"] is False
    assert first_page["changes"][0]["cursor"] < second_page["changes"][0]["cursor"]


@pytest.mark.asyncio
@pytest.mark.writer
async def test_tag_and_claim_edge_changes_map_to_writer_claim_and_file(db) -> None:
    project_id = "prj_impact"
    await _seed_project(db, project_id)
    await _seed_core_claim(
        db,
        project_id=project_id,
        journal_id="jrn_bound",
        claim_id="clm_bound",
    )
    await _seed_core_claim(
        db,
        project_id=project_id,
        journal_id="jrn_neighbor",
        claim_id="clm_neighbor",
        content="neighboring result",
    )
    await _seed_native_manuscript(db, project_id)
    await db.commit()
    baseline = await _latest_cursor(db)

    # Neither write touches the bound claim row.  The metadata/edge triggers
    # must still advance the cursor and carry enough endpoints for impact.
    await db.execute(
        """INSERT INTO tags (tag, entity_type, entity_id, project_id)
           VALUES ('needs-recheck', 'journal', 'jrn_bound', ?)""",
        [project_id],
    )
    await db.execute(
        """INSERT INTO claim_edges (
               id, source_claim_id, target_claim_id, relation,
               confidence, project_id
           ) VALUES (
               'ced_cursor', 'clm_neighbor', 'clm_bound',
               'qualifies', 0.7, ?
           )""",
        [project_id],
    )
    await db.commit()

    service = ChangeTrackingService(db, project_id=project_id)
    impact = await service.get_manuscript_impact(
        "jrn_bound",
        since_cursor=baseline,
    )

    assert impact["schema_version"] == "rka-manuscript-impact/v1"
    assert impact["manuscript_id"] == "man_cursor"
    assert impact["requested_manuscript_id"] == "jrn_bound"
    assert impact["impact_state"] == "relevant_changes"
    assert impact["changed_evidence_claim_ids"] == ["clm_bound"]
    assert {
        (item["entity_type"], item["entity_id"])
        for item in impact["changed_sources"]
    } >= {
        ("claim", "clm_bound"),
        ("claim", "clm_neighbor"),
        ("journal", "jrn_bound"),
    }

    assert [item["id"] for item in impact["affected_manuscript_claims"]] == [
        "mcl_cursor"
    ]
    affected_claim = impact["affected_manuscript_claims"][0]
    assert affected_claim["local_key"] == "C1"
    assert affected_claim["current_version"] == 1
    assert affected_claim["evidence_claim_ids"] == ["clm_bound"]

    assert [item["id"] for item in impact["affected_units"]] == ["mun_cursor"]
    assert impact["file_locations"] == [
        "sections/results.tex#bounded-result"
    ]
    assert impact["artifact_refs"] == ["figures/bounded-result.pdf"]
    assert {
        item["source_table"] for item in impact["relevant_changes"]
    } == {"tags", "claim_edges"}


@pytest.mark.asyncio
@pytest.mark.writer
async def test_canonical_reference_attestation_is_manuscript_wide(db) -> None:
    project_id = "prj_reference_impact"
    await _seed_project(db, project_id)
    await _seed_core_claim(
        db,
        project_id=project_id,
        journal_id="jrn_bound",
        claim_id="clm_bound",
    )
    await _seed_native_manuscript(db, project_id)
    await db.commit()
    baseline = await _latest_cursor(db)

    await db.execute(
        """INSERT INTO reference_validation_attestations (
               id, project_id, manuscript_id, canonical_manuscript_id,
               input_authors, status, retraction_check_enabled,
               retraction_checked, sources_tried, sources_confirmed, notes,
               stage_trace, full_json_payload, started_at, completed_at
           ) VALUES (
               'rvd_impact', ?, 'man_cursor', 'man_cursor', '[]', 'VERIFIED',
               1, 1, '[]', '[]', '[]', '{}', '{}', 'start', 'end'
           )""",
        [project_id],
    )
    await db.commit()

    impact = await ChangeTrackingService(
        db, project_id=project_id
    ).get_manuscript_impact("man_cursor", since_cursor=baseline)

    assert impact["impact_state"] == "relevant_changes"
    assert [item["id"] for item in impact["affected_manuscript_claims"]] == [
        "mcl_cursor"
    ]
    assert [item["id"] for item in impact["affected_units"]] == ["mun_cursor"]
    assert impact["file_locations"] == ["sections/results.tex#bounded-result"]


@pytest.mark.asyncio
@pytest.mark.writer
async def test_typed_citation_change_maps_to_exact_unit_and_adjacent_claim(db) -> None:
    project_id = "prj_citation_impact"
    await _seed_project(db, project_id)
    await _seed_core_claim(
        db,
        project_id=project_id,
        journal_id="jrn_bound",
        claim_id="clm_bound",
    )
    await _seed_native_manuscript(db, project_id)
    await db.execute(
        """INSERT INTO literature
           (id, title, authors, year, doi, status, added_by, project_id)
           VALUES ('lit_cursor', 'Prior baseline', '[]', 2025,
                   '10.1000/cursor', 'cited', 'pi', ?)""",
        [project_id],
    )
    await db.execute(
        """INSERT INTO manuscript_reference_members
           (id, manuscript_id, project_id, citation_key, literature_id)
           VALUES ('mrf_cursor', 'man_cursor', ?, 'prior2025', 'lit_cursor')""",
        [project_id],
    )
    await db.commit()
    baseline = await _latest_cursor(db)

    await db.execute(
        """INSERT INTO manuscript_unit_citations
           (id, manuscript_id, project_id, unit_id, reference_member_id,
            citation_role, supported_proposition, verification_state)
           VALUES ('muc_cursor', 'man_cursor', ?, 'mun_cursor', 'mrf_cursor',
                   'baseline', 'The result uses the prior baseline.',
                   'self_attested')""",
        [project_id],
    )
    await db.commit()

    impact = await ChangeTrackingService(
        db, project_id=project_id
    ).get_manuscript_impact("man_cursor", since_cursor=baseline)
    assert impact["impact_state"] == "relevant_changes"
    assert [item["id"] for item in impact["affected_units"]] == ["mun_cursor"]
    assert [item["id"] for item in impact["affected_manuscript_claims"]] == [
        "mcl_cursor"
    ]
    citation_change = next(
        item
        for item in impact["relevant_changes"]
        if item["entity_type"] == "manuscript_citation"
    )
    assert citation_change["affected_unit_ids"] == ["mun_cursor"]


@pytest.mark.asyncio
@pytest.mark.writer
async def test_active_reference_literature_change_is_manuscript_wide(db) -> None:
    project_id = "prj_reference_literature_impact"
    await _seed_project(db, project_id)
    await _seed_core_claim(
        db,
        project_id=project_id,
        journal_id="jrn_bound",
        claim_id="clm_bound",
    )
    await _seed_native_manuscript(db, project_id)
    await db.execute(
        """INSERT INTO literature (
               id, title, doi, status, added_by, project_id
           ) VALUES (
               'lit_reference_impact', 'Original title', '10.1000/impact',
               'cited', 'pi', ?
           )""",
        [project_id],
    )
    await db.execute(
        """INSERT INTO manuscript_reference_members (
               id, manuscript_id, project_id, citation_key, literature_id
           ) VALUES (
               'mrf_reference_impact', 'man_cursor', ?,
               'impact2026', 'lit_reference_impact'
           )""",
        [project_id],
    )
    await db.commit()
    baseline = await _latest_cursor(db)

    await db.execute(
        """UPDATE literature
           SET title = 'Corrected title'
           WHERE id = 'lit_reference_impact' AND project_id = ?""",
        [project_id],
    )
    await db.commit()

    impact = await ChangeTrackingService(
        db,
        project_id=project_id,
    ).get_manuscript_impact("man_cursor", since_cursor=baseline)
    assert impact["impact_state"] == "relevant_changes"
    assert impact["relevant_changes"][0]["manuscript_wide"] is True
    assert [item["id"] for item in impact["affected_manuscript_claims"]] == [
        "mcl_cursor"
    ]
    assert [item["id"] for item in impact["affected_units"]] == ["mun_cursor"]
    assert {
        (item["entity_type"], item["entity_id"])
        for item in impact["changed_sources"]
    } >= {("literature", "lit_reference_impact")}


@pytest.mark.asyncio
@pytest.mark.writer
async def test_native_unit_and_decision_changes_map_through_current_topology(db) -> None:
    project_id = "prj_native_impact"
    await _seed_project(db, project_id)
    await _seed_core_claim(
        db,
        project_id=project_id,
        journal_id="jrn_bound",
        claim_id="clm_bound",
    )
    await _seed_native_manuscript(db, project_id)
    await db.execute(
        """INSERT INTO decisions (
               id, phase, question, chosen, rationale, decided_by,
               status, project_id
           ) VALUES (
               'dec_ratify', 'paper_writing', 'Ratify claim?',
               'The bounded result held in the tested setting.',
               'PI selected exact wording.', 'pi', 'active', ?
           )""",
        [project_id],
    )
    await db.execute(
        """INSERT INTO manuscript_claim_ratifications (
               id, manuscript_id, project_id, claim_id, claim_version,
               decision_id, ratified_at
           ) VALUES (
               'mra_cursor', 'man_cursor', ?, 'mcl_cursor', 1,
               'dec_ratify', '2026-07-22T12:00:00Z'
           )""",
        [project_id],
    )
    await db.commit()
    baseline = await _latest_cursor(db)

    await db.execute(
        """UPDATE manuscript_units
           SET location = 'sections/results.tex#updated-location'
           WHERE id = 'mun_cursor' AND project_id = ?""",
        [project_id],
    )
    await db.execute(
        """UPDATE decisions
           SET rationale = 'PI confirmed the exact bounded wording.'
           WHERE id = 'dec_ratify' AND project_id = ?""",
        [project_id],
    )
    await db.commit()

    impact = await ChangeTrackingService(
        db, project_id=project_id
    ).get_manuscript_impact("man_cursor", since_cursor=baseline)

    assert impact["impact_state"] == "relevant_changes"
    assert [item["id"] for item in impact["affected_manuscript_claims"]] == [
        "mcl_cursor"
    ]
    assert [item["id"] for item in impact["affected_units"]] == ["mun_cursor"]
    assert impact["file_locations"] == [
        "sections/results.tex#updated-location"
    ]
    assert {
        item["source_table"] for item in impact["changed_native_entities"]
    } == {"manuscript_units"}


@pytest.mark.asyncio
async def test_cursor_arguments_fail_closed(db) -> None:
    service = ChangeTrackingService(db, project_id="proj_default")
    with pytest.raises(ValueError, match="non-negative"):
        await service.changes_since(-1)
    with pytest.raises(ValueError, match="between"):
        await service.changes_since(0, limit=0)


@pytest.mark.asyncio
@pytest.mark.writer
async def test_manuscript_impact_missing_id_fails_closed(db) -> None:
    service = ChangeTrackingService(db, project_id="proj_default")
    with pytest.raises(ManuscriptNotFoundError, match="not found"):
        await service.get_manuscript_impact("man_missing")


@pytest.mark.asyncio
async def test_change_event_rolls_back_with_owning_semantic_write(db) -> None:
    baseline = await _latest_cursor(db)

    with pytest.raises(RuntimeError, match="abort semantic write"):
        async with db.transaction():
            await db.execute(
                """INSERT INTO tags (
                       tag, entity_type, entity_id, project_id
                   ) VALUES (
                       'rolled-back', 'journal', 'jrn_rolled_back',
                       'proj_default'
                   )"""
            )
            raise RuntimeError("abort semantic write")

    assert await _latest_cursor(db) == baseline
    assert await db.fetchone(
        """SELECT 1 FROM tags
           WHERE tag = 'rolled-back' AND entity_id = 'jrn_rolled_back'"""
    ) is None


@pytest.mark.asyncio
@pytest.mark.writer
async def test_unrelated_changes_do_not_leak_into_manuscript_changed_sources(db) -> None:
    project_id = "prj_unrelated_impact"
    await _seed_project(db, project_id)
    await _seed_core_claim(
        db,
        project_id=project_id,
        journal_id="jrn_bound",
        claim_id="clm_bound",
    )
    await _seed_native_manuscript(db, project_id)
    await db.commit()
    baseline = await _latest_cursor(db)

    await db.execute(
        """INSERT INTO journal (
               id, type, content, source, status, confidence, project_id
           ) VALUES (
               'jrn_unrelated', 'note', 'unrelated', 'executor',
               'active', 'hypothesis', ?
           )""",
        [project_id],
    )
    await db.commit()

    impact = await ChangeTrackingService(
        db,
        project_id=project_id,
    ).get_manuscript_impact("man_cursor", since_cursor=baseline)
    assert impact["impact_state"] == "no_relevant_changes"
    assert impact["changed_sources"] == []


@pytest.mark.asyncio
@pytest.mark.writer
async def test_experiment_locator_change_maps_through_reviewed_claim_to_writer(db) -> None:
    project_id = "prj_experiment_impact"
    await _seed_project(db, project_id)
    await _seed_core_claim(
        db,
        project_id=project_id,
        journal_id="jrn_bound",
        claim_id="clm_bound",
    )
    await _seed_native_manuscript(db, project_id)
    await db.execute(
        """INSERT INTO experiments (
               id, project_id, title, status, current_plan_version,
               revision, created_by
           ) VALUES (
               'exp_impact', ?, 'Impact experiment', 'active', 1, 2, 'brain'
           )""",
        [project_id],
    )
    await db.execute(
        """INSERT INTO experiment_plan_versions (
               id, experiment_id, project_id, version, objective, protocol,
               created_by, reason
           ) VALUES (
               'epv_impact', 'exp_impact', ?, 1, 'Test bounded result',
               'Run exact benchmark', 'brain', 'Test manuscript evidence'
           )""",
        [project_id],
    )
    await db.execute(
        """INSERT INTO experiment_runs (
               id, experiment_id, project_id, plan_version, label, runner,
               status, started_at, revision, created_by
           ) VALUES (
               'run_impact', 'exp_impact', ?, 1, 'impact run', 'local',
               'running', '2026-08-15T12:00:00Z', 2, 'executor'
           )""",
        [project_id],
    )
    await db.execute(
        """INSERT INTO experiment_observations (
               id, run_id, project_id, name, kind, direction, summary,
               value_real, unit, observed_at, recorded_by
           ) VALUES (
               'obs_impact', 'run_impact', ?, 'bounded result', 'metric',
               'positive', 'The bounded result was measured.', 1.0, 'score',
               '2026-08-15T12:01:00Z', 'executor'
           )""",
        [project_id],
    )
    await db.execute(
        """INSERT INTO interpretation_candidates (
               id, project_id, source_type, source_id, locator_kind,
               locator_value, statement, epistemic_kind, created_by,
               extraction_tool, review_status, disposition,
               disposition_reason, disposition_target_type,
               disposition_target_id, reviewed_by, reviewed_at, revision
           ) VALUES (
               'icd_impact', ?, 'experiment_observation', 'obs_impact',
               'record', 'full_record', 'The bounded result was measured.',
               'observation', 'brain', 'impact_test', 'resolved',
               'classified_evidence', 'Reviewed exact evidence.', 'claim',
               'clm_bound', 'pi', '2026-08-15T12:02:00Z', 2
           )""",
        [project_id],
    )
    await db.execute(
        """INSERT INTO claim_evidence_relations (
               id, project_id, claim_id, observation_id, candidate_id,
               role, reviewed_by, review_reason
           ) VALUES (
               'evr_impact', ?, 'clm_bound', 'obs_impact', 'icd_impact',
               'support', 'pi', 'Reviewed exact evidence.'
           )""",
        [project_id],
    )
    await db.commit()
    baseline = await _latest_cursor(db)

    await db.execute(
        """INSERT INTO evidence_locators (
               id, observation_id, project_id, source_kind, repository_url,
               commit_sha, relative_path, locator_kind, locator_value,
               content_hash, created_by
           ) VALUES (
               'elc_impact', 'obs_impact', ?, 'repository',
               'https://github.com/example/evaluation',
               '0123456789abcdef0123456789abcdef01234567',
               'results/impact.json', 'json_pointer', '/result', ?, 'executor'
           )""",
        [project_id, "c" * 64],
    )
    await db.commit()

    impact = await ChangeTrackingService(
        db, project_id=project_id
    ).get_manuscript_impact("man_cursor", since_cursor=baseline)

    assert impact["impact_state"] == "relevant_changes"
    assert impact["changed_evidence_claim_ids"] == ["clm_bound"]
    assert [item["id"] for item in impact["affected_manuscript_claims"]] == [
        "mcl_cursor"
    ]
    assert [item["id"] for item in impact["affected_units"]] == ["mun_cursor"]
    assert impact["file_locations"] == ["sections/results.tex#bounded-result"]
    assert impact["relevant_changes"][0]["source_table"] == "evidence_locators"
    assert {
        (item["entity_type"], item["entity_id"])
        for item in impact["changed_sources"]
    } >= {
        ("evidence_locator", "elc_impact"),
        ("experiment_observation", "obs_impact"),
        ("claim", "clm_bound"),
    }
