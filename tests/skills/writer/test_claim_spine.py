"""Offline contract tests for the RKA-backed manuscript claim spine.

The claim spine is a derived Writer artifact. RKA remains canonical: a filled
YAML cell is never evidence, a PI decision is ratification rather than
empirical support, and every claim-level evidence record must resolve through
its source record. These tests deliberately inject a resolver so they never
contact a live RKA server or an external API.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest


PROJECT_ID = "prj_01PPPPPPPPPPPPPPPPPPPPPPPP"
MANUSCRIPT_ID = "jrn_01MMMMMMMMMMMMMMMMMMMMMMMM"
DECISION_ID = "dec_01DDDDDDDDDDDDDDDDDDDDDDDD"
EVIDENCE_CLAIM_ID = "clm_01AAAAAAAAAAAAAAAAAAAAAAAA"
EVIDENCE_SOURCE_ID = "jrn_01EEEEEEEEEEEEEEEEEEEEEEEE"
QUALIFIER_CLAIM_ID = "clm_01QQQQQQQQQQQQQQQQQQQQQQQQ"
QUALIFIER_SOURCE_ID = "jrn_01LLLLLLLLLLLLLLLLLLLLLLLL"
COUNTER_CLAIM_ID = "clm_01CCCCCCCCCCCCCCCCCCCCCCCC"
COUNTER_SOURCE_ID = "jrn_01RRRRRRRRRRRRRRRRRRRRRRRR"
SYNTHESIS_ID = "ecl_01SSSSSSSSSSSSSSSSSSSSSSSS"


def _codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


def _copy_entities(entities: dict[str, dict]) -> dict[str, dict]:
    return deepcopy(entities)


def _place_entity_in_role(data: dict, role: str, entity_id: str) -> None:
    """Place a claim record in one exact v1 evidentiary role."""

    if role == "claim_evidence":
        data["claims"][0]["evidence_ids"] = [entity_id]
    elif role == "claim_qualifier":
        data["claims"][0]["qualifier_ids"] = [entity_id]
    elif role == "claim_counterevidence":
        data["claims"][0]["counterevidence_ids"] = [entity_id]
    elif role == "result_unit":
        result_unit = next(unit for unit in data["units"] if unit["kind"] == "result")
        result_unit["evidence_ids"].append(entity_id)
    else:  # pragma: no cover - protects future parameter additions
        raise AssertionError(f"unknown test role {role}")


def _legacy_snapshot_without_validation(claim_spine, data: dict, resolver) -> dict:
    """Simulate a pre-gate or externally forged snapshot for fail-closed tests."""

    resolved = claim_spine._resolve_closure(
        claim_spine._direct_entity_ids(data), resolver
    )
    captured_at = claim_spine._utc_now()
    return {
        "schema_version": claim_spine.SNAPSHOT_VERSION,
        "project_id": data["project_id"],
        "entities": {
            entity_id: claim_spine._entity_snapshot(
                entity_id, entity, at=captured_at
            )
            for entity_id, entity in sorted(resolved.items())
        },
    }


class TestLoadSpine:
    def test_loads_valid_yaml_as_plain_dict(
        self, claim_spine, claim_spine_fixture_dir: Path, claim_spine_data: dict
    ) -> None:
        loaded = claim_spine.load_spine(claim_spine_fixture_dir / "valid_spine.yaml")
        assert isinstance(loaded, dict)
        assert loaded == claim_spine_data
        assert loaded["schema_version"] == "rka-claim-spine/v1"

    def test_unsafe_yaml_tag_is_rejected(self, claim_spine, tmp_path: Path) -> None:
        path = tmp_path / "unsafe.yaml"
        path.write_text(
            "schema_version: !!python/object/apply:os.system ['echo unsafe']\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            claim_spine.load_spine(path)

    def test_non_mapping_document_is_rejected(self, claim_spine, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        path.write_text("- not\n- a\n- claim-spine\n", encoding="utf-8")
        with pytest.raises(ValueError, match="mapping|object|document"):
            claim_spine.load_spine(path)


class TestValidation:
    def test_current_source_backed_ratified_claim_passes(
        self, claim_spine, claim_spine_data, claim_spine_resolver
    ) -> None:
        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=claim_spine_resolver,
            project_id=PROJECT_ID,
        )
        assert report.verdict == "PASS"
        assert not {f for f in report.findings if f.severity == "BLOCK"}

    def test_resolver_absence_never_reports_pass(self, claim_spine, claim_spine_data) -> None:
        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=None,
            project_id=PROJECT_ID,
        )
        assert report.verdict == "ERROR"
        assert "RESOLVER_REQUIRED" in _codes(report)

    def test_candidate_claim_cannot_authorize_drafting(
        self, claim_spine, claim_spine_data, claim_spine_resolver
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["claims"][0]["status"] = "candidate"
        data["claims"][0]["ratified_by"] = None
        report = claim_spine.validate_spine(
            data,
            resolver=claim_spine_resolver,
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "RATIFICATION_REQUIRED" in _codes(report)

    def test_unknown_schema_version_blocks(
        self, claim_spine, claim_spine_data, claim_spine_resolver
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["schema_version"] = "rka-claim-spine/v99"
        report = claim_spine.validate_spine(
            data,
            resolver=claim_spine_resolver,
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "UNSUPPORTED_SCHEMA" in _codes(report)

    @pytest.mark.parametrize("claim_type", ["method", "result", "novelty"])
    def test_v1_rejects_non_empirical_claim_type(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_resolver,
        claim_type: str,
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["claims"][0]["claim_type"] = claim_type

        report = claim_spine.validate_spine(
            data,
            resolver=claim_spine_resolver,
            project_id=PROJECT_ID,
        )

        assert report.verdict == "BLOCK"
        assert "UNSUPPORTED_CLAIM_TYPE" in _codes(report)

    @pytest.mark.parametrize("invalid_id", [DECISION_ID, EVIDENCE_CLAIM_ID])
    def test_non_journal_entity_cannot_be_the_manuscript(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_resolver,
        invalid_id: str,
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["manuscript_id"] = invalid_id

        report = claim_spine.validate_spine(
            data,
            resolver=claim_spine_resolver,
            project_id=PROJECT_ID,
        )

        assert report.verdict == "BLOCK"
        assert "INVALID_MANUSCRIPT_ROLE" in _codes(report)

    def test_ordinary_journal_cannot_be_the_manuscript(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["manuscript_id"] = EVIDENCE_SOURCE_ID
        entities = _copy_entities(claim_spine_entities)
        entities[DECISION_ID]["related_journal"] = [EVIDENCE_SOURCE_ID]

        report = claim_spine.validate_spine(
            data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )

        assert report.verdict == "BLOCK"
        assert "MANUSCRIPT_TAG_REQUIRED" in _codes(report)

    def test_declared_manuscript_requires_exact_manuscript_tag(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[MANUSCRIPT_ID]["tags"] = ["phase:draft"]

        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )

        assert report.verdict == "BLOCK"
        assert "MANUSCRIPT_TAG_REQUIRED" in _codes(report)

    def test_manuscript_tagged_journal_cannot_be_terminal_empirical_evidence(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_SOURCE_ID]["tags"].append("manuscript")

        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )

        assert report.verdict == "BLOCK"
        assert "MANUSCRIPT_AS_EVIDENCE" in _codes(report)

    def test_duplicate_claim_ids_block(
        self, claim_spine, claim_spine_data, claim_spine_resolver
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["claims"].append(deepcopy(data["claims"][0]))
        report = claim_spine.validate_spine(
            data,
            resolver=claim_spine_resolver,
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "DUPLICATE_CLAIM_ID" in _codes(report)

    def test_missing_entity_blocks(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities.pop(EVIDENCE_CLAIM_ID)
        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "MISSING_ENTITY" in _codes(report)
        assert any(f.entity_id == EVIDENCE_CLAIM_ID for f in report.findings)

    def test_wrong_project_evidence_blocks(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_CLAIM_ID]["project_id"] = (
            "prj_01XXXXXXXXXXXXXXXXXXXXXXXX"
        )
        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "WRONG_PROJECT" in _codes(report)

    def test_packet_record_id_must_match_lookup_key(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_CLAIM_ID]["id"] = QUALIFIER_CLAIM_ID
        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "ENTITY_ID_MISMATCH" in _codes(report)

    def test_stale_claim_blocks(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_CLAIM_ID]["stale"] = True
        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "STALE_ENTITY" in _codes(report)

    def test_yellow_staleness_is_a_visible_warning_not_a_red_block(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_CLAIM_ID].update(
            stale=True,
            staleness="yellow",
            stale_reason="Review after a newer benchmark",
        )
        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )
        assert report.verdict == "WARN"
        assert "FRESHNESS_REVIEW_REQUIRED" in _codes(report)

    def test_red_staleness_blocks_even_when_legacy_flag_is_absent(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_CLAIM_ID].update(stale=False, staleness="red")
        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "STALE_ENTITY" in _codes(report)

    def test_expired_temporal_validity_blocks(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
        monkeypatch,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_CLAIM_ID]["valid_until"] = "2026-07-20T00:00:00Z"
        monkeypatch.setattr(
            claim_spine,
            "_utc_now",
            lambda: datetime(2026, 7, 22, tzinfo=timezone.utc),
        )
        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "TEMPORAL_VALIDITY_ENDED" in _codes(report)

    def test_historical_resolution_is_not_current_manuscript_support(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_CLAIM_ID].update(
            stale=False,
            staleness="green",
            staleness_verdict="historical",
        )
        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "INACTIVE_DISPOSITION" in _codes(report)

    def test_dismissed_freshness_concern_remains_current(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_CLAIM_ID].update(
            stale=False,
            staleness="green",
            staleness_verdict="dismissed",
        )
        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )
        assert report.verdict == "PASS"

    def test_unknown_freshness_metadata_fails_closed_as_error(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_CLAIM_ID]["staleness"] = "orange"
        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )
        assert report.verdict == "ERROR"
        assert "INVALID_FRESHNESS_METADATA" in _codes(report)

    def test_current_claim_with_retracted_source_blocks(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        """The source chain matters; clm_.stale=False is not sufficient."""
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_SOURCE_ID]["status"] = "retracted"
        entities[EVIDENCE_SOURCE_ID]["confidence"] = "retracted"
        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "STALE_SOURCE" in _codes(report)
        assert any(f.entity_id == EVIDENCE_SOURCE_ID for f in report.findings)

    def test_ungrounded_claim_cannot_support_ratified_empirical_claim(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_CLAIM_ID]["verified"] = False
        entities[EVIDENCE_CLAIM_ID]["confidence"] = 0.45
        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "GROUNDING_REQUIRED" in _codes(report)

    @pytest.mark.parametrize(
        ("role", "entity_id"),
        [
            ("claim_evidence", EVIDENCE_CLAIM_ID),
            ("claim_qualifier", QUALIFIER_CLAIM_ID),
            ("claim_counterevidence", COUNTER_CLAIM_ID),
            ("result_unit", COUNTER_CLAIM_ID),
        ],
    )
    def test_every_v1_claim_record_role_requires_grounding_fidelity(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
        role: str,
        entity_id: str,
    ) -> None:
        data = deepcopy(claim_spine_data)
        _place_entity_in_role(data, role, entity_id)
        entities = _copy_entities(claim_spine_entities)
        entities[entity_id]["verified"] = False

        report = claim_spine.validate_spine(
            data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )

        assert report.verdict == "BLOCK"
        assert any(
            finding.code == "GROUNDING_REQUIRED"
            and finding.entity_id == entity_id
            for finding in report.findings
        )

    @pytest.mark.parametrize(
        ("role", "entity_id"),
        [
            ("claim_evidence", EVIDENCE_CLAIM_ID),
            ("claim_qualifier", QUALIFIER_CLAIM_ID),
            ("claim_counterevidence", COUNTER_CLAIM_ID),
            ("result_unit", COUNTER_CLAIM_ID),
        ],
    )
    def test_every_v1_claim_record_role_requires_scientific_support_status(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
        role: str,
        entity_id: str,
    ) -> None:
        data = deepcopy(claim_spine_data)
        _place_entity_in_role(data, role, entity_id)
        entities = _copy_entities(claim_spine_entities)
        entities[entity_id]["evidence_status"] = "unassessed"

        report = claim_spine.validate_spine(
            data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )

        assert report.verdict == "BLOCK"
        assert any(
            finding.code == "SUPPORTED_EVIDENCE_REQUIRED"
            and finding.entity_id == entity_id
            for finding in report.findings
        )

    @pytest.mark.parametrize(
        ("role", "entity_id"),
        [
            ("claim_evidence", EVIDENCE_CLAIM_ID),
            ("claim_qualifier", QUALIFIER_CLAIM_ID),
            ("claim_counterevidence", COUNTER_CLAIM_ID),
            ("result_unit", COUNTER_CLAIM_ID),
        ],
    )
    def test_every_v1_claim_record_role_must_be_explicitly_uncontested(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
        role: str,
        entity_id: str,
    ) -> None:
        data = deepcopy(claim_spine_data)
        _place_entity_in_role(data, role, entity_id)
        entities = _copy_entities(claim_spine_entities)
        entities[entity_id]["contradicted"] = True

        report = claim_spine.validate_spine(
            data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )

        assert report.verdict == "BLOCK"
        assert any(
            finding.code == "UNCONTESTED_EVIDENCE_REQUIRED"
            and finding.entity_id == entity_id
            for finding in report.findings
        )

    def test_missing_contradiction_attestation_fails_closed(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_CLAIM_ID].pop("contradicted")

        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )

        assert report.verdict == "BLOCK"
        assert "UNCONTESTED_EVIDENCE_REQUIRED" in _codes(report)

    def test_legacy_verified_is_grounding_only_not_scientific_support(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_CLAIM_ID].pop("evidence_status")

        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )

        assert entities[EVIDENCE_CLAIM_ID]["verified"] is True
        assert report.verdict == "BLOCK"
        assert "SUPPORTED_EVIDENCE_REQUIRED" in _codes(report)
        assert "GROUNDING_REQUIRED" not in _codes(report)

    def test_partially_supported_is_an_eligible_scientific_support_status(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_CLAIM_ID]["evidence_status"] = "partially_supported"
        entities[QUALIFIER_CLAIM_ID]["evidence_status"] = "partially_supported"

        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )

        assert report.verdict == "PASS"

    @pytest.mark.parametrize("bad_evidence_id", [DECISION_ID, SYNTHESIS_ID])
    def test_decision_or_synthesis_alone_is_not_empirical_evidence(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_resolver,
        bad_evidence_id: str,
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["claims"][0]["evidence_ids"] = [bad_evidence_id]
        for unit in data["units"]:
            unit["evidence_ids"] = [bad_evidence_id]
        report = claim_spine.validate_spine(
            data,
            resolver=claim_spine_resolver,
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "INVALID_EVIDENCE_ROLE" in _codes(report)

    def test_direct_journal_cannot_replace_required_claim_source_chain(
        self, claim_spine, claim_spine_data, claim_spine_resolver
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["claims"][0]["evidence_ids"] = [EVIDENCE_SOURCE_ID]
        for unit in data["units"]:
            unit["evidence_ids"] = [EVIDENCE_SOURCE_ID]
        report = claim_spine.validate_spine(
            data,
            resolver=claim_spine_resolver,
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "INVALID_EVIDENCE_ROLE" in _codes(report)

    def test_empirical_claim_record_requires_terminal_source_link(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_CLAIM_ID].pop("source_entry_id")
        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "SOURCE_LINK_REQUIRED" in _codes(report)

    def test_inactive_terminal_source_blocks_claim_support(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_SOURCE_ID]["status"] = "inactive"
        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "STALE_SOURCE" in _codes(report)

    def test_ratified_claim_requires_current_pi_decision(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[DECISION_ID]["status"] = "superseded"
        entities[DECISION_ID]["superseded_by"] = (
            "dec_01NNNNNNNNNNNNNNNNNNNNNNNN"
        )
        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "RATIFICATION_REQUIRED" in _codes(report)

    def test_ratification_must_be_authored_by_pi(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[DECISION_ID]["decided_by"] = "brain"

        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )

        assert report.verdict == "BLOCK"
        assert "RATIFICATION_REQUIRED" in _codes(report)

    def test_ratification_must_belong_to_the_same_project(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[DECISION_ID]["project_id"] = "prj_01OTHERPROJECTXXXXXXXXXXXX"

        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )

        assert report.verdict == "BLOCK"
        assert {"WRONG_PROJECT", "RATIFICATION_REQUIRED"}.issubset(_codes(report))

    def test_ratification_must_explicitly_scope_this_manuscript(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[DECISION_ID]["related_journal"] = [EVIDENCE_SOURCE_ID]

        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )

        assert report.verdict == "BLOCK"
        assert "RATIFICATION_SCOPE_REQUIRED" in _codes(report)

    def test_soft_stale_decision_is_not_current_ratification(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[DECISION_ID]["staleness"] = "yellow"

        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )

        assert report.verdict == "BLOCK"
        assert {"FRESHNESS_REVIEW_REQUIRED", "RATIFICATION_REQUIRED"}.issubset(
            _codes(report)
        )

    def test_propagated_decision_staleness_in_assumptions_blocks_ratification(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[DECISION_ID]["assumptions"] = {"staleness": "red"}
        report = claim_spine.validate_spine(
            claim_spine_data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "RATIFICATION_REQUIRED" in _codes(report)

    def test_reprocessing_required_synthesis_cannot_enter_a_unit(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["units"][0]["evidence_ids"].append(SYNTHESIS_ID)
        entities = _copy_entities(claim_spine_entities)
        entities[SYNTHESIS_ID]["needs_reprocessing"] = True
        report = claim_spine.validate_spine(
            data,
            resolver=make_claim_spine_resolver(entities),
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "REPROCESSING_REQUIRED" in _codes(report)

    def test_edit_after_ratification_requires_new_decision(
        self, claim_spine, claim_spine_data, claim_spine_resolver
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["claims"][0]["text"] = (
            "The method eliminates attacks under every threat model."
        )
        report = claim_spine.validate_spine(
            data,
            resolver=claim_spine_resolver,
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "RATIFICATION_MISMATCH" in _codes(report)

    def test_unresolved_counterevidence_cannot_silently_support_strong_claim(
        self, claim_spine, claim_spine_data, claim_spine_resolver
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["claims"][0]["counterevidence_ids"] = [COUNTER_CLAIM_ID]
        report = claim_spine.validate_spine(
            data,
            resolver=claim_spine_resolver,
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "UNRESOLVED_CONTRADICTION" in _codes(report)
        assert any(f.entity_id == COUNTER_CLAIM_ID for f in report.findings)

    def test_fluent_text_without_evidence_still_blocks(
        self, claim_spine, claim_spine_data, claim_spine_resolver
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["claims"][0]["evidence_ids"] = []
        data["claims"][0]["allowed_wording"] = (
            "The extensive and comprehensive experimental campaign establishes "
            "the contribution with high confidence across realistic settings."
        )
        report = claim_spine.validate_spine(
            data,
            resolver=claim_spine_resolver,
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "EVIDENCE_REQUIRED" in _codes(report)

    def test_empirical_claim_without_result_unit_blocks(
        self, claim_spine, claim_spine_data, claim_spine_resolver
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["claims"][0]["manuscript_units"] = ["U-ABSTRACT-1"]
        data["units"] = [u for u in data["units"] if u["kind"] != "result"]
        report = claim_spine.validate_spine(
            data,
            resolver=claim_spine_resolver,
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "RESULT_COVERAGE_REQUIRED" in _codes(report)

    def test_result_unit_without_contribution_is_orphaned(
        self, claim_spine, claim_spine_data, claim_spine_resolver
    ) -> None:
        data = deepcopy(claim_spine_data)
        result_unit = next(u for u in data["units"] if u["kind"] == "result")
        result_unit["claim_ids"] = []
        report = claim_spine.validate_spine(
            data,
            resolver=claim_spine_resolver,
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "ORPHAN_RESULT" in _codes(report)

    def test_result_unit_without_evidence_blocks(
        self, claim_spine, claim_spine_data, claim_spine_resolver
    ) -> None:
        data = deepcopy(claim_spine_data)
        result_unit = next(unit for unit in data["units"] if unit["kind"] == "result")
        result_unit["evidence_ids"] = []
        report = claim_spine.validate_spine(
            data,
            resolver=claim_spine_resolver,
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "RESULT_EVIDENCE_REQUIRED" in _codes(report)

    @pytest.mark.parametrize("field", ["allowed_wording", "prohibited_wording"])
    def test_claim_boundary_fields_are_required(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_resolver,
        field: str,
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["claims"][0][field] = [] if field == "prohibited_wording" else ""
        report = claim_spine.validate_spine(
            data,
            resolver=claim_spine_resolver,
            project_id=PROJECT_ID,
        )
        assert report.verdict == "BLOCK"
        assert "CLAIM_BOUNDARY_REQUIRED" in _codes(report)


class TestSnapshotAndCurrency:
    def test_snapshot_is_deterministic_and_includes_terminal_sources(
        self, claim_spine, claim_spine_data, claim_spine_resolver
    ) -> None:
        original = deepcopy(claim_spine_data)
        first = claim_spine.build_snapshot(claim_spine_data, claim_spine_resolver)
        second = claim_spine.build_snapshot(claim_spine_data, claim_spine_resolver)
        assert first == second
        assert claim_spine_data == original, "snapshot builder mutated the claim spine"
        assert first["project_id"] == PROJECT_ID
        assert {
            MANUSCRIPT_ID,
            DECISION_ID,
            EVIDENCE_CLAIM_ID,
            EVIDENCE_SOURCE_ID,
            QUALIFIER_CLAIM_ID,
            QUALIFIER_SOURCE_ID,
        }.issubset(first["entities"])

    @pytest.mark.parametrize(
        ("updates", "expected"),
        [
            ({"stale": True}, "BLOCK"),
            ({"stale": True, "staleness": "yellow"}, "WARN"),
        ],
    )
    def test_snapshot_builder_refuses_nonpassing_live_state(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
        updates,
        expected,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_CLAIM_ID].update(updates)
        with pytest.raises(ValueError, match=f"got {expected}"):
            claim_spine.build_snapshot(
                claim_spine_data,
                make_claim_spine_resolver(entities),
            )

    def test_snapshot_builder_refuses_inactive_terminal_source(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_SOURCE_ID]["status"] = "inactive"
        with pytest.raises(ValueError, match="got BLOCK"):
            claim_spine.build_snapshot(
                claim_spine_data,
                make_claim_spine_resolver(entities),
            )

    def test_unchanged_snapshot_passes(
        self, claim_spine, claim_spine_data, claim_spine_resolver
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["rka_snapshot"] = claim_spine.build_snapshot(data, claim_spine_resolver)
        report = claim_spine.check_currency(data, claim_spine_resolver)
        assert report.verdict == "PASS"
        assert report.changed_entities == []
        assert report.affected_claims == []
        assert report.affected_units == []

    def test_retracted_source_invalidates_only_dependent_claim_and_units(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        claim_spine_resolver,
        make_claim_spine_resolver,
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["rka_snapshot"] = claim_spine.build_snapshot(data, claim_spine_resolver)

        changed = _copy_entities(claim_spine_entities)
        changed[EVIDENCE_SOURCE_ID]["status"] = "retracted"
        changed[EVIDENCE_SOURCE_ID]["confidence"] = "retracted"
        report = claim_spine.check_currency(
            data,
            make_claim_spine_resolver(changed),
        )
        assert report.verdict == "BLOCK"
        assert EVIDENCE_SOURCE_ID in report.changed_entities
        assert report.affected_claims == ["C1"]
        assert set(report.affected_units) == {"U-ABSTRACT-1", "U-RESULTS-1"}

    def test_inactive_source_blocks_currency_even_without_other_changes(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        claim_spine_resolver,
        make_claim_spine_resolver,
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["rka_snapshot"] = claim_spine.build_snapshot(data, claim_spine_resolver)

        changed = _copy_entities(claim_spine_entities)
        changed[EVIDENCE_SOURCE_ID]["status"] = "inactive"
        report = claim_spine.check_currency(
            data,
            make_claim_spine_resolver(changed),
        )

        assert report.verdict == "BLOCK"
        assert EVIDENCE_SOURCE_ID in report.changed_entities
        assert report.affected_claims == ["C1"]
        assert set(report.affected_units) == {"U-ABSTRACT-1", "U-RESULTS-1"}
        assert "STALE_SOURCE" in _codes(report)

    def test_current_content_change_requires_revalidation_without_rewriting_claim(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        claim_spine_resolver,
        make_claim_spine_resolver,
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["rka_snapshot"] = claim_spine.build_snapshot(data, claim_spine_resolver)
        licensed_before = data["claims"][0]["allowed_wording"]

        changed = _copy_entities(claim_spine_entities)
        changed[EVIDENCE_SOURCE_ID]["content"] += " A new platform C run was added."
        report = claim_spine.check_currency(
            data,
            make_claim_spine_resolver(changed),
        )
        assert report.verdict in {"WARN", "BLOCK"}
        assert EVIDENCE_SOURCE_ID in report.changed_entities
        assert "C1" in report.affected_claims
        assert data["claims"][0]["allowed_wording"] == licensed_before

    def test_missing_snapshot_is_error_not_pass(
        self, claim_spine, claim_spine_data, claim_spine_resolver
    ) -> None:
        report = claim_spine.check_currency(claim_spine_data, claim_spine_resolver)
        assert report.verdict == "ERROR"

    def test_snapshot_schema_or_project_mismatch_is_error(
        self, claim_spine, claim_spine_data, claim_spine_resolver
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["rka_snapshot"] = claim_spine.build_snapshot(data, claim_spine_resolver)
        data["rka_snapshot"]["schema_version"] = "rka-claim-spine-snapshot/v99"
        assert claim_spine.check_currency(data, claim_spine_resolver).verdict == "ERROR"

        data["rka_snapshot"]["schema_version"] = claim_spine.SNAPSHOT_VERSION
        data["rka_snapshot"]["project_id"] = "prj_01WRONG"
        assert claim_spine.check_currency(data, claim_spine_resolver).verdict == "ERROR"

    def test_unchanged_but_expired_dependency_still_blocks_currency(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
        monkeypatch,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_CLAIM_ID]["valid_until"] = "2026-07-20T00:00:00Z"
        resolver = make_claim_spine_resolver(entities)
        monkeypatch.setattr(
            claim_spine,
            "_utc_now",
            lambda: datetime(2026, 7, 22, tzinfo=timezone.utc),
        )
        data = deepcopy(claim_spine_data)
        data["rka_snapshot"] = _legacy_snapshot_without_validation(
            claim_spine, data, resolver
        )

        report = claim_spine.check_currency(data, resolver)

        assert report.verdict == "BLOCK"
        assert EVIDENCE_CLAIM_ID not in report.changed_entities
        assert report.affected_claims == ["C1"]
        assert "TEMPORAL_VALIDITY_ENDED" in _codes(report)

    def test_validity_boundary_crossing_is_detected_without_record_edit(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
        monkeypatch,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_CLAIM_ID]["valid_until"] = "2026-07-22T12:00:00Z"
        resolver = make_claim_spine_resolver(entities)
        data = deepcopy(claim_spine_data)
        monkeypatch.setattr(
            claim_spine,
            "_utc_now",
            lambda: datetime(2026, 7, 22, 11, tzinfo=timezone.utc),
        )
        data["rka_snapshot"] = claim_spine.build_snapshot(data, resolver)

        monkeypatch.setattr(
            claim_spine,
            "_utc_now",
            lambda: datetime(2026, 7, 22, 13, tzinfo=timezone.utc),
        )
        report = claim_spine.check_currency(data, resolver)

        assert report.verdict == "BLOCK"
        assert EVIDENCE_CLAIM_ID in report.changed_entities
        assert report.affected_claims == ["C1"]

    def test_unchanged_yellow_dependency_remains_visible_as_warning(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities[EVIDENCE_CLAIM_ID].update(stale=True, staleness="yellow")
        resolver = make_claim_spine_resolver(entities)
        data = deepcopy(claim_spine_data)
        data["rka_snapshot"] = _legacy_snapshot_without_validation(
            claim_spine, data, resolver
        )

        report = claim_spine.check_currency(data, resolver)

        assert report.verdict == "WARN"
        assert report.changed_entities == []
        assert report.affected_claims == ["C1"]
        assert "FRESHNESS_REVIEW_REQUIRED" in _codes(report)

    def test_unverified_change_blocks_currency_not_merely_warns(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        claim_spine_resolver,
        make_claim_spine_resolver,
    ) -> None:
        data = deepcopy(claim_spine_data)
        data["rka_snapshot"] = claim_spine.build_snapshot(data, claim_spine_resolver)
        changed = _copy_entities(claim_spine_entities)
        changed[EVIDENCE_CLAIM_ID].update(verified=False, confidence=0.4)

        report = claim_spine.check_currency(
            data, make_claim_spine_resolver(changed)
        )

        assert report.verdict == "BLOCK"
        assert "GROUNDING_REQUIRED" in _codes(report)
        assert report.affected_claims == ["C1"]

    def test_unit_only_terminal_source_change_targets_that_unit(
        self,
        claim_spine,
        claim_spine_data,
        claim_spine_entities,
        make_claim_spine_resolver,
    ) -> None:
        extra_claim = "clm_01UNITONLYAAAAAAAAAAAAAAAAAA"
        extra_source = "jrn_01UNITONLYSOURCEAAAAAAAAAAAA"
        data = deepcopy(claim_spine_data)
        result_unit = next(unit for unit in data["units"] if unit["kind"] == "result")
        result_unit["evidence_ids"].append(extra_claim)
        entities = _copy_entities(claim_spine_entities)
        entities[extra_claim] = {
            "id": extra_claim,
            "project_id": PROJECT_ID,
            "source_entry_id": extra_source,
            "claim_type": "result",
            "content": "A unit-specific robustness measurement was positive.",
            "confidence": 0.9,
            "verified": True,
            "evidence_status": "supported",
            "stale": False,
            "contradicted": False,
        }
        entities[extra_source] = {
            "id": extra_source,
            "project_id": PROJECT_ID,
            "type": "log",
            "content": "Unit-specific robustness run.",
            "status": "active",
            "confidence": "verified",
            "superseded_by": None,
        }
        resolver = make_claim_spine_resolver(entities)
        data["rka_snapshot"] = claim_spine.build_snapshot(data, resolver)

        changed = _copy_entities(entities)
        changed[extra_source]["content"] += " Rechecked with a corrected seed."
        report = claim_spine.check_currency(
            data, make_claim_spine_resolver(changed)
        )

        assert report.verdict == "WARN"
        assert extra_source in report.changed_entities
        assert report.affected_claims == []
        assert report.affected_units == ["U-RESULTS-1"]


class TestRendering:
    EXPECTED = {
        "contribution_contract": "CONTRIBUTION_CONTRACT.md",
        "argument_spine": "ARGUMENT_SPINE.md",
        "results_trace": "RESULTS_TRACE.md",
    }

    def test_render_views_writes_only_three_derived_markdown_files(
        self, claim_spine, claim_spine_data, tmp_path: Path
    ) -> None:
        paths = claim_spine.render_views(claim_spine_data, tmp_path)
        assert set(paths) == set(self.EXPECTED)
        assert {p.name for p in paths.values()} == set(self.EXPECTED.values())
        assert {p.name for p in tmp_path.iterdir()} == set(self.EXPECTED.values())
        for key, expected_name in self.EXPECTED.items():
            path = paths[key]
            assert isinstance(path, Path)
            assert path.name == expected_name
            text = path.read_text(encoding="utf-8")
            assert "generated" in text.lower()
            assert "RKA" in text

    def test_render_is_byte_deterministic_and_preserves_trace_ids(
        self, claim_spine, claim_spine_data, tmp_path: Path
    ) -> None:
        left = claim_spine.render_views(claim_spine_data, tmp_path / "left")
        right = claim_spine.render_views(claim_spine_data, tmp_path / "right")
        for key in self.EXPECTED:
            assert left[key].read_bytes() == right[key].read_bytes()

        combined = "\n".join(path.read_text(encoding="utf-8") for path in left.values())
        assert "C1" in combined
        assert DECISION_ID in combined
        assert EVIDENCE_CLAIM_ID in combined
        assert "U-RESULTS-1" in combined
        assert "universally attack-proof" in combined

    def test_render_does_not_mutate_canonical_spine(
        self, claim_spine, claim_spine_data, tmp_path: Path
    ) -> None:
        before = deepcopy(claim_spine_data)
        claim_spine.render_views(claim_spine_data, tmp_path)
        assert claim_spine_data == before


class TestCli:
    def test_render_subcommand_returns_zero(
        self, claim_spine, claim_spine_fixture_dir: Path, tmp_path: Path
    ) -> None:
        rc = claim_spine.main([
            "render",
            str(claim_spine_fixture_dir / "valid_spine.yaml"),
            "--output-dir",
            str(tmp_path),
        ])
        assert rc == 0
        assert (tmp_path / "CONTRIBUTION_CONTRACT.md").is_file()

    def test_missing_input_returns_usage_error(self, claim_spine, tmp_path: Path) -> None:
        rc = claim_spine.main([
            "render",
            str(tmp_path / "missing.yaml"),
            "--output-dir",
            str(tmp_path / "out"),
        ])
        assert rc == 3

    def test_snapshot_resolver_failure_returns_error_code(
        self,
        claim_spine,
        claim_spine_fixture_dir: Path,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        def failing_resolver(_entity_id: str):
            raise RuntimeError("offline")

        monkeypatch.setattr(
            claim_spine,
            "_rest_resolver",
            lambda *_args, **_kwargs: failing_resolver,
        )
        output = tmp_path / "snapshot.yaml"
        rc = claim_spine.main([
            "snapshot",
            str(claim_spine_fixture_dir / "valid_spine.yaml"),
            "--rka-url",
            "http://127.0.0.1:9712",
            "--output",
            str(output),
        ])
        assert rc == 3
        assert not output.exists()

    def test_snapshot_block_writes_no_baseline(
        self,
        claim_spine,
        claim_spine_fixture_dir: Path,
        claim_spine_entities: dict,
        tmp_path: Path,
    ) -> None:
        entities = _copy_entities(claim_spine_entities)
        entities.pop(EVIDENCE_SOURCE_ID)
        packet = tmp_path / "missing-source.json"
        packet.write_text(
            json.dumps({"project_id": PROJECT_ID, "entities": entities}),
            encoding="utf-8",
        )
        output = tmp_path / "must-not-exist.yaml"

        rc = claim_spine.main([
            "snapshot",
            str(claim_spine_fixture_dir / "valid_spine.yaml"),
            "--entity-packet",
            str(packet),
            "--output",
            str(output),
        ])

        assert rc == 2
        assert not output.exists()


class TestRestResolver:
    def test_scopes_requests_and_requires_server_attested_project_id(
        self, claim_spine, monkeypatch
    ) -> None:
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def read() -> bytes:
                return (
                    b'{"id":"jrn_01EXAMPLE","status":"active",'
                    b'"project_id":"prj_01PPPPPPPPPPPPPPPPPPPPPPPP"}'
                )

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return Response()

        monkeypatch.setattr(claim_spine, "urlopen", fake_urlopen)
        resolver = claim_spine._rest_resolver(
            "http://127.0.0.1:9712",
            timeout=4.0,
            project_id=PROJECT_ID,
        )
        entity = resolver("jrn_01EXAMPLE")

        headers = {
            key.lower(): value for key, value in captured["request"].header_items()
        }
        assert headers["x-rka-project"] == PROJECT_ID
        assert captured["timeout"] == 4.0
        assert entity["project_id"] == PROJECT_ID

    def test_missing_server_project_attestation_fails_closed(
        self, claim_spine, monkeypatch
    ) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def read() -> bytes:
                return b'{"id":"jrn_01EXAMPLE","status":"active"}'

        monkeypatch.setattr(claim_spine, "urlopen", lambda *_args, **_kwargs: Response())
        resolver = claim_spine._rest_resolver(
            "http://127.0.0.1:9712",
            project_id=PROJECT_ID,
        )
        with pytest.raises(RuntimeError, match="did not attest"):
            resolver("jrn_01EXAMPLE")


class TestEntityPacketResolver:
    def test_cli_validates_with_fresh_project_scoped_packet(
        self,
        claim_spine,
        claim_spine_fixture_dir: Path,
        claim_spine_entities: dict,
        tmp_path: Path,
    ) -> None:
        packet = tmp_path / "entities.json"
        packet.write_text(
            json.dumps({"project_id": PROJECT_ID, "entities": claim_spine_entities}),
            encoding="utf-8",
        )
        rc = claim_spine.main([
            "validate",
            str(claim_spine_fixture_dir / "valid_spine.yaml"),
            "--entity-packet",
            str(packet),
            "--project",
            PROJECT_ID,
        ])
        assert rc == 0

    def test_packet_project_mismatch_fails_closed(
        self,
        claim_spine,
        claim_spine_fixture_dir: Path,
        claim_spine_entities: dict,
        tmp_path: Path,
    ) -> None:
        packet = tmp_path / "wrong-project.json"
        packet.write_text(
            json.dumps(
                {
                    "project_id": "prj_01XXXXXXXXXXXXXXXXXXXXXXXX",
                    "entities": claim_spine_entities,
                }
            ),
            encoding="utf-8",
        )
        rc = claim_spine.main([
            "validate",
            str(claim_spine_fixture_dir / "valid_spine.yaml"),
            "--entity-packet",
            str(packet),
        ])
        assert rc == 3
