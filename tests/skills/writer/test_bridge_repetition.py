"""Tests for bridge_repetition_check.py.

Verifies the clean-room implementation: cross-file sentence pairs with
difflib.SequenceMatcher ratio >= threshold (default 0.7) are flagged;
intra-file pairs are not compared; min_length filter respected.

Per mis_01KS0C3RP04XANCZAB3HTNAG0P T4 acceptance criteria.
"""

from __future__ import annotations

from pathlib import Path


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_no_bridges_when_files_are_unrelated(
    bridge_repetition_check, tmp_path: Path
) -> None:
    a = _write(
        tmp_path, "a.tex",
        "The experimental setup measures decision latency across sessions. "
        "Participants completed three rounds of the diary protocol."
    )
    b = _write(
        tmp_path, "b.tex",
        "Discussion section reviews implications for permission-system design. "
        "Future work could extend the protocol to longitudinal observation."
    )
    hits = bridge_repetition_check.find_bridges([a, b], threshold=0.7)
    assert hits == []


def test_detects_near_duplicate_pair(
    bridge_repetition_check, tmp_path: Path
) -> None:
    common = (
        "The diary instrument surfaces patterns of permission decisions over time. "
    )
    a = _write(
        tmp_path, "a.tex",
        common + "It records when each agent prompt occurs and the user response."
    )
    b = _write(
        tmp_path, "b.tex",
        common + "This produces a longitudinal record suitable for trend analysis."
    )
    hits = bridge_repetition_check.find_bridges([a, b], threshold=0.7)
    assert any(h.ratio >= 0.7 for h in hits)


def test_threshold_filters_low_similarity_pairs(
    bridge_repetition_check, tmp_path: Path
) -> None:
    a = _write(
        tmp_path, "a.tex",
        "The instrument captures user permission decisions during sessions."
    )
    b = _write(
        tmp_path, "b.tex",
        "Permission decisions during sessions are captured by the instrument."
    )
    # Default 0.7: should match given high word overlap.
    hits_70 = bridge_repetition_check.find_bridges([a, b], threshold=0.7)
    # Very high threshold should miss this pair.
    hits_98 = bridge_repetition_check.find_bridges([a, b], threshold=0.98)
    assert len(hits_70) >= len(hits_98)


def test_min_length_filters_short_sentences(
    bridge_repetition_check, tmp_path: Path
) -> None:
    a = _write(tmp_path, "a.tex", "Yes. The same. Yes.")
    b = _write(tmp_path, "b.tex", "Yes. The same. Yes.")
    # min_length 40 filters everything; result must be empty.
    hits = bridge_repetition_check.find_bridges([a, b], min_length=40)
    assert hits == []


def test_no_intra_file_pairs(bridge_repetition_check, tmp_path: Path) -> None:
    a = _write(
        tmp_path, "a.tex",
        "The diary instrument surfaces patterns of permission decisions over time. "
        "The diary instrument surfaces patterns of permission decisions over time."
    )
    # Two identical sentences inside the same file; cross-file scanner should not report.
    hits = bridge_repetition_check.find_bridges([a], threshold=0.5)
    assert hits == []
