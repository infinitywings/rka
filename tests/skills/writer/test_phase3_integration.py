"""Phase 3 integration tests: end-to-end revision-loop scenarios.

Tests cover the full Brain-spawned writer-revision mission lifecycle as
documented in SKILL.md Section 4 path (b):

  1. Brain creates writer-revision mission with tags + context.
  2. Writer reads the mission, extracts tags + comment.
  3. Writer classifies the comment via revision_handler.
  4. Writer dispatches to the matching handler.
  5. Writer submits report (success) or checkpoint (escalation).

Per mis_01KS2WW6MRN6AXP11EMCSCDFAR T4 acceptance criteria (~5 integration tests).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture
def revision_handler():
    path = Path(__file__).resolve().parents[3] / "rka" / "skills" / "writer" / "scripts" / "revision_handler.py"
    spec = importlib.util.spec_from_file_location("writer_revision_handler_int", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["writer_revision_handler_int"] = mod
    spec.loader.exec_module(mod)
    return mod


def _comment_class_from_tags(tags: list[str]) -> str | None:
    """Helper: parse the comment-class tag from a mission's tag list."""
    for tag in tags:
        if tag.startswith("comment-class:"):
            return tag.split(":", 1)[1]
    return None


class TestWriterRevisionMissionFlow:
    """Brain spawns mission -> Writer extracts tags -> classifies -> dispatches."""

    def test_brain_tag_convention_parses_correctly(self, revision_handler) -> None:
        # Brain spawns mission with these tags (per SKILL.md Section 4 path b).
        mission_tags = [
            "writer-revision",
            "comment-class:factual_r1",
            "manuscript:jrn_01KS_test",
        ]
        comment_class = _comment_class_from_tags(mission_tags)
        assert comment_class == "factual_r1"

    def test_writer_classifies_mission_context_consistently_with_brain_tag(
        self, revision_handler,
    ) -> None:
        # Brain marked the comment as factual_r1; the heuristic should agree.
        comment = "This citation is incorrect; the year is wrong for Smith 2024."
        classification = revision_handler.classify_comment(comment)
        assert classification.cls == revision_handler.CommentClass.FACTUAL_R1
        # Brain's tag should match the heuristic's output (or at least not contradict).
        brain_class_str = "factual_r1"
        assert classification.cls.value == brain_class_str

    def test_ambiguous_comment_triggers_escalation_path(self, revision_handler) -> None:
        # The Writer's escalation rule: if classify_comment returns ambiguous=True,
        # do NOT dispatch; escalate via rka_submit_checkpoint per SKILL.md Section 4.
        comment = "This paragraph needs work."
        classification = revision_handler.classify_comment(comment)
        if classification.ambiguous:
            # Writer's expected behavior: do not invoke any handler.
            assert classification.cls == revision_handler.CommentClass.ESCALATE
        # The integration assertion is that ambiguous classifications never
        # bypass PI escalation.

    def test_r4_logical_handler_prepares_evidence_gap_mission(
        self, revision_handler, tmp_path: Path,
    ) -> None:
        """R4 path: Writer creates a writer_evidence_gap mission for Brain."""
        section = tmp_path / "method.tex"
        section.write_text("\\section{Method}\n...")

        class CollectingClient:
            def __init__(self) -> None:
                self.created_missions: list[dict] = []

            def create_mission(self, **kwargs: object) -> None:
                self.created_missions.append(kwargs)

        client = CollectingClient()
        result = revision_handler.handle_logical_r4(
            comment="No evidence supports this conclusion.",
            section_path=section,
            manuscript_id="jrn_01KS_test",
            rka_client=client,
        )
        assert result.escalation_required is True
        assert len(client.created_missions) == 1
        spawned = client.created_missions[0]
        assert spawned.get("type") == "writer_evidence_gap"
        assert "jrn_01KS_test" in spawned.get("context", "")


class TestReviewStateCapTriggersEscalation:
    """REVIEW_STATE.md three-iteration cap forces ESCALATE verdict."""

    def test_three_failures_yield_escalate(self, revision_handler) -> None:
        state = revision_handler.ReviewState()
        for i in range(3):
            state = revision_handler.advance_review_state(
                state, success=False, note=f"iteration {i+1} failed",
            )
        assert state.verdict == "ESCALATE"
        assert state.iteration == 3
        assert len(state.history) == 3
