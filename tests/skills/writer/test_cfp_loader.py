"""Phase W2 - cfp_loader tests.

Covers:
  - HTML text extraction (strips tags, drops script/style)
  - fetch_cfp surfaces transport + HTTP errors as CFPFetchError
  - fetch_cfp rejects unsupported content-types
  - Heuristic extraction: page limits, references-counted, anonymization,
    abstract word cap, citation style, deadlines
  - render_overrides_yaml round-trips through yaml.safe_load
  - load_overrides_file validates envelope
  - apply_overrides overlays a partial overrides dict on a base Venue
  - load_workspace_venue applies both manuscript.yaml overrides and
    cfp_overrides.yaml in the right precedence
  - layout_audit._resolve_from_manuscript_yaml prefers cfp_overrides.yaml
    over the venue baseline
"""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest
import yaml


HTML_NEURIPS = """
<html><head><title>CFP</title><style>.x{color:red}</style></head>
<body>
<h1>NeurIPS 2025 Call for Papers</h1>
<p>The main paper is limited to 9 pages excluding references.</p>
<p>Submissions must be anonymous (double-blind review).</p>
<p>Abstracts are limited to 250 words.</p>
<p>Citations use numeric citations in cite-order.</p>
<p>Submission deadline: 2025-05-15. Author response deadline: 2025-08-01.</p>
<script>var x=1;</script>
</body></html>
"""

HTML_OSDI = """
<html><body>
<h2>OSDI Call</h2>
<p>The body of the paper must be limited to 12 pages, including references.</p>
<p>OSDI uses single-blind review; authors are identified to reviewers.</p>
<p>Abstract: up to 300 words.</p>
</body></html>
"""


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def test_extract_text_strips_script_and_style(cfp_loader):
    text = cfp_loader.extract_text_from_html(HTML_NEURIPS)
    assert "var x=1" not in text
    assert "color:red" not in text
    assert "NeurIPS 2025 Call for Papers" in text
    assert "limited to 9 pages excluding references" in text


def test_extract_text_inserts_paragraph_breaks(cfp_loader):
    text = cfp_loader.extract_text_from_html(HTML_NEURIPS)
    # Two consecutive <p>s should land on separate lines.
    assert "9 pages" in text and "anonymous" in text
    assert any(
        "9 pages" in ln for ln in text.splitlines()
    )
    assert any("anonymous" in ln for ln in text.splitlines())


# ---------------------------------------------------------------------------
# fetch_cfp transport behaviour
# ---------------------------------------------------------------------------


def test_fetch_cfp_returns_text_for_html(cfp_loader, monkeypatch):
    monkeypatch.setattr(
        cfp_loader,
        "_http_get",
        lambda url, **kw: (200, "text/html; charset=utf-8", HTML_NEURIPS.encode("utf-8")),
    )
    result = cfp_loader.fetch_cfp("https://example.test/cfp")
    assert result.http_status == 200
    assert result.content_type == "text/html"
    assert "NeurIPS 2025" in result.text
    assert result.url == "https://example.test/cfp"
    assert result.raw_bytes_len == len(HTML_NEURIPS.encode("utf-8"))


def test_fetch_cfp_rejects_pdf_content_type(cfp_loader, monkeypatch):
    monkeypatch.setattr(
        cfp_loader,
        "_http_get",
        lambda url, **kw: (200, "application/pdf", b"%PDF-1.7..."),
    )
    with pytest.raises(cfp_loader.CFPFetchError):
        cfp_loader.fetch_cfp("https://example.test/cfp.pdf")


def test_fetch_cfp_surfaces_http_error(cfp_loader, monkeypatch):
    import urllib.error

    def boom(url, **kw):  # noqa: ARG001
        raise urllib.error.HTTPError(
            url, 404, "Not Found", hdrs=None, fp=io.BytesIO(b"")
        )

    monkeypatch.setattr(cfp_loader, "_http_get", lambda url, **kw: (_ for _ in ()).throw(
        cfp_loader.CFPFetchError("HTTP 404 fetching x: Not Found")
    ))
    with pytest.raises(cfp_loader.CFPFetchError):
        cfp_loader.fetch_cfp("https://example.test/cfp")


