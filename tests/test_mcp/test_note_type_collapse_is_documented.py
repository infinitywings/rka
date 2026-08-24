"""The note-type enum must say that nine of its twelve values collapse.

`note`, `log` and `directive` are the only stored journal types. The other
nine are legacy aliases, normalized on write by `JOURNAL_TYPE_MAP` — sending
`finding` stores `note`.

That is deliberate and the source says so, but the comment lives in
`_enums.py` and never reaches the wire. What an agent sees is the JSON Schema:
twelve enum values and, until now, the description "Journal entry type." So an
agent picks `finding`, gets `note` back, and has nothing to reconcile the two
with.

That cost is not hypothetical. A Brain agent working a real session reported
this as a defect, having reproduced it twice — effort spent, and a false bug
report, because the surface asserted a choice the system does not offer.
"""

from __future__ import annotations

import pytest

from rka.models.journal import JOURNAL_TYPE_MAP, normalize_journal_type
from rka.mcp.operation_args import IngestDocumentArgs, RecordNoteArgs, UpdateNoteArgs

CANONICAL = {"note", "log", "directive"}
ALIASES = sorted(set(JOURNAL_TYPE_MAP) - CANONICAL)


def _description(model, field: str) -> str:
    return model.model_fields[field].description or ""


class TestTheCollapseIsRealAndDeliberate:
    @pytest.mark.parametrize("alias", ALIASES)
    def test_every_alias_normalizes_to_a_canonical_type(self, alias):
        assert normalize_journal_type(alias) in CANONICAL

    @pytest.mark.parametrize("canonical", sorted(CANONICAL))
    def test_canonical_types_are_left_alone(self, canonical):
        assert normalize_journal_type(canonical) == canonical

    def test_there_really_are_nine_aliases(self):
        """Pins the count the descriptions quote."""
        assert len(ALIASES) == 9


class TestTheSurfaceSaysSo:
    """These descriptions are what reaches the agent as `inputSchema`."""

    @pytest.mark.parametrize(
        "model,field",
        [
            (RecordNoteArgs, "type"),
            (UpdateNoteArgs, "type"),
            (IngestDocumentArgs, "default_type"),
        ],
    )
    def test_the_description_names_the_canonical_set(self, model, field):
        description = _description(model, field)
        for canonical in CANONICAL:
            assert canonical in description, (
                f"{model.__name__}.{field} offers twelve values without naming "
                f"the three that are stored"
            )

    @pytest.mark.parametrize(
        "model,field",
        [
            (RecordNoteArgs, "type"),
            (UpdateNoteArgs, "type"),
            (IngestDocumentArgs, "default_type"),
        ],
    )
    def test_the_description_says_the_rest_are_rewritten(self, model, field):
        description = _description(model, field).lower()
        assert "normaliz" in description, (
            f"{model.__name__}.{field} must say the other values are rewritten "
            f"on write, not merely that they are accepted"
        )

    def test_ingest_document_flags_that_its_own_default_is_an_alias(self):
        """`default_type` defaults to `finding`, which is stored as `note`."""
        field = IngestDocumentArgs.model_fields["default_type"]
        assert field.default == "finding"
        assert normalize_journal_type(field.default) == "note"
        assert "legacy alias" in (field.description or "").lower(), (
            "a default that is silently rewritten must say so at the default"
        )
