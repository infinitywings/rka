"""Tests for v2 journal type mapping and model changes."""

from __future__ import annotations

import pytest
from rka.models.journal import (
    JournalEntryCreate, JournalEntryUpdate,
    normalize_journal_type, JOURNAL_TYPE_MAP,
)


class TestNormalizeJournalType:
    """Test the type normalization function."""

    def test_v2_types_pass_through(self):
        assert normalize_journal_type("note") == "note"
        assert normalize_journal_type("log") == "log"
        assert normalize_journal_type("directive") == "directive"

    def test_legacy_types_mapped(self):
        assert normalize_journal_type("finding") == "note"
        assert normalize_journal_type("insight") == "note"
        assert normalize_journal_type("idea") == "note"
        assert normalize_journal_type("observation") == "note"
        assert normalize_journal_type("exploration") == "note"
        assert normalize_journal_type("hypothesis") == "note"
        assert normalize_journal_type("summary") == "note"
        assert normalize_journal_type("methodology") == "log"
        assert normalize_journal_type("pi_instruction") == "directive"

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown journal type"):
            normalize_journal_type("nonexistent")

    def test_all_map_entries_are_valid(self):
        valid_v2 = {"note", "log", "directive"}
        for old_type, new_type in JOURNAL_TYPE_MAP.items():
            assert new_type in valid_v2, f"{old_type} maps to invalid {new_type}"


class TestJournalEntryCreate:
    """Test the JournalEntryCreate model with type normalization."""

    def test_default_type_is_note(self):
        entry = JournalEntryCreate(content="test")
        assert entry.type == "note"

    def test_legacy_type_auto_mapped(self):
        entry = JournalEntryCreate(content="test", type="finding")
        assert entry.type == "note"

    def test_methodology_maps_to_log(self):
        entry = JournalEntryCreate(content="test", type="methodology")
        assert entry.type == "log"

    def test_pi_instruction_maps_to_directive(self):
        entry = JournalEntryCreate(content="test", type="pi_instruction")
        assert entry.type == "directive"

    def test_v2_type_accepted(self):
        entry = JournalEntryCreate(content="test", type="log")
        assert entry.type == "log"

    def test_has_status_field(self):
        entry = JournalEntryCreate(content="test")
        assert entry.status == "active"

    def test_has_pinned_field(self):
        entry = JournalEntryCreate(content="test")
        assert entry.pinned is False

    def test_status_draft(self):
        entry = JournalEntryCreate(content="test", status="draft")
        assert entry.status == "draft"


class TestJournalEntryUpdate:
    """Test the JournalEntryUpdate model."""

    def test_type_normalized_on_update(self):
        update = JournalEntryUpdate(type="finding")
        assert update.type == "note"

    def test_none_type_stays_none(self):
        update = JournalEntryUpdate(content="new content")
        assert update.type is None

    def test_status_field(self):
        update = JournalEntryUpdate(status="retracted")
        assert update.status == "retracted"

    def test_pinned_field(self):
        update = JournalEntryUpdate(pinned=True)
        assert update.pinned is True