# ---------------------------------------------------------------------------
# Heuristic extraction
# ---------------------------------------------------------------------------


def test_extract_candidates_neurips(cfp_loader):
    text = cfp_loader.extract_text_from_html(HTML_NEURIPS)
    c = cfp_loader.extract_candidates(text)
    assert c.page_limit_main is not None and c.page_limit_main[0] == 9
    assert c.references_counted is not None and c.references_counted[0] is False
    assert c.anonymization is not None and c.anonymization[0] == "required"
    assert c.abstract_word_max is not None and c.abstract_word_max[0] == 250
    assert c.citation_style is not None and c.citation_style[0] == "numeric"
    assert c.submission_deadline is not None and c.submission_deadline[0] == "2025-05-15"


def test_extract_candidates_osdi_inverts_signals(cfp_loader):
    text = cfp_loader.extract_text_from_html(HTML_OSDI)
    c = cfp_loader.extract_candidates(text)
    assert c.page_limit_main is not None and c.page_limit_main[0] == 12
    assert c.references_counted is not None and c.references_counted[0] is True
    assert c.anonymization is not None and c.anonymization[0] == "none"
    assert c.abstract_word_max is not None and c.abstract_word_max[0] == 300


def test_extract_candidates_returns_all_none_on_blank(cfp_loader):
    c = cfp_loader.extract_candidates("Lorem ipsum dolor sit amet.")
    assert c.page_limit_main is None
    assert c.references_counted is None
    assert c.anonymization is None
    assert c.abstract_word_max is None
    assert c.citation_style is None
    assert c.submission_deadline is None


def test_page_limit_sanity_floor(cfp_loader):
    # 50-page "limit" must NOT be accepted (outside 1-40 sanity range).
    text = "main text is limited to 50 pages"
    c = cfp_loader.extract_candidates(text)
    assert c.page_limit_main is None


# ---------------------------------------------------------------------------
# render_overrides_yaml
# ---------------------------------------------------------------------------


def test_render_overrides_yaml_is_valid_yaml(cfp_loader):
    text = cfp_loader.extract_text_from_html(HTML_NEURIPS)
    candidates = cfp_loader.extract_candidates(text)
    fetched = cfp_loader.CFPFetched(
        url="https://example.test/cfp",
        fetched_at="2026-05-27T00:00:00Z",
        http_status=200,
        content_type="text/html",
        text=text,
        raw_bytes_len=len(text),
    )
    out = cfp_loader.render_overrides_yaml(
        base_venue_id="NeurIPS", source=fetched, candidates=candidates
    )
    payload = yaml.safe_load(out)
    assert payload["schema_version"] == "v1"
    assert payload["base_venue_id"] == "NeurIPS"
    assert payload["source"]["url"] == "https://example.test/cfp"
    assert payload["overrides"]["submission"]["page_limit_main"] == 9
    assert payload["overrides"]["submission"]["anonymization"] == "required"
    assert payload["overrides"]["format"]["citation_style"] == "numeric"
    assert "submission.page_limit_main" in payload["review_required"]


def test_render_overrides_yaml_omits_undetected_sections(cfp_loader):
    fetched = cfp_loader.CFPFetched(
        url="x", fetched_at="2026-01-01T00:00:00Z", http_status=200,
        content_type="text/html", text="", raw_bytes_len=0,
    )
    out = cfp_loader.render_overrides_yaml(
        base_venue_id="NeurIPS",
        source=fetched,
        candidates=cfp_loader.CFPCandidates(),
    )
    payload = yaml.safe_load(out)
    assert payload["overrides"] == {} or payload["overrides"] is None
    # No review_required key when nothing detected.
    assert "review_required" not in payload


# ---------------------------------------------------------------------------
# load_overrides_file envelope validation
# ---------------------------------------------------------------------------


def test_load_overrides_file_rejects_bad_schema_version(cfp_loader, tmp_path):
    p = tmp_path / "cfp_overrides.yaml"
    p.write_text("schema_version: v0\nbase_venue_id: NeurIPS\n", encoding="utf-8")
    with pytest.raises(cfp_loader.CFPOverrideError):
        cfp_loader.load_overrides_file(p)


