"""Zotero linker — resolve an RKA literature entry to its Zotero item key.

Tries six matching strategies in order of confidence:
  1. DOI
  2. arXiv ID (extracted from URL or DOI prefix)
  3. URL (for working papers, preprints, blog posts)
  4. ISBN (for books)
  5. Title + first author + year (fuzzy fallback)
  6. Standalone attachment / webpage title fuzzy match (v2.7.0.3 gray-lit
     path — NEVER auto-links; always returns weak_match_needs_confirmation
     for PI ratification via explicit zotero_key).

Stops at the first hit. Returns the match method so the caller can
record an audit trail.

Reads `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_ID`, `ZOTERO_LIBRARY_TYPE`
from the environment. If unset, returns a structured "not configured"
result rather than raising — callers can degrade gracefully.

Security: never logs the API key value. Probe results contain only
the resolved item key (8-char alnum) — no secret content.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

ZOTERO_API_BASE = "https://api.zotero.org"
DEFAULT_TIMEOUT = 10.0

# Recognized arXiv ID forms (modern + legacy). Matches both bare IDs and
# arxiv.org URLs.
_ARXIV_PATTERNS = [
    re.compile(r"\barxiv\.org/(?:abs|pdf|html)/(?P<id>\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE),
    re.compile(r"\barxiv\.org/(?:abs|pdf|html)/(?P<id>[a-z\-]+/\d{7})(?:v\d+)?", re.IGNORECASE),
    re.compile(r"\barxiv:\s*(?P<id>\d{4}\.\d{4,5})(?:v\d+)?\b", re.IGNORECASE),
    re.compile(r"\barxiv:\s*(?P<id>[a-z\-]+/\d{7})(?:v\d+)?\b", re.IGNORECASE),
    re.compile(r"^(?P<id>\d{4}\.\d{4,5})$"),  # bare ID
]

_ISBN_PATTERN = re.compile(r"\b(97[89][\-\s]?(?:\d[\-\s]?){9}\d|\d[\-\s]?(?:\d[\-\s]?){8}[\dxX])\b")


@dataclass
class LinkResult:
    """Result of a single linking attempt."""
    zotero_item_key: Optional[str] = None
    matched_by: Optional[str] = None
    candidates: list[dict] = None
    reason: Optional[str] = None
    confidence: Optional[float] = None

    def to_dict(self) -> dict:
        out: dict[str, Any] = {
            "zotero_item_key": self.zotero_item_key,
            "matched_by": self.matched_by,
        }
        if self.candidates:
            out["candidates"] = self.candidates
        if self.reason:
            out["reason"] = self.reason
        if self.confidence is not None:
            out["confidence"] = self.confidence
        return out


def _normalize_library_type(library_type: str) -> str:
    """Normalize 'user'/'users'/'group'/'groups' → URL-path plural."""
    plural = library_type.rstrip("s") + "s"
    if plural not in ("users", "groups"):
        plural = "users"
    return plural


def _env_config() -> Optional[tuple[str, str, str]]:
    """Read Zotero creds from env vars (operator override path).

    v2.7.0.2: env vars still win over the persisted config file at
    ``/data/zotero_config.json``. This preserves the one-off testing /
    eval-harness pattern (``ZOTERO_API_KEY=... docker compose up``) while
    the persistent path goes through ``ZoteroConfigService``.
    """
    api_key = (os.environ.get("ZOTERO_API_KEY") or "").strip()
    library_id = (os.environ.get("ZOTERO_LIBRARY_ID") or "").strip()
    library_type = (os.environ.get("ZOTERO_LIBRARY_TYPE") or "user").strip().lower()
    if not api_key or not library_id:
        return None
    return api_key, library_id, _normalize_library_type(library_type)


def _persisted_config() -> Optional[tuple[str, str, str]]:
    """Read Zotero creds from `/data/zotero_config.json` (v2.7.0.2).

    Returns the same (api_key, library_id, library_type-URL-plural) tuple
    as `_env_config()`. Returns None when the file is missing OR the
    persisted config is not fully populated (api_key + library_id both
    non-empty). Failures in the file-read path log a warning but return
    None so the caller falls through to `LinkResult(reason='zotero_not_configured')`
    rather than raising.
    """
    try:
        # Lazy import keeps zotero_linker importable without the service.
        from rka.services.zotero_config import ZoteroConfigService
    except ImportError:
        return None
    try:
        cfg_svc = ZoteroConfigService()
        cfg = cfg_svc.load_config()
    except Exception as exc:  # noqa: BLE001
        logger.warning("zotero_config load failed; treating as not-configured: %s", exc)
        return None
    if not cfg.is_configured():
        return None
    return (
        cfg.api_key.strip(),
        cfg.library_id.strip(),
        _normalize_library_type(cfg.library_type),
    )


def _resolve_config() -> Optional[tuple[str, str, str]]:
    """Resolve Zotero creds: env > /data/zotero_config.json > None.

    v2.7.0.2: returns the first source that yields a fully-configured
    triple. Env wins for operator-override paths (one-off testing,
    eval-harness); the file is the persistent path the Web UI / REST API
    writes to so the cred survives ``docker compose up -d --build``.
    """
    return _env_config() or _persisted_config()


def is_configured() -> bool:
    return _resolve_config() is not None


def _extract_arxiv_id(*texts: Optional[str]) -> Optional[str]:
    """Find an arXiv ID in any of the provided texts (URL, DOI, etc.)."""
    for txt in texts:
        if not txt:
            continue
        for pat in _ARXIV_PATTERNS:
            m = pat.search(txt)
            if m:
                return m.group("id")
    return None


def _extract_isbn(*texts: Optional[str]) -> Optional[str]:
    for txt in texts:
        if not txt:
            continue
        m = _ISBN_PATTERN.search(txt)
        if m:
            return re.sub(r"[\-\s]", "", m.group(1))
    return None


def _zotero_search(
    client,
    base: str,
    query: str,
    qmode: str = "everything",
    item_type: Optional[str] = None,
) -> list[dict]:
    """Single-page Zotero items search. Returns the list of item dicts.

    v2.7.0.3 (Bug 4): the optional ``item_type`` kwarg is forwarded to
    Zotero's ``itemType`` URL param. Supports the boolean ``||`` (OR) and
    ``-`` (NOT) syntax documented in the Zotero Web API v3 reference,
    e.g. ``item_type="attachment || webpage"`` (Strategy 6's filter).
    Omitted when None so the surface for Strategies 1-5 is unchanged.
    """
    params: dict[str, Any] = {
        "q": query,
        "qmode": qmode,
        "limit": 25,
        "format": "json",
    }
    if item_type is not None:
        params["itemType"] = item_type
    try:
        r = client.get(f"{base}/items", params=params)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Zotero items search failed for q=%r: %s", query, exc)
        return []
    if r.status_code != 200:
        return []
    try:
        return r.json() or []
    except Exception:  # noqa: BLE001
        return []


# ---- v2.7.0.3 Strategy 6 false-positive guards ----
#
# Per PI bug report 2026-06-03: gray literature (sector reports, working
# papers, standalone PDFs) often appears in Zotero only as attachments
# with auto-generated filenames. We must avoid matching these "detritus"
# titles against any lit row whose own title shares 1-2 generic tokens.
#
# _ATTACHMENT_TITLE_STOPWORDS: filenames that recur across Zotero auto-
# imports when no metadata was extracted from the PDF. A candidate whose
# normalized title (a) equals a stopword exactly, OR (b) is <=2 tokens
# AND any token is in the set, is skipped before similarity scoring.
_ATTACHMENT_TITLE_STOPWORDS = frozenset({
    "untitled",
    "document",
    "pdf",
    "doc",
    "file",
    "attachment",
    "scan",
    "image",
    "snapshot",
    "fulltext",
    "full text",
    "manuscript",
})


def _is_stopword_title(normalized_title: str) -> bool:
    """True if a normalized title looks like Zotero auto-generated detritus.

    v2.7.0.3 Strategy 6 guard. The check is intentionally narrow — we
    only filter titles that are short AND contain a stopword token.
    Real paper titles with 4+ tokens almost never trip this even if they
    happen to mention "document" or "manuscript" in passing.
    """
    if not normalized_title:
        return True
    if normalized_title in _ATTACHMENT_TITLE_STOPWORDS:
        return True
    tokens = normalized_title.split()
    if len(tokens) <= 2 and any(t in _ATTACHMENT_TITLE_STOPWORDS for t in tokens):
        return True
    return False


def _normalize_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    d = doi.strip().lower()
    # Strip common URL prefixes
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "dx.doi.org/"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d


def _item_matches_doi(item_data: dict, doi: str) -> bool:
    item_doi = (item_data.get("DOI") or "").strip().lower()
    if item_doi and _normalize_doi(item_doi) == _normalize_doi(doi):
        return True
    # Some imports stash the DOI in `extra` as "DOI: ..."
    extra = (item_data.get("extra") or "").lower()
    if doi.lower() in extra:
        return True
    return False


def _item_matches_arxiv(item_data: dict, arxiv_id: str) -> bool:
    aid = arxiv_id.lower()
    # arXiv items in Zotero typically use itemType "preprint" or "report"
    # with archiveID = "<id>" and url containing the id
    archive_id = (item_data.get("archiveID") or "").lower()
    extra = (item_data.get("extra") or "").lower()
    url = (item_data.get("url") or "").lower()
    if aid in archive_id or f"arxiv:{aid}" in extra or aid in url:
        return True
    return False


def _norm_text(s: str) -> str:
    """Lowercase, strip punctuation + extra whitespace for fuzzy compare."""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _title_similarity(a: str, b: str) -> float:
    """Token Jaccard over normalized titles."""
    ta, tb = set(_norm_text(a).split()), set(_norm_text(b).split())
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    union = ta | tb
    return len(inter) / len(union) if union else 0.0


def link_literature(
    *,
    title: Optional[str] = None,
    authors: Optional[list[str]] = None,
    year: Optional[int] = None,
    doi: Optional[str] = None,
    url: Optional[str] = None,
    zotero_key: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> LinkResult:
    """Try to find a Zotero item matching this literature entry.

    Returns a LinkResult. zotero_item_key is None if no confident match.

    v2.7.0.3 (Bug 4 fix, per PI bug report 2026-06-03): when Strategies
    1-5 produce no_match, Strategy 6 searches Zotero for standalone
    attachments + webpages whose title fuzzy-matches the lit title and
    returns weak_match_needs_confirmation candidates the PI can ratify
    via an explicit ``zotero_key`` call. Targets gray literature (sector
    reports, working papers) that exists only as PDF attachments without
    parent bibliographic items. NEVER auto-links — attachment titles
    are noisy (filenames like 'untitled.pdf') so PI confirmation is
    required.

    v2.7.0.2 (Bug 3 fix): when ``zotero_key`` is supplied, validate it
    exists in the configured library via direct GET on /items/<key>, then
    return the explicit-key result and bypass the five fuzzy-match
    strategies. This is the manual override path for cases the matcher
    can't anchor on — standalone PDF attachments, working papers without
    bibliographic metadata, sector reports without DOIs.

    v2.7.0.2 (Bug 1 fix): credential resolution falls back to
    ``/data/zotero_config.json`` via ``ZoteroConfigService`` when env
    vars are empty. Pre-fix this returned ``zotero_not_configured`` on
    every container restart because the Docker images don't ship Zotero
    env, leaving the linker permanently broken until the operator
    re-sourced ``.env`` and ``--force-recreate``'d.
    """
    cfg = _resolve_config()
    if cfg is None:
        return LinkResult(reason="zotero_not_configured")

    api_key, library_id, library_type = cfg

    try:
        import httpx
    except ImportError:
        return LinkResult(reason="httpx_not_installed")

    headers = {
        "Zotero-API-Key": api_key,
        "Zotero-API-Version": "3",
        "User-Agent": "rka/2.7",
    }
    base = f"{ZOTERO_API_BASE}/{library_type}/{library_id}"

    # ---- Strategy 0: explicit zotero_key (v2.7.0.2 override path) ----
    if zotero_key and zotero_key.strip():
        key = zotero_key.strip()
        try:
            with httpx.Client(timeout=timeout, headers=headers) as client:
                resp = client.get(f"{base}/items/{key}")
            if resp.status_code == 200:
                return LinkResult(
                    zotero_item_key=key,
                    matched_by="explicit_key",
                    confidence=1.0,
                )
            if resp.status_code == 404:
                return LinkResult(
                    reason=f"explicit_key_not_found: {key}",
                )
            return LinkResult(
                reason=f"explicit_key_probe_error: HTTP {resp.status_code}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Zotero explicit-key probe failed: %s", exc)
            return LinkResult(reason=f"explicit_key_probe_error: {type(exc).__name__}")

    try:
        with httpx.Client(timeout=timeout, headers=headers) as client:
            # ---- Strategy 1: DOI ----
            ndoi = _normalize_doi(doi)
            if ndoi:
                items = _zotero_search(client, base, ndoi, qmode="everything")
                for it in items:
                    data = it.get("data", {})
                    if _item_matches_doi(data, ndoi):
                        return LinkResult(
                            zotero_item_key=data.get("key"),
                            matched_by="doi",
                        )

            # ---- Strategy 2: arXiv ID ----
            arxiv_id = _extract_arxiv_id(url, doi)
            if arxiv_id:
                items = _zotero_search(client, base, arxiv_id, qmode="everything")
                for it in items:
                    data = it.get("data", {})
                    if _item_matches_arxiv(data, arxiv_id):
                        return LinkResult(
                            zotero_item_key=data.get("key"),
                            matched_by="arxiv_id",
                        )

            # ---- Strategy 3: URL exact-ish ----
            if url and url.strip():
                items = _zotero_search(client, base, url.strip(), qmode="everything")
                for it in items:
                    data = it.get("data", {})
                    item_url = (data.get("url") or "").strip()
                    if item_url and item_url.lower() == url.strip().lower():
                        return LinkResult(
                            zotero_item_key=data.get("key"),
                            matched_by="url",
                        )

            # ---- Strategy 4: ISBN ----
            isbn = _extract_isbn(doi, url)
            if isbn:
                items = _zotero_search(client, base, isbn, qmode="everything")
                for it in items:
                    data = it.get("data", {})
                    item_isbn = (data.get("ISBN") or "").replace("-", "").replace(" ", "")
                    if item_isbn and isbn in item_isbn:
                        return LinkResult(
                            zotero_item_key=data.get("key"),
                            matched_by="isbn",
                        )

            # ---- Strategy 5: title + first author + year ----
            if title and title.strip():
                items = _zotero_search(client, base, title.strip(), qmode="titleCreatorYear")
                candidates: list[dict] = []
                best: Optional[tuple[float, dict]] = None
                first_author_surname = ""
                if authors:
                    parts = authors[0].split(",")[0].split()
                    if parts:
                        first_author_surname = _norm_text(parts[-1])
                for it in items:
                    data = it.get("data", {})
                    item_title = data.get("title") or ""
                    sim = _title_similarity(title, item_title)
                    if sim < 0.6:
                        continue
                    # Year match (within 1 year) is a strong corroborator
                    item_year_str = (data.get("date") or "")[:4]
                    year_match = False
                    if year and item_year_str.isdigit():
                        year_match = abs(int(item_year_str) - year) <= 1
                    # First-author surname match
                    item_authors = data.get("creators") or []
                    author_match = False
                    if first_author_surname:
                        for cr in item_authors:
                            last = _norm_text(cr.get("lastName") or "")
                            if last and (last == first_author_surname or first_author_surname in last):
                                author_match = True
                                break
                    score = sim + (0.15 if year_match else 0) + (0.20 if author_match else 0)
                    candidate = {
                        "key": data.get("key"),
                        "title": item_title,
                        "year": item_year_str,
                        "similarity": round(sim, 3),
                        "year_match": year_match,
                        "author_match": author_match,
                        "score": round(score, 3),
                    }
                    candidates.append(candidate)
                    if best is None or score > best[0]:
                        best = (score, candidate)

                if best and best[0] >= 0.95:
                    return LinkResult(
                        zotero_item_key=best[1]["key"],
                        matched_by="title_author_year",
                        confidence=round(best[0], 3),
                    )
                if len(candidates) > 1:
                    return LinkResult(
                        candidates=sorted(candidates, key=lambda c: -c["score"])[:5],
                        reason="multiple_matches_below_threshold",
                    )
                if best:
                    # Single weak candidate — surface it for PI confirmation
                    return LinkResult(
                        candidates=[best[1]],
                        reason="weak_match_needs_confirmation",
                    )

            # ---- Strategy 6: standalone attachment + webpage title fuzzy (v2.7.0.3) ----
            #
            # Per PI bug report 2026-06-03 (lit_01KSNPS7G… Moody's sector
            # report case): gray literature (sector reports, working papers,
            # standalone PDFs without parent bibliographic items) has no
            # DOI / arXiv ID / ISBN / URL anchor, AND no parent record for
            # Strategy 5's title_author_year heuristic to land on. The PI's
            # Zotero library represents such items as standalone attachments
            # (itemType=attachment, no parentItem) or webpages
            # (itemType=webpage). Strategy 6 searches those item types by
            # title and returns weak_match_needs_confirmation candidates
            # for PI ratification via an explicit zotero_key call.
            #
            # NEVER auto-link an attachment — the lack of bibliographic
            # corroboration (no author / year / venue we can verify against)
            # makes it too risky. The 0.85 strong-similarity threshold gates
            # inclusion in the candidate set; it does NOT auto-link. The
            # 0.65 weak floor filters noise (filename overlaps with a real
            # title at 0.4-0.6 Jaccard are common false positives).
            #
            # Threshold rationale:
            #   - Strategy 5 auto-links at score >= 0.95 (similarity alone
            #     can reach 1.0; author + year corroboration adds 0.35 of
            #     headroom) — bibliographic corroboration justifies auto-link.
            #   - Strategy 6 has ONLY title similarity (no author / no year
            #     for attachments; webpages may carry a date but we skip it
            #     for symmetry / simplicity) — even 0.85 is not enough to
            #     auto-link, so we surface ALL above-floor matches for the PI.
            #   - 0.65 weak floor: empirically filters 1-token filename hits
            #     while admitting real titles with 4+ tokens of overlap.
            #
            # False-positive mitigations (three layers):
            #   1. Title length floor: skip Strategy 6 entirely if the
            #      normalized lit title is <= 5 chars (short queries like
            #      'memo' / 'q4' produce spurious Jaccard hits).
            #   2. Stopword filter: skip candidate attachments whose title
            #      matches _ATTACHMENT_TITLE_STOPWORDS detritus patterns
            #      (untitled.pdf, document.pdf, scan, etc.).
            #   3. Parent-item filter: skip attachment candidates whose
            #      data.parentItem is truthy — these are CHILDREN of a
            #      bibliographic parent that Strategy 5 would already have
            #      matched if the parent's title aligned.
            if title and title.strip():
                normalized_lit_title = _norm_text(title)
                if len(normalized_lit_title) > 5:
                    attachment_items = _zotero_search(
                        client,
                        base,
                        title.strip(),
                        qmode="title",
                        item_type="attachment || webpage",
                    )
                    attachment_candidates: list[dict] = []
                    for it in attachment_items:
                        data = it.get("data", {})
                        item_type = (data.get("itemType") or "").lower()
                        # Mitigation #3: skip child attachments (bound to
                        # a bibliographic parent Strategy 5 would have hit).
                        # Webpages have no parent concept so the check is
                        # only meaningful for attachments.
                        if item_type == "attachment" and data.get("parentItem"):
                            continue
                        item_title = data.get("title") or ""
                        normalized_item_title = _norm_text(item_title)
                        # Mitigation #2: skip detritus filenames.
                        if _is_stopword_title(normalized_item_title):
                            continue
                        sim = _title_similarity(title, item_title)
                        # 0.65 weak floor — below this, contribute nothing.
                        if sim < 0.65:
                            continue
                        attachment_candidates.append({
                            "key": data.get("key"),
                            "title": item_title,
                            "item_type": item_type,
                            "similarity": round(sim, 3),
                        })
                    if attachment_candidates:
                        # Sort by similarity desc, cap at top 5.
                        # NEVER auto-link — even sim >= 0.85 returns as
                        # weak_match_needs_confirmation per PI directive
                        # (attachment titles lack the bibliographic
                        # corroboration that would justify auto-linking).
                        return LinkResult(
                            candidates=sorted(
                                attachment_candidates,
                                key=lambda c: -c["similarity"],
                            )[:5],
                            reason="weak_match_needs_confirmation",
                        )

            return LinkResult(reason="no_match")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Zotero link failed: %s", exc)
        return LinkResult(reason=f"error: {type(exc).__name__}")
