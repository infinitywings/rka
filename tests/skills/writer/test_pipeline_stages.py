"""Per-stage isolation tests for the validate_references.py Stages B through G.

Backends are mocked module-attribute-style so each stage tests only its own
logic. Phase 1 Stage A is unchanged and not retested here (covered by Phase 1
test_skill_loads).

Per mis_01KS2S871YPQ3D5RVY5K3PSQY6 T6 acceptance criteria.
"""

from __future__ import annotations

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

    def test_enabled_retraction_backend_unavailable_blocks(
        self,
        validate_references,
    ) -> None:
        vr = validate_references
        hit = {"DOI": "10.1/a", "title": "Paper"}
        vr._crossref = _FakeBackend(available=False, doi_hits={"10.1/a": hit})
        vr._openalex = _FakeBackend(doi_hits={"10.1/a": hit})
        vr._s2 = _FakeBackend(doi_hits={"10.1/a": hit})

        verdict = vr.validate_reference(doi="10.1/a", check_retraction=True)

        assert verdict.status == vr.Status.FIELD_ERROR
        assert verdict.stage_trace["D_retraction"] == {
            "enabled": True,
            "reached": True,
            "completed": False,
            "outcome": "unavailable",
        }
        assert "stage_d_retraction_backend_unavailable" in verdict.notes


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

    def test_pipeline_enables_conditional_serpapi_fallback(
        self,
        validate_references,
        monkeypatch,
    ) -> None:
        vr = validate_references
        hit = {"DOI": "10.1/a", "title": "Paper"}
        vr._crossref = _FakeBackend(doi_hits={"10.1/a": hit})
        vr._openalex = _FakeBackend(doi_hits={"10.1/a": hit})
        vr._s2 = _FakeBackend(doi_hits={"10.1/a": hit})
        observed: dict[str, bool] = {}

        def fake_disambiguate(
            authors,
            affiliation_hints=None,
            *,
            budget=None,
            escalate_to_serpapi=False,
        ):
            observed["enabled"] = escalate_to_serpapi
            return vr.Status.VERIFIED, [], 0

        monkeypatch.setattr(vr, "stage_e_disambiguate_authors", fake_disambiguate)
        verdict = vr.validate_reference(
            doi="10.1/a",
            authors=["Smith"],
            budget=object(),
            check_retraction=False,
            check_disambiguation=True,
        )

        assert verdict.status == vr.Status.VERIFIED
        assert observed == {"enabled": True}


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
            vr.Status.LOW_CONFIDENCE,
        ):
            rpt = vr.AuditReport()
            rpt.refs.append(vr.ReferenceVerdict("x", blocking_status))
            assert rpt.has_any_blocking() is True, f"{blocking_status} should block"