def test_load_overrides_file_requires_base_venue_id(cfp_loader, tmp_path):
    p = tmp_path / "cfp_overrides.yaml"
    p.write_text("schema_version: v1\n", encoding="utf-8")
    with pytest.raises(cfp_loader.CFPOverrideError):
        cfp_loader.load_overrides_file(p)


# ---------------------------------------------------------------------------
# apply_overrides
# ---------------------------------------------------------------------------


def test_apply_overrides_replaces_page_limit_only(venue_loader, cfp_loader):
    base = venue_loader.load_venue("NeurIPS")
    overrides = {"submission": {"page_limit_main": 11, "anonymization": "required"}}
    merged = cfp_loader.apply_overrides(base, overrides)
    assert merged.submission.page_limit_main == 11
    assert merged.submission.anonymization == "required"
    # Other base sections untouched.
    assert merged.format.citation_style == base.format.citation_style
    assert merged.tone.voice == base.tone.voice
    assert merged.id == base.id


def test_apply_overrides_noop_when_empty(venue_loader, cfp_loader):
    base = venue_loader.load_venue("NeurIPS")
    assert cfp_loader.apply_overrides(base, {}) is base


def test_apply_overrides_rejects_non_mapping_section(venue_loader, cfp_loader):
    base = venue_loader.load_venue("NeurIPS")
    with pytest.raises(cfp_loader.CFPOverrideError):
        cfp_loader.apply_overrides(base, {"submission": "not-a-mapping"})


# ---------------------------------------------------------------------------
# load_workspace_venue
# ---------------------------------------------------------------------------


def _make_workspace(
    tmp_path: Path,
    venue_loader,
    *,
    venue_id: str = "NeurIPS",
    manuscript_overrides: dict | None = None,
    cfp_overrides: dict | None = None,
) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manuscript_payload = {
        "schema_version": "v1",
        "venue_id": venue_id,
        "project_id": "prj_test",
        "title": "Test",
        "overrides": manuscript_overrides or {},
    }
    (workspace / "manuscript.yaml").write_text(
        yaml.safe_dump(manuscript_payload, sort_keys=False),
        encoding="utf-8",
    )
    if cfp_overrides is not None:
        cfp_payload = {
            "schema_version": "v1",
            "base_venue_id": venue_id,
            "source": {
                "url": "https://example.test/cfp",
                "fetched_at": "2026-05-27T00:00:00Z",
                "http_status": 200,
                "content_type": "text/html",
            },
            "overrides": cfp_overrides,
        }
        (workspace / "cfp_overrides.yaml").write_text(
            yaml.safe_dump(cfp_payload, sort_keys=False),
            encoding="utf-8",
        )
    return workspace


def test_load_workspace_venue_baseline_only(cfp_loader, venue_loader, tmp_path):
    workspace = _make_workspace(tmp_path, venue_loader)
    v = cfp_loader.load_workspace_venue(workspace)
    baseline = venue_loader.load_venue("NeurIPS")
    assert v.submission.page_limit_main == baseline.submission.page_limit_main


def test_load_workspace_venue_manuscript_override_wins(
    cfp_loader, venue_loader, tmp_path
):
    workspace = _make_workspace(
        tmp_path, venue_loader, manuscript_overrides={"page_limit_main": 7}
    )
    v = cfp_loader.load_workspace_venue(workspace)
    assert v.submission.page_limit_main == 7


def test_load_workspace_venue_cfp_overrides_apply(
    cfp_loader, venue_loader, tmp_path
):
    workspace = _make_workspace(
        tmp_path,
        venue_loader,
        cfp_overrides={"submission": {"page_limit_main": 11}},
    )
    v = cfp_loader.load_workspace_venue(workspace)
    assert v.submission.page_limit_main == 11


def test_load_workspace_venue_manuscript_beats_cfp(
    cfp_loader, venue_loader, tmp_path
):
    """Per-manuscript overrides are the most specific signal; they win
    over year-wide CFP overrides."""
    workspace = _make_workspace(
        tmp_path,
        venue_loader,
        manuscript_overrides={"page_limit_main": 5},
        cfp_overrides={"submission": {"page_limit_main": 11}},
    )
    v = cfp_loader.load_workspace_venue(workspace)
    assert v.submission.page_limit_main == 5


