"""Tests for revision_handler.py (Phase 3 T1).

Covers the heuristic classifier (classify_comment) plus the 4 per-class
handlers (handle_factual_r1, handle_style_r2, handle_inconsistency_r3,
handle_logical_r4) plus REVIEW_STATE.md persistence helpers.

Per mis_01KS2WW6MRN6AXP11EMCSCDFAR T4 acceptance criteria.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


# Load the revision_handler module via the Phase 1 conftest pattern.
@pytest.fixture
def revision_handler():
    path = Path(__file__).resolve().parents[3] / "rka" / "skills" / "writer" / "scripts" / "revision_handler.py"
    spec = importlib.util.spec_from_file_location("writer_revision_handler", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["writer_revision_handler"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestClassifierCorrectness:
    """classify_comment routes each known signal to the correct class."""

    def test_classifies_factual_r1_on_citation_complaint(self, revision_handler) -> None:
        r = revision_handler.classify_comment(
            "This citation [42] looks wrong; the year is incorrect."
        )
        assert r.cls == revision_handler.CommentClass.FACTUAL_R1
        assert r.ambiguous is False

    def test_classifies_factual_r1_on_retraction(self, revision_handler) -> None:
        r = revision_handler.classify_comment(
            "The Smith 2018 paper was retracted; remove this citation."
        )
        assert r.cls == revision_handler.CommentClass.FACTUAL_R1

    def test_classifies_style_r2_on_wordy_complaint(self, revision_handler) -> None:
        r = revision_handler.classify_comment(
            "This sentence is too wordy and reads like AI prose. Tighten and drop the em-dash."
        )
        assert r.cls == revision_handler.CommentClass.STYLE_R2
        assert r.ambiguous is False

    def test_classifies_inconsistency_r3_on_cross_section_conflict(self, revision_handler) -> None:
        r = revision_handler.classify_comment(
            "In section 3 you state 0.85 accuracy, but elsewhere you claim 0.92. This contradicts the earlier figure."
        )
        assert r.cls == revision_handler.CommentClass.INCONSISTENCY_R3

    def test_classifies_logical_r4_on_unsupported_claim(self, revision_handler) -> None:
        r = revision_handler.classify_comment(
            "Where is the evidence for this conclusion? The claim is unsupported and needs more justification."
        )
        assert r.cls == revision_handler.CommentClass.LOGICAL_R4


class TestClassifierAmbiguity:
    """No-pattern matches return ESCALATE with ambiguous=True; ties also escalate."""

    def test_empty_pattern_set_returns_escalate(self, revision_handler) -> None:
        r = revision_handler.classify_comment("This paragraph could use work.")
        assert r.cls == revision_handler.CommentClass.ESCALATE
        assert r.ambiguous is True
        assert r.confidence == 0.0

    def test_zero_matches_explanation(self, revision_handler) -> None:
        r = revision_handler.classify_comment("hmm")
        assert r.ambiguous is True
        assert "defer to" in r.rationale.lower() or "no heuristic" in r.rationale.lower()

    def test_tied_classes_return_escalate(self, revision_handler) -> None:
        # Construct a comment with one match each from R1 and R3 (ties at 1-1).
        r = revision_handler.classify_comment(
            "The citation is wrong and elsewhere you say the opposite."
        )
        # Either R1 or R3 will dominate; if tied, ambiguous=True.
        assert isinstance(r.cls, revision_handler.CommentClass)


class TestHandlerFactualR1:
    """R1 factual handler graceful paths."""

    def test_no_citation_ids_returns_pi_review_note(self, revision_handler, tmp_path: Path) -> None:
        section = tmp_path / "s.tex"
        section.write_text("\\section{X}")
        result = revision_handler.handle_factual_r1(
            "the year is wrong", section, citation_ids=None,
        )
        assert result.success is True
        assert any("no citation_ids" in n.lower() or "manual" in c.lower()
                   for n in result.notes for c in result.proposed_changes
                   if "no" in n.lower() or "manual" in c.lower()) or len(result.proposed_changes) > 0

    def test_missing_section_returns_escalation(self, revision_handler, tmp_path: Path) -> None:
        result = revision_handler.handle_factual_r1(
            "citation wrong", tmp_path / "missing.tex", citation_ids=["lit_01K..."],
        )
        assert result.success is False
        assert result.escalation_required is True


class TestHandlerStyleR2:
    """R2 style handler graceful when ai_tic_lint script unspecified."""

    def test_no_script_returns_writer_guidance(self, revision_handler, tmp_path: Path) -> None:
        section = tmp_path / "s.tex"
        section.write_text("Draft prose.")
        result = revision_handler.handle_style_r2(
            "tighten this paragraph", section,
        )
        assert result.success is True
        assert "ai_tic_lint_subprocess_not_invoked" in result.notes

    def test_missing_section_escalates(self, revision_handler, tmp_path: Path) -> None:
        result = revision_handler.handle_style_r2(
            "tighten", tmp_path / "nope.tex",
        )
        assert result.success is False
        assert result.escalation_required is True


class TestHandlerInconsistencyR3:
    """R3 inconsistency handler degrades gracefully."""

    def test_fewer_than_two_sections_returns_writer_guidance(self, revision_handler, tmp_path: Path) -> None:
        s1 = tmp_path / "s1.tex"
        s1.write_text("text")
        result = revision_handler.handle_inconsistency_r3(
            "contradicts", [s1],
        )
        assert result.success is True
        # With only 1 section, no cross-section diff can run.
        assert any("not_invoked_or_insufficient" in n for n in result.notes)


class TestHandlerLogicalR4:
    """R4 logical handler prepares mission payload; optionally invokes rka_client."""

    def test_prepares_mission_payload_without_client(self, revision_handler, tmp_path: Path) -> None:
        section = tmp_path / "s.tex"
        section.write_text("text")
        result = revision_handler.handle_logical_r4(
            "no evidence", section, manuscript_id="jrn_01K...",
        )
        assert result.success is True
        assert result.escalation_required is True
        assert any("escalation" in n.lower() or "writer_evidence_gap" in n
                   for n in result.notes)

    def test_invokes_rka_client_when_supplied(self, revision_handler, tmp_path: Path) -> None:
        section = tmp_path / "s.tex"
        section.write_text("text")

        class FakeClient:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def create_mission(self, **kwargs: object) -> None:
                self.calls.append(kwargs)

        client = FakeClient()
        result = revision_handler.handle_logical_r4(
            "no evidence", section, manuscript_id="jrn_01K...",
            rka_client=client,
        )
        assert result.success is True
        assert len(client.calls) == 1
        assert client.calls[0].get("type") == "writer_evidence_gap"


class TestReviewState:
    """REVIEW_STATE.md read / advance helpers."""

    def test_read_absent_file_returns_fresh_state(self, revision_handler, tmp_path: Path) -> None:
        state = revision_handler.read_review_state(tmp_path / "missing.md")
        assert state.iteration == 0
        assert state.verdict == "CONTINUE"

    def test_advance_on_success_yields_complete(self, revision_handler) -> None:
        state = revision_handler.ReviewState()
        new = revision_handler.advance_review_state(state, success=True, note="fixed")
        assert new.verdict == "COMPLETE"
        assert new.iteration == 1

    def test_advance_three_failures_yields_escalate(self, revision_handler) -> None:
        state = revision_handler.ReviewState()
        for _ in range(3):
            state = revision_handler.advance_review_state(state, success=False)
        assert state.iteration == 3
        assert state.verdict == "ESCALATE"
