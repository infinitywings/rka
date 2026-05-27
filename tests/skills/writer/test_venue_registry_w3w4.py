"""Phase W3 + W4 - registry expansion tests.

W3 ships ~50 minimal-baseline venue YAMLs (CS conferences, CS journals,
FT50 accounting / finance / management). W4 ships the NSF PAPPG base
spec + a CAREER solicitation that uses `inherits_from` to overlay
PAPPG defaults.

These tests verify (without re-validating every individual file -- that
is venue_loader's job, already covered by test_venue_loader.py):
  - load_all_venues returns the full expanded set
  - new domains parse (cs-nlp, cs-cv, cs-ir, cs-web, etc.)
  - one representative from each new family loads and has the
    expected kind/domain
  - NSF-PAPPG loads, kind=proposal renders through venue_md_generator
    without raising
  - NSF-CAREER inherits PAPPG's format/tone block and overrides
    required_sections (delta semantics enforced by merge_inheritance)
"""

from __future__ import annotations


# Representative venues per W3 family (kind, domain). Not exhaustive --
# venue_loader's load_all_venues check covers the rest.
W3_REPRESENTATIVES = {
    "ICML":        ("conference", "cs-ml"),
    "ICLR":        ("conference", "cs-ml"),
    "AAAI":        ("conference", "cs-ml"),
    "CVPR":        ("conference", "cs-cv"),
    "ICCV":        ("conference", "cs-cv"),
    "ACL":         ("conference", "cs-nlp"),
    "ACL-Short":   ("conference", "cs-nlp"),
    "SOSP":        ("conference", "cs-systems"),
    "ASPLOS":      ("conference", "cs-systems"),
    "ISCA":        ("conference", "cs-arch"),
    "MICRO":       ("conference", "cs-arch"),
    "PLDI":        ("conference", "cs-pl"),
    "POPL":        ("conference", "cs-pl"),
    "SIGCOMM":     ("conference", "cs-net"),
    "CCS":         ("conference", "cs-security"),
    "NDSS":        ("conference", "cs-security"),
    "UIST":        ("conference", "cs-hci"),
    "CSCW":        ("conference", "cs-hci"),
    "SIGIR":       ("conference", "cs-ir"),
    "WWW":         ("conference", "cs-web"),
    # CS journals
    "TPAMI":       ("journal",    "cs-cv"),
    "TOPLAS":      ("journal",    "cs-pl"),
    "TOCS":        ("journal",    "cs-systems"),
    "TON":         ("journal",    "cs-net"),
    "JACM":        ("journal",    "cs-systems"),
    "CACM":        ("journal",    "cs-systems"),
    # FT50 accounting
    "JAR":         ("journal",    "acct"),
    "JAE":         ("journal",    "acct"),
    "TAR":         ("journal",    "acct"),
    "RAST":        ("journal",    "acct"),
    "CAR":         ("journal",    "acct"),
    # FT50 finance
    "JF":          ("journal",    "fin"),
    "JFE":         ("journal",    "fin"),
    "RFS":         ("journal",    "fin"),
    "JFQA":        ("journal",    "fin"),
    # FT50 management
    "AMJ":         ("journal",    "mgmt"),
    "AMR":         ("journal",    "mgmt"),
    "ASQ":         ("journal",    "mgmt"),
    "JOM":         ("journal",    "mgmt"),
    "MS":          ("journal",    "mgmt"),
    "OS":          ("journal",    "mgmt"),
    "SMJ":         ("journal",    "mgmt"),
}


def test_load_all_venues_returns_full_registry(venue_loader):
    """The full expanded registry loads without VenueValidationError
    and includes the W1 shipped seven, the W3 representatives, and
    the W4 NSF entries."""
    venues = venue_loader.load_all_venues()
    # W1 baseline preserved.
    assert {"CHI", "EMNLP", "IEEE-SP", "Nature", "NeurIPS", "OSDI", "USENIX"}.issubset(
        venues.keys()
    )
    # Every W3 representative is present.
    missing = set(W3_REPRESENTATIVES.keys()) - venues.keys()
    assert not missing, f"missing W3 venues: {sorted(missing)}"
    # W4 proposals are present too.
    assert "NSF-PAPPG" in venues
    assert "NSF-CAREER" in venues


def test_each_w3_representative_has_expected_kind_and_domain(venue_loader):
    for vid, (kind, domain) in W3_REPRESENTATIVES.items():
        v = venue_loader.load_venue(vid)
        assert v.kind == kind, f"{vid}: kind {v.kind!r} != {kind!r}"
        assert v.domain == domain, f"{vid}: domain {v.domain!r} != {domain!r}"