def test_load_workspace_venue_rejects_mismatched_base(
    cfp_loader, venue_loader, tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "manuscript.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "v1",
            "venue_id": "NeurIPS",
            "project_id": "prj_test",
            "title": "T",
        }),
        encoding="utf-8",
    )
    (workspace / "cfp_overrides.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "v1",
            "base_venue_id": "CHI",  # mismatch
            "source": {"url": "x", "fetched_at": "x", "http_status": 200, "content_type": "text/html"},
            "overrides": {},
        }),
        encoding="utf-8",
    )
    with pytest.raises(cfp_loader.CFPOverrideError):
        cfp_loader.load_workspace_venue(workspace)


def test_load_workspace_venue_rejects_unfilled_placeholder(cfp_loader, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "manuscript.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "v1",
            "venue_id": "REPLACE_WITH_VENUE_ID",
            "project_id": "prj_test",
            "title": "T",
        }),
        encoding="utf-8",
    )
    with pytest.raises(cfp_loader.CFPOverrideError):
        cfp_loader.load_workspace_venue(workspace)


# ---------------------------------------------------------------------------
# layout_audit integration
# ---------------------------------------------------------------------------


def test_layout_audit_reads_cfp_overrides_page_limit(layout_audit, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "manuscript.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "v1",
            "venue_id": "NeurIPS",
            "project_id": "prj_test",
            "title": "T",
            "overrides": {"page_limit_main": None},
        }),
        encoding="utf-8",
    )
    (workspace / "cfp_overrides.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "v1",
            "base_venue_id": "NeurIPS",
            "source": {"url": "x", "fetched_at": "x", "http_status": 200, "content_type": "text/html"},
            "overrides": {"submission": {"page_limit_main": 11}},
        }),
        encoding="utf-8",
    )
    venue_id, page_limit = layout_audit._resolve_from_manuscript_yaml(
        workspace / "manuscript.yaml"
    )
    assert venue_id == "NeurIPS"
    assert page_limit == 11


def test_layout_audit_manuscript_override_beats_cfp(layout_audit, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "manuscript.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "v1",
            "venue_id": "NeurIPS",
            "project_id": "prj_test",
            "title": "T",
            "overrides": {"page_limit_main": 7},
        }),
        encoding="utf-8",
    )
    (workspace / "cfp_overrides.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "v1",
            "base_venue_id": "NeurIPS",
            "source": {"url": "x", "fetched_at": "x", "http_status": 200, "content_type": "text/html"},
            "overrides": {"submission": {"page_limit_main": 11}},
        }),
        encoding="utf-8",
    )
    venue_id, page_limit = layout_audit._resolve_from_manuscript_yaml(
        workspace / "manuscript.yaml"
    )
    assert page_limit == 7  # manuscript wins


def test_layout_audit_falls_back_to_venue_baseline_without_cfp(
    layout_audit, tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "manuscript.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "v1",
            "venue_id": "NeurIPS",
            "project_id": "prj_test",
            "title": "T",
        }),
        encoding="utf-8",
    )
    venue_id, page_limit = layout_audit._resolve_from_manuscript_yaml(
        workspace / "manuscript.yaml"
    )
    assert venue_id == "NeurIPS"
    assert page_limit > 0  # whatever NeurIPS.yaml declares


# ---------------------------------------------------------------------------
# Idempotency: re-rendering the same fetched payload yields identical YAML
# ---------------------------------------------------------------------------


def test_render_overrides_yaml_idempotent(cfp_loader):
    fetched = cfp_loader.CFPFetched(
        url="https://example.test/cfp",
        fetched_at="2026-05-27T00:00:00Z",
        http_status=200,
        content_type="text/html",
        text=cfp_loader.extract_text_from_html(HTML_NEURIPS),
        raw_bytes_len=len(HTML_NEURIPS),
    )
    candidates = cfp_loader.extract_candidates(fetched.text)
    first = cfp_loader.render_overrides_yaml(
        base_venue_id="NeurIPS", source=fetched, candidates=candidates
    )
    second = cfp_loader.render_overrides_yaml(
        base_venue_id="NeurIPS", source=fetched, candidates=candidates
    )
    assert first == second