class TestNativeStageTrace:
    """Every reference carries a closed, truthful A-G execution trace."""

    def test_single_reference_trace_records_disabled_and_completed_stages(
        self,
        validate_references,
    ) -> None:
        vr = validate_references
        hit = {"DOI": "10.1/a", "title": "Paper"}
        vr._crossref = _FakeBackend(doi_hits={"10.1/a": hit})
        vr._openalex = _FakeBackend(doi_hits={"10.1/a": hit})
        vr._s2 = _FakeBackend()

        verdict = vr.validate_reference(
            doi="10.1/a",
            check_retraction=False,
            check_disambiguation=False,
        )

        assert set(verdict.stage_trace) == set(vr.STAGE_KEYS)
        for record in verdict.stage_trace.values():
            assert set(record) == {"enabled", "reached", "completed", "outcome"}
            assert isinstance(record["enabled"], bool)
            assert isinstance(record["reached"], bool)
            assert isinstance(record["completed"], bool)
            assert record["outcome"] in {outcome.value for outcome in vr.StageOutcome}
        assert verdict.stage_trace["A_extraction"] == {
            "enabled": True,
            "reached": True,
            "completed": True,
            "outcome": "passed",
        }
        assert verdict.stage_trace["C_cross_source_confirmation"]["outcome"] == "passed"
        assert verdict.stage_trace["D_retraction"]["outcome"] == "disabled"
        assert verdict.stage_trace["E_author_disambiguation"]["outcome"] == "disabled"
        assert verdict.stage_trace["F_bibliography_compile"]["outcome"] == "not_reached"

    def test_multi_reference_stage_f_does_not_hide_uncompiled_reference(
        self,
        validate_references,
        monkeypatch,
        tmp_path,
    ) -> None:
        vr = validate_references
        trace_one = vr._new_stage_trace(
            check_retraction=False,
            check_disambiguation=False,
        )
        trace_two = vr._new_stage_trace(
            check_retraction=False,
            check_disambiguation=False,
        )
        report = vr.AuditReport(refs=[
            vr.ReferenceVerdict(
                "10.1/a",
                vr.Status.VERIFIED,
                csl_json={"DOI": "10.1/a", "title": "Resolvable"},
                stage_trace=trace_one,
            ),
            vr.ReferenceVerdict(
                "Title only",
                vr.Status.VERIFIED,
                csl_json={"title": "Title only"},
                stage_trace=trace_two,
            ),
        ])

        def fake_compile(refs, out_bib):
            out_bib.write_text("@article{a}", encoding="utf-8")
            return 0, []

        monkeypatch.setattr(vr, "stage_f_compile_bibliography", fake_compile)
        exit_code, batch_trace = vr._apply_stage_f(report, tmp_path / "refs.bib")

        assert exit_code == 1
        assert batch_trace["outcome"] == "inconclusive"
        assert report.refs[0].stage_trace["F_bibliography_compile"]["outcome"] == "passed"
        assert report.refs[1].stage_trace["F_bibliography_compile"] == {
            "enabled": True,
            "reached": True,
            "completed": False,
            "outcome": "inconclusive",
        }
        assert "stage_f_reference_missing_resolvable_id" in report.refs[1].notes

    def test_batch_invalid_inputs_still_receive_complete_traces(
        self,
        validate_references,
    ) -> None:
        vr = validate_references
        report = vr.validate_all(
            [{}, "not-an-object"],
            budget=None,
            check_retraction=True,
            check_disambiguation=True,
        )
        assert len(report.refs) == 2
        assert all(set(verdict.stage_trace) == set(vr.STAGE_KEYS) for verdict in report.refs)
        assert all(verdict.status == vr.Status.FIELD_ERROR for verdict in report.refs)
        assert all(
            verdict.stage_trace["A_extraction"]["outcome"] == "rejected"
            for verdict in report.refs
        )

    def test_cli_audit_serializes_trace_for_every_reference(
        self,
        validate_references,
        tmp_path,
    ) -> None:
        import json

        vr = validate_references
        input_path = tmp_path / "refs.json"
        audit_path = tmp_path / "refs.audit.json"
        bib_path = tmp_path / "refs.bib"
        input_path.write_text(json.dumps([{}, "not-an-object"]), encoding="utf-8")

        exit_code = vr.main([
            "--validate", str(input_path),
            "--audit-out", str(audit_path),
            "--bib-out", str(bib_path),
            "--no-retraction",
            "--check-disambiguation",
        ])

        assert exit_code == 1
        payload = json.loads(audit_path.read_text(encoding="utf-8"))
        assert payload["stage_trace_schema"] == vr.STAGE_TRACE_SCHEMA
        assert payload["summary"]["blocking"] == 2
        assert len(payload["refs"]) == 2
        assert all(set(ref["stage_trace"]) == set(vr.STAGE_KEYS) for ref in payload["refs"])
        assert payload["batch_stage_trace"]["F_bibliography_compile"] == {
            "enabled": True,
            "reached": False,
            "completed": False,
            "outcome": "not_reached",
        }