def test_ft50_business_journals_have_double_blind_and_author_year(venue_loader):
    """Accounting / finance / management journals follow shared conventions:
    double-blind review, author-year citations, third-person voice."""
    for vid in ("JAR", "JF", "AMJ"):  # one from each FT50 sub-family
        v = venue_loader.load_venue(vid)
        assert v.kind == "journal"
        assert v.submission.anonymization == "required"
        assert v.format.citation_style == "author-year"
        assert v.tone.voice == "third-person"


def test_cs_nlp_uses_name_year_citation(venue_loader):
    """ACL Anthology family uses name-year (natbib) citations."""
    for vid in ("ACL", "ACL-Short", "NAACL", "EMNLP-Short"):
        v = venue_loader.load_venue(vid)
        assert v.format.citation_style == "name-year"


def test_short_track_page_limits(venue_loader):
    """ACL-Short and EMNLP-Short cap main paper at 4 pages."""
    for vid in ("ACL-Short", "EMNLP-Short"):
        v = venue_loader.load_venue(vid)
        assert v.submission.page_limit_main == 4


def test_cs_journals_have_no_fixed_page_limit(venue_loader):
    """ACM/IEEE journals don't impose a submission-time page cap."""
    for vid in ("TPAMI", "TOPLAS", "TON", "JACM"):
        v = venue_loader.load_venue(vid)
        assert v.submission.page_limit_main is None


# ---------------------------------------------------------------------------
# W4 - NSF proposals
# ---------------------------------------------------------------------------


def test_nsf_pappg_loads_as_proposal(venue_loader):
    v = venue_loader.load_venue("NSF-PAPPG")
    assert v.kind == "proposal"
    assert v.domain == "proposal"
    assert v.submission.page_limit_main == 15
    # PAPPG mandates explicit IM + BI sections in the Project Description.
    assert "Intellectual Merit" in v.structure.required_sections
    assert "Broader Impacts" in v.structure.required_sections
    # PAPPG review-criteria framing.
    names = [rd.name for rd in v.review_dimensions]
    assert "intellectual_merit" in names
    assert "broader_impacts" in names


def test_nsf_career_inherits_pappg_baseline(venue_loader):
    """CAREER overrides required_sections + review_dimensions but
    inherits PAPPG's submission, format, and tone blocks via
    merge_inheritance."""
    career = venue_loader.load_venue("NSF-CAREER")
    pappg = venue_loader.load_venue("NSF-PAPPG")
    # Format inherited from PAPPG (CAREER didn't redeclare).
    assert career.format.template_id == pappg.format.template_id
    assert career.format.citation_style == pappg.format.citation_style
    # Tone inherited.
    assert career.tone.voice == pappg.tone.voice
    assert career.tone.hedging == pappg.tone.hedging
    # Required sections REPLACED (delta semantics): CAREER adds
    # "Integrated Research and Education Plan" + "Department Letter"
    # that PAPPG doesn't carry.
    assert "Integrated Research and Education Plan" in career.structure.required_sections
    assert "Department Letter" in career.structure.required_sections
    assert "Integrated Research and Education Plan" not in pappg.structure.required_sections
    # Review dimensions REPLACED -- CAREER adds two CAREER-specific axes.
    names = [rd.name for rd in career.review_dimensions]
    assert "integration_of_research_and_education" in names
    assert "career_development_trajectory" in names


def test_nsf_career_inherits_from_pappg_field(venue_loader):
    """The inherits_from field is preserved on the loaded Venue."""
    career_raw = venue_loader.load_venue("NSF-CAREER", resolve_inheritance=False)
    assert career_raw.inherits_from == "NSF-PAPPG"


# ---------------------------------------------------------------------------
# kind=proposal renders through venue_md_generator without error
# ---------------------------------------------------------------------------


def test_proposal_kind_renders_canonical_sections(
    venue_loader, venue_md_generator
):
    """The MD generator must not assume kind in (conference, journal);
    proposals carry the same seven canonical sections."""
    v = venue_loader.load_venue("NSF-PAPPG")
    md = venue_md_generator.render_md(v)
    assert "## 1. Section names and order" in md
    assert "## 2. Page-limit class" in md
    assert "## 3. Tone characteristics" in md
    assert "## 4. Forbidden constructions" in md
    assert "## 5. Citation style" in md
    assert "## 6. Required sections" in md
    assert "## 7. Sample corpus pointers" in md
    # The Kind line in the header now carries "proposal".
    assert "**Kind**: proposal" in md
