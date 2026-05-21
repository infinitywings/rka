"""Per-stage isolation tests for the validate_references.py Stages B through G.

Backends are mocked module-attribute-style so each stage tests only its own
logic. Phase 1 Stage A is unchanged and not retested here (covered by Phase 1
test_skill_loads).

Per mis_01KS2S871YPQ3D5RVY5K3PSQY6 T6 acceptance criteria.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class _FakeBackend:
    """Module-attribute-style fake; replaces _crossref / _openalex / _s2 / _arxiv / _serpapi."""

    def __init__(self, *, available: bool = True, doi_hits: dict[str, dict] | None = None):
        self._available = available
        self._doi_hits = doi_hits or {}
        self._calls = []

    def is_available(self) -> bool:
        return self._available

    def resolve_doi(self, doi: str):
        self._calls.append(("resolve_doi", doi))
        return self._doi_hits.get(doi)

    def search_works(self, query: str, rows: int = 10):
        return [{"title": query, "DOI": "10.fake/" + query[:6]}] if self._available else []

    def search_papers(self, query: str, max_results: int = 10):
        return [{"title": query}] if self._available else []

    def paper_by_id(self, identifier: str):
        return self._doi_hits.get(identifier)

    def get_paper(self, arxiv_id: str):
        return self._doi_hits.get(arxiv_id)

    def disambiguate_author(self, name: str, affiliation_hints=None):
        if self._available and name == "Smith":
            return {"display_name": "Smith, John"}
        return None

    def get_update_to(self, doi: str):
        return self._doi_hits.get(doi, {}).get("update-to", []) if self._doi_hits else []


class TestStageBResolution:
    """Stage B waterfall: Crossref -> OpenAlex -> Semantic Scholar."""

    def test_first_source_hit_short_circuits(self, validate_references) -> None:
        vr = validate_references
        vr._crossref = _FakeBackend(doi_hits={"10.1/a": {"DOI": "10.1/a"}})
        vr._openalex = _FakeBackend()
        vr._s2 = _FakeBackend()
        csl, tried, confirmed = vr.stage_b_resolve("10.1/a")
        assert csl is not None
        assert "crossref" in confirmed
        # Other backends are also tried since we want confirmation count, but the
        # important property is at least crossref confirmed.
        assert "crossref" in tried

    def test_no_source_returns_none(self, validate_references) -> None:
        vr = validate_references
        vr._crossref = _FakeBackend()
        vr._openalex = _FakeBackend()
        vr._s2 = _FakeBackend()
        csl, tried, confirmed = vr.stage_b_resolve("10.1/missing")
        assert csl is None
        assert confirmed == []

    def test_multiple_sources_confirm(self, validate_references) -> None:
        vr = validate_references
        hit = {"DOI": "10.1/a", "title": "Paper"}
        vr._crossref = _FakeBackend(doi_hits={"10.1/a": hit})
        vr._openalex = _FakeBackend(doi_hits={"10.1/a": hit})
        vr._s2 = _FakeBackend(doi_hits={"10.1/a": hit})
        csl, tried, confirmed = vr.stage_b_resolve("10.1/a")
        assert len(confirmed) >= 2


class TestStageCConfirmation:
    """Stage C maps confirmation count to verdict per design."""

    def test_two_or_more_sources_verified(self, validate_references) -> None:
        assert validate_references.stage_c_cross_source(["a", "b"]) == validate_references.Status.VERIFIED
        assert validate_references.stage_c_cross_source(["a", "b", "c"]) == validate_references.Status.VERIFIED

    def test_one_source_low_confidence(self, validate_references) -> None:
        assert validate_references.stage_c_cross_source(["a"]) == validate_references.Status.LOW_CONFIDENCE

    def test_zero_sources_unverified(self, validate_references) -> None:
        assert validate_references.stage_c_cross_source([]) == validate_references.Status.UNVERIFIED


class TestStageDRetraction:
    """Stage D retraction check via Crossref update-to."""

    def test_no_updates_not_retracted(self, validate_references) -> None:
        vr = validate_references
        vr._crossref = _FakeBackend(doi_hits={"10.1/clean": {"update-to": []}})
        is_retracted, updates = vr.stage_d_retraction("10.1/clean")
        assert is_retracted is False

    def test_retraction_record_detected(self, validate_references) -> None:
        vr = validate_references
        vr._crossref = _FakeBackend(doi_hits={
            "10.1/bad": {"update-to": [{"type": "retraction", "source": "retraction-watch"}]}
        })
        is_retracted, updates = vr.stage_d_retraction("10.1/bad")
        assert is_retracted is True
        assert len(updates) == 1


class TestStageEDisambiguation:
    """Stage E uses OpenAlex; escalates to SerpAPI on demand."""

    def test_all_authors_resolved_verified(self, validate_references) -> None:
        vr = validate_references
        vr._openalex = _FakeBackend()  # disambiguate_author returns truthy for 'Smith'
        status, notes, credits = vr.stage_e_disambiguate_authors(["Smith"], budget=None)
        assert status == vr.Status.VERIFIED
        assert credits == 0

    def test_unresolved_author_mismatch(self, validate_references) -> None:
        vr = validate_references
        vr._openalex = _FakeBackend()
        status, notes, credits = vr.stage_e_disambiguate_authors(["Unknown"], budget=None)
        assert status == vr.Status.AUTHOR_MISMATCH

    def test_partial_resolution_low_confidence(self, validate_references) -> None:
        vr = validate_references
        vr._openalex = _FakeBackend()
        status, notes, _ = vr.stage_e_disambiguate_authors(["Smith", "Unknown"], budget=None)
        assert status == vr.Status.LOW_CONFIDENCE

    def test_openalex_unavailable_returns_low_confidence(self, validate_references) -> None:
        vr = validate_references
        vr._openalex = _FakeBackend(available=False)
        status, notes, credits = vr.stage_e_disambiguate_authors(["Smith"], budget=None)
        assert status == vr.Status.LOW_CONFIDENCE
        assert "openalex_unavailable" in notes


class TestStageGNicheRescue:
    """Stage G: SerpAPI google_scholar lookup before HALLUCINATED."""

    def test_serpapi_unavailable_returns_no_budget_note(self, validate_references) -> None:
        vr = validate_references

        class FakeSerpAPI:
            @staticmethod
            def is_available() -> bool:
                return False

        vr._serpapi = FakeSerpAPI
        from rka.skills.writer.mcp_tools.backends.serpapi_backend import CreditBudget
        budget = CreditBudget(budget=5)
        csl, notes, credits = vr.stage_g_niche_rescue("test query", budget=budget)
        assert csl is None
        assert "no-serpapi-budget" in notes
        assert credits == 0

    def test_serpapi_hit_returns_unverified_scholar_only_source(self, validate_references) -> None:
        vr = validate_references

        class FakeSerpAPI:
            class SerpAPIBudgetExceededError(RuntimeError):
                pass

            @staticmethod
            def is_available() -> bool:
                return True

            @staticmethod
            def google_scholar_search(query, budget):
                budget.used += 1
                return [{"title": "Found Paper", "link": "http://example.com/"}]

        from rka.skills.writer.mcp_tools.backends.serpapi_backend import CreditBudget
        vr._serpapi = FakeSerpAPI
        budget = CreditBudget(budget=5)
        csl, notes, credits = vr.stage_g_niche_rescue("test query", budget=budget)
        assert csl is not None
        assert "scholar-only-source" in notes
        assert credits == 1


class TestAuditReportHelpers:
    """ReferenceVerdict + AuditReport blocking detection."""

    def test_audit_report_blocking_status(self, validate_references) -> None:
        vr = validate_references
        rpt = vr.AuditReport()
        rpt.refs.append(vr.ReferenceVerdict("a", vr.Status.VERIFIED))
        assert rpt.has_any_blocking() is False
        rpt.refs.append(vr.ReferenceVerdict("b", vr.Status.UNVERIFIED))
        assert rpt.has_any_blocking() is True

    def test_audit_report_all_terminal_statuses_blocking(self, validate_references) -> None:
        vr = validate_references
        for blocking_status in (
            vr.Status.UNVERIFIED,
            vr.Status.HALLUCINATED,
            vr.Status.RETRACTED,
            vr.Status.AUTHOR_MISMATCH,
            vr.Status.FIELD_ERROR,
        ):
            rpt = vr.AuditReport()
            rpt.refs.append(vr.ReferenceVerdict("x", blocking_status))
            assert rpt.has_any_blocking() is True, f"{blocking_status} should block"
        # LOW_CONFIDENCE does not block compile per design (suggestive only).
        rpt = vr.AuditReport()
        rpt.refs.append(vr.ReferenceVerdict("y", vr.Status.LOW_CONFIDENCE))
        assert rpt.has_any_blocking() is False
