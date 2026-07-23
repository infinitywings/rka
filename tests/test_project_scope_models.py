"""Response-model contract for server-attested project scope."""

from rka.models.decision import Decision
from rka.models.journal import JournalEntry


def test_journal_entry_serializes_project_id() -> None:
    entry = JournalEntry(
        id="jrn_scope_test",
        project_id="proj_alpha",
        type="note",
        content="Scoped evidence.",
        source="executor",
        confidence="tested",
        importance="normal",
    )

    assert entry.model_dump()["project_id"] == "proj_alpha"


def test_decision_serializes_project_id() -> None:
    decision = Decision(
        id="dec_scope_test",
        project_id="proj_alpha",
        phase="planning",
        question="Which scoped claim should be used?",
        decided_by="pi",
        status="active",
    )

    assert decision.model_dump()["project_id"] == "proj_alpha"
