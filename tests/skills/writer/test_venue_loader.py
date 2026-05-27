"""Phase W1 — venue.yaml loader + validation tests.

Covers:
  - All 7 migrated venues (CHI, EMNLP, IEEE-SP, Nature, NeurIPS, OSDI, USENIX)
    load successfully and round-trip through the dataclass
  - Required-field enforcement on each enum
  - load_all_venues returns a dict keyed by venue.id; no duplicates
  - merge_inheritance overlays child onto base correctly
  - Invalid YAML raises VenueValidationError with a precise message
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


SHIPPED_VENUE_IDS = {"CHI", "EMNLP", "IEEE-SP", "Nature", "NeurIPS", "OSDI", "USENIX"}


def test_all_shipped_venues_load(venue_loader):
    venues = venue_loader.load_all_venues()
    assert SHIPPED_VENUE_IDS.issubset(venues.keys()), (
        f"missing shipped venues: {SHIPPED_VENUE_IDS - venues.keys()}"
    )


def test_each_shipped_venue_round_trips(venue_loader):
    for vid in SHIPPED_VENUE_IDS:
        v = venue_loader.load_venue(vid)
        d = venue_loader.venue_to_dict(v)
        # Round-trip: dict → dataclass → dict should be stable.
        v2 = venue_loader.venue_from_dict(d, source=vid)
        d2 = venue_loader.venue_to_dict(v2)
        assert d == d2, f"{vid}: round-trip differs"


def test_neurips_has_known_constraints(venue_loader):
    """Spot-check NeurIPS to catch silent schema drift."""
    v = venue_loader.load_venue("NeurIPS")
    assert v.kind == "conference"
    assert v.domain == "cs-ml"
    assert v.submission.page_limit_main == 9
    assert v.submission.references_counted is False
    assert v.submission.has_required_checklist is True
    assert v.tone.multi_seed_required is True
    assert v.tone.reproducibility_floor == "high"
    # Forbidden constructions present.
    patterns = [fc.pattern for fc in v.forbidden_constructions]
    assert "we propose a novel" in patterns


def test_nature_has_word_count_journal_shape(venue_loader):
    v = venue_loader.load_venue("Nature")
    assert v.kind == "journal"
    assert v.submission.page_limit_main is None  # word-count gated, no page limit
    assert v.format.citation_style == "vancouver"
    assert "Lead paragraph" in v.structure.required_sections


def test_chi_has_high_hedging(venue_loader):
    """HCI venues lean toward higher hedging than ML venues."""
    chi = venue_loader.load_venue("CHI")
    neurips = venue_loader.load_venue("NeurIPS")
    assert chi.tone.hedging == "high"
    assert neurips.tone.hedging == "moderate"


def test_load_all_venues_keys_are_venue_ids(venue_loader):
    venues = venue_loader.load_all_venues()
    for k, v in venues.items():
        assert k == v.id, f"key {k} doesn't match venue.id {v.id}"


def test_invalid_yaml_raises(venue_loader, tmp_path: Path):
    bad = {
        "schema_version": "v1",
        "id": "BOGUS",
        "name": "Bogus venue",
        "kind": "not-a-real-kind",  # invalid enum
        "domain": "cs-ml",
    }
    with pytest.raises(venue_loader.VenueValidationError, match="kind"):
        venue_loader.venue_from_dict(bad, source="bogus.yaml")


def test_invalid_anonymization_enum_rejected(venue_loader):
    bad = {
        "schema_version": "v1",
        "id": "X",
        "name": "X",
        "kind": "conference",
        "domain": "cs-ml",
        "submission": {"anonymization": "sometimes"},
    }
    with pytest.raises(venue_loader.VenueValidationError, match="anonymization"):
        venue_loader.venue_from_dict(bad, source="bad.yaml")


def test_invalid_citation_style_rejected(venue_loader):
    bad = {
        "schema_version": "v1",
        "id": "X",
        "name": "X",
        "kind": "conference",
        "domain": "cs-ml",
        "format": {"citation_style": "fancy-numeric"},
    }
    with pytest.raises(venue_loader.VenueValidationError, match="citation_style"):
        venue_loader.venue_from_dict(bad, source="bad.yaml")


def test_inherits_from_only_allowed_for_proposal(venue_loader):
    """A conference venue with inherits_from should be rejected."""
    bad = {
        "schema_version": "v1",
        "id": "X",
        "name": "X",
        "kind": "conference",
        "domain": "cs-ml",
        "inherits_from": "SomeBase",
    }
    with pytest.raises(venue_loader.VenueValidationError, match="inherits_from"):
        venue_loader.venue_from_dict(bad, source="bad.yaml")


def test_schema_version_required_to_match(venue_loader):
    bad = {
        "schema_version": "v2",  # future version
        "id": "X",
        "name": "X",
        "kind": "conference",
        "domain": "cs-ml",
    }
    with pytest.raises(venue_loader.VenueValidationError, match="schema_version"):
        venue_loader.venue_from_dict(bad, source="bad.yaml")


def test_merge_inheritance_child_overrides_base(venue_loader):
    """Child's set fields win over base; unset child fields inherit base."""
    base_dict = {
        "schema_version": "v1",
        "id": "BASE",
        "name": "Base",
        "kind": "proposal",
        "domain": "proposal",
        "submission": {"page_limit_main": 15, "has_required_checklist": True},
        "tone": {"hedging": "low"},
    }
    child_dict = {
        "schema_version": "v1",
        "id": "CHILD",
        "name": "Child solicitation",
        "kind": "proposal",
        "domain": "proposal",
        "submission": {"page_limit_main": 10},  # override page limit only
    }
    base = venue_loader.venue_from_dict(base_dict, source="base")
    child = venue_loader.venue_from_dict(child_dict, source="child")
    merged = venue_loader.merge_inheritance(child=child, base=base)
    # Child's override wins.
    assert merged.submission.page_limit_main == 10
    # Base's has_required_checklist preserved (child didn't override).
    assert merged.submission.has_required_checklist is True
    # Base's tone.hedging preserved (child didn't override).
    assert merged.tone.hedging == "low"


def test_validate_cli_command_returns_zero_on_clean(venue_loader, monkeypatch, capsys):
    """`venue_loader.py validate` exits 0 when all venues are clean."""

    class _NS:
        venue_id = None
        strict = False

    rc = venue_loader._cmd_validate(_NS())
    out = capsys.readouterr().out + capsys.readouterr().err
    assert rc == 0
