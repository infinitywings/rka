"""Contract tests for the choice-first framing and spine interview."""

from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
WRITER_DIR = REPO_ROOT / "rka" / "skills" / "writer"
REFERENCE = WRITER_DIR / "references" / "framing_elicitation.md"
SESSION_TEMPLATE = (
    WRITER_DIR
    / "workspace-template"
    / ".planning"
    / "FRAMING_SESSION.yaml"
)


def test_choice_first_contract_is_explicit() -> None:
    text = REFERENCE.read_text(encoding="utf-8")

    required = [
        "Ask one decision per turn.",
        "Offer two to four evidence-bounded options.",
        "`single-select` or `multi-select`",
        "concrete pros",
        "concrete cons",
        "Mark one option `Recommended`",
        "Use the host's structured choice UI when available.",
        "Revise or combine these options",
        "Defer and gather evidence",
    ]
    for phrase in required:
        assert phrase in text


def test_elicitation_covers_framing_spine_and_disagreement() -> None:
    text = REFERENCE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    for round_id in range(10):
        assert f"### F{round_id}." in text
    assert "Author voice" in text
    assert "Researcher judgment" in text
    assert "PI authority" in text
    assert "do not silently average" in normalized.lower()
    assert "not evidence, a PI decision, or a substitute" in normalized


def test_framing_session_template_is_advisory_and_resumable() -> None:
    data = yaml.safe_load(SESSION_TEMPLATE.read_text(encoding="utf-8"))

    assert data["schema"] == "rka-framing-session/v1"
    assert data["status"] == "not_started"
    assert data["participants"] == []
    assert data["rounds"] == []
    assert data["candidate_spines"] == []
    assert data["selected_spine"] is None
    assert data["unresolved_questions"] == []
    assert data["rka_decision_links"] == []
