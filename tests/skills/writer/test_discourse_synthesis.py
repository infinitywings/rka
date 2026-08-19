"""Contracts that keep RKA provenance from becoming record-shaped prose."""

from __future__ import annotations

from pathlib import Path


def _squash(text: str) -> str:
    return " ".join(text.split())


def test_skill_exposes_evidence_to_discourse_separation(
    skill_dir: Path, skill_md_path: Path
) -> None:
    skill_text = skill_md_path.read_text(encoding="utf-8")
    discourse_path = skill_dir / "references" / "discourse_synthesis.md"
    discourse = discourse_path.read_text(encoding="utf-8")

    assert "Discourse Law" in skill_text
    assert "references/discourse_synthesis.md" in skill_text
    assert "Evidence graph and discourse graph" in discourse
    assert "The mapping is many-to-many" in discourse
    assert "Never traverse journal entries" in discourse
    assert "one paragraph per claim" in discourse


def test_pipeline_does_not_map_units_directly_to_paragraphs(skill_dir: Path) -> None:
    pipeline = (
        skill_dir / "references" / "evidence_to_spine_pipeline.md"
    ).read_text(encoding="utf-8")
    pipeline_flat = _squash(pipeline)

    assert "section-level discourse plan" in pipeline
    assert "do not preserve record order" in pipeline_flat.lower()
    assert "Paragraph boundaries follow rhetorical continuity" in pipeline_flat
    assert "Do not fragment coherent prose" in pipeline_flat


def test_section_drafter_runs_coherence_before_surface_lint(skill_dir: Path) -> None:
    workflows = (skill_dir / "references" / "workflows.md").read_text(
        encoding="utf-8"
    )
    section = workflows[workflows.index("### 5. Section drafter") :]
    coherence = section.index("Run the discourse-synthesis coherence review")
    provenance = section.index(
        "attaches hidden provenance comments and citations post-hoc"
    )
    lint = section.index("scripts/ai_tic_lint.py")

    assert coherence < provenance < lint
    assert "groups duplicate or closely related records into evidence bundles" in (
        _squash(section)
    )
    assert "Several RKA records or native units may serve one paragraph" in (
        _squash(section)
    )
    assert "attaches hidden provenance comments and citations post-hoc" in (
        _squash(section)
    )
    assert "The score cannot establish logic or fluency" in section
    assert "Any prose change" in section
    assert "validate_discourse_artifacts.py" in section


def test_plain_academic_profile_is_positive_and_sample_calibratable(
    skill_dir: Path,
) -> None:
    discourse = (
        skill_dir / "references" / "discourse_synthesis.md"
    ).read_text(encoding="utf-8")

    assert "Plain academic target" in discourse
    assert "Calibrating to author samples" in discourse
    assert "logic ladder" in discourse
    assert "concrete problem, consequence, or observation" in discourse
    assert "do not copy sentences" in discourse.lower()
    assert "Do not imitate grammar errors" in discourse
    assert ".planning/STYLE_PROFILE.yaml" in discourse
    assert "status: approved" in discourse


def test_security_sections_and_contrastive_example_are_actionable(
    skill_dir: Path,
) -> None:
    discourse = (
        skill_dir / "references" / "discourse_synthesis.md"
    ).read_text(encoding="utf-8")

    assert "**Related work**" in discourse
    assert "**Threat model or security assumptions**" in discourse
    assert "diagnostic patterns, not fill-in templates" in discourse
    assert "Synthetic contrastive example" in discourse
    assert "Record-shaped:" in discourse
    assert "Synthesized:" in discourse
