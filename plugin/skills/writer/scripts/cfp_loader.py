#!/usr/bin/env python3
"""cfp_loader.py - fetch a year-specific Call-for-Papers URL and emit a
draft `cfp_overrides.yaml` that overlays the curated venue spec.

Phase W2 design:
  - LLM-free. The rka core does not ship server-side LLM (see CLAUDE.md
    "LLM-driven features ... were removed in v2.4.0"). This loader is
    deliberately a rule-based heuristic that emits a DRAFT overrides
    file. Reviewers (a human, or Claude Code at the manuscript prompt)
    refine the file before use.
  - Stdlib-only HTTP (urllib). No new dependencies.
  - The fetched raw text is persisted next to the overrides YAML so
    re-extraction is reproducible offline.

Public API
----------
    fetch_cfp(url)                         -> CFPFetched
    extract_candidates(text)               -> dict
    render_overrides_yaml(...)             -> str
    apply_overrides(base, overrides_dict)  -> Venue
    load_workspace_venue(workspace_dir)    -> Venue

CLI
---
    cfp_loader.py fetch <url> --base-venue NeurIPS --out cfp_overrides.yaml
    cfp_loader.py inspect <workspace-dir>     # print resolved venue spec
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional

import yaml

# Allow standalone CLI invocation and importlib loading (under pytest the
# scripts directory is not on sys.path).
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from venue_loader import (  # noqa: E402
    Venue,
    VenueValidationError,
    load_venue,
    merge_inheritance,
    venue_from_dict,
)

SCHEMA_VERSION = "v1"
DEFAULT_USER_AGENT = "rka-writer-cfp-loader/0.1 (+https://github.com/infinitywings/rka)"
DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_BYTES = 2_000_000  # 2 MB upper bound on fetched payload


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CFPFetchError(RuntimeError):
    """Raised when the CFP URL cannot be retrieved or decoded."""


class CFPOverrideError(ValueError):
    """Raised when a cfp_overrides.yaml file is malformed."""


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------


@dataclass
class CFPFetched:
    """Result of a CFP URL fetch."""
    url: str
    fetched_at: str  # ISO 8601 UTC
    http_status: int
    content_type: str
    text: str        # decoded body (plain text for HTML; raw text otherwise)
    raw_bytes_len: int


class _TextExtractor(HTMLParser):
    """Strip HTML tags and collapse whitespace into a single text blob.

    Skips <script>/<style>/<noscript> bodies and renders <br>/<p> as
    newlines so heuristic regex patterns see paragraph boundaries.
    """

    _SKIP = {"script", "style", "noscript", "head"}
    _BREAK = {"br", "p", "li", "div", "section", "article", "h1", "h2",
              "h3", "h4", "h5", "h6", "tr", "td", "th"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: D401
        if tag in self._SKIP:
            self._skip_depth += 1
        if tag in self._BREAK:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in self._BREAK:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def get_text(self) -> str:
        raw = "".join(self._chunks)
        # Collapse runs of whitespace within a line; preserve paragraph breaks.
        lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in raw.splitlines()]
        # Collapse 3+ blank lines to one blank line.
        out: list[str] = []
        blank = 0
        for ln in lines:
            if ln:
                out.append(ln)
                blank = 0
            else:
                blank += 1
                if blank == 1:
                    out.append("")
        return "\n".join(out).strip() + "\n"


def extract_text_from_html(html: str) -> str:
    """Strip HTML markup and return plain text suitable for regex extraction."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.get_text()


def _http_get(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    user_agent: str = DEFAULT_USER_AGENT,
) -> tuple[int, str, bytes]:
    """Plain HTTP GET. Returns (status, content_type, body_bytes).

    Separated from `fetch_cfp` so tests can monkey-patch the network
    boundary without faking urllib internals.
    """
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            content_type = (resp.headers.get("Content-Type") or "").split(";", 1)[0].strip()
            body = resp.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise CFPFetchError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise CFPFetchError(f"network error fetching {url}: {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise CFPFetchError(f"transport error fetching {url}: {exc}") from exc
    if len(body) > max_bytes:
        raise CFPFetchError(
            f"response from {url} exceeds {max_bytes} bytes (truncated read)"
        )
    return status, content_type, body


def fetch_cfp(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> CFPFetched:
    """Retrieve a CFP URL, decode it, and return text suitable for extraction.

    HTML payloads are stripped of markup. Non-HTML, non-text content types
    (e.g., application/pdf) are rejected — the loader is intentionally
    text-only; PDFs should be converted with `pdftotext` outside this
    module and the resulting text fed to `extract_candidates()` directly.
    """
    status, content_type, body = _http_get(url, timeout=timeout, max_bytes=max_bytes)
    # Tolerate callers (and test mocks) that hand back the raw header
    # value with a charset suffix; canonicalise on the bare media-type.
    content_type = content_type.split(";", 1)[0].strip()
    ct = content_type.lower()
    if ct.startswith("text/html") or ct.startswith("application/xhtml"):
        # Decode best-effort; HTML pages frequently mis-declare charset.
        for enc in ("utf-8", "latin-1"):
            try:
                html = body.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            html = body.decode("utf-8", errors="replace")
        text = extract_text_from_html(html)
    elif ct.startswith("text/"):
        text = body.decode("utf-8", errors="replace")
    else:
        raise CFPFetchError(
            f"unsupported content-type {content_type!r} for {url} "
            f"(only text/html and text/* are parsed; for PDFs convert with "
            f"pdftotext and call extract_candidates() directly)"
        )
    return CFPFetched(
        url=url,
        fetched_at=_dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        http_status=status,
        content_type=content_type or "text/plain",
        text=text,
        raw_bytes_len=len(body),
    )


# ---------------------------------------------------------------------------
# Heuristic extraction
# ---------------------------------------------------------------------------

# Patterns are deliberately conservative: prefer false-negative (no
# extraction) over false-positive (wrong value silently injected).
# Anything emitted lands in the YAML's `review_required:` list so the
# reviewer must touch it before relying on it.

_RE_PAGE_LIMIT = re.compile(
    r"\b(?:limited\s+to|maximum\s+of|up\s+to|no\s+more\s+than)\s+(\d{1,2})\s+pages?\b",
    re.IGNORECASE,
)
_RE_PAGE_LIMIT_ALT = re.compile(
    r"\b(\d{1,2})\s*[- ]page\s+limit\b",
    re.IGNORECASE,
)
_RE_PAGE_LIMIT_BODY = re.compile(
    r"\b(?:main\s+(?:text|paper|body)|body\s+of\s+the\s+paper)\s+"
    r"(?:is|must\s+be|may\s+be)?\s*(?:limited\s+to|at\s+most|up\s+to)?\s*"
    r"(\d{1,2})\s+pages?\b",
    re.IGNORECASE,
)
_RE_REFS_EXCLUDED = re.compile(
    r"\b(?:excluding|not\s+counting|exclude[sd]?)\s+references\b",
    re.IGNORECASE,
)
_RE_REFS_INCLUDED = re.compile(
    r"\b(?:including|inclusive\s+of|counting)\s+references\b",
    re.IGNORECASE,
)
_RE_ANON = re.compile(
    r"\b(?:double[- ]blind|anonymous\s+submission|anonymized\s+submission|"
    r"author\s+identities?\s+(?:must|should)\s+be\s+(?:hidden|removed))\b",
    re.IGNORECASE,
)
_RE_ANON_NONE = re.compile(
    r"\b(?:single[- ]blind|not\s+anonymous|non[- ]anonymous|"
    r"authors?\s+are\s+identified)\b",
    re.IGNORECASE,
)
_RE_ABSTRACT_MAX = re.compile(
    r"\babstracts?\b[^\n]{0,40}?"
    r"(?:up\s+to|at\s+most|no\s+more\s+than|maximum\s+of|limited\s+to|:)\s*"
    r"(\d{2,4})\s+words?\b",
    re.IGNORECASE,
)
# Citation style hints are very noisy; we only flag if the page repeatedly
# names a style by canonical phrase.
_RE_CITE_NUMERIC = re.compile(r"\bnumeric(?:al)?\s+citations?\b", re.IGNORECASE)
_RE_CITE_NAME_YEAR = re.compile(
    r"\b(?:author[- ]year|name[- ]year|natbib\s+author[- ]year)\s+(?:citation|style)\b",
    re.IGNORECASE,
)
# Submission deadlines: best-effort ISO 8601 capture for any explicit
# "submission deadline" phrase nearby. Returns the first match only.
_RE_DEADLINE = re.compile(
    r"submission\s+deadline[^\n]{0,80}?"
    r"(\d{4}-\d{2}-\d{2}|"
    r"[A-Z][a-z]+\s+\d{1,2},?\s+\d{4})",
    re.IGNORECASE,
)


def _detect_page_limit(text: str) -> Optional[tuple[int, str]]:
    """Return (page_limit, matched_phrase) or None.

    Prefer the body/main-text-specific pattern; fall back to generic
    "limited to N pages" if none of the body patterns match.
    """
    for pat in (_RE_PAGE_LIMIT_BODY, _RE_PAGE_LIMIT, _RE_PAGE_LIMIT_ALT):
        m = pat.search(text)
        if m:
            try:
                n = int(m.group(1))
            except (ValueError, IndexError):
                continue
            if 1 <= n <= 40:  # sanity floor/ceiling
                return n, m.group(0)
    return None


def _detect_references_counted(text: str) -> Optional[tuple[bool, str]]:
    if m := _RE_REFS_EXCLUDED.search(text):
        return False, m.group(0)
    if m := _RE_REFS_INCLUDED.search(text):
        return True, m.group(0)
    return None


def _detect_anonymization(text: str) -> Optional[tuple[str, str]]:
    if m := _RE_ANON.search(text):
        return "required", m.group(0)
    if m := _RE_ANON_NONE.search(text):
        return "none", m.group(0)
    return None


def _detect_abstract_max(text: str) -> Optional[tuple[int, str]]:
    m = _RE_ABSTRACT_MAX.search(text)
    if not m:
        return None
    try:
        n = int(m.group(1))
    except (ValueError, IndexError):
        return None
    if 50 <= n <= 1000:
        return n, m.group(0)
    return None


def _detect_citation_style(text: str) -> Optional[tuple[str, str]]:
    if m := _RE_CITE_NUMERIC.search(text):
        return "numeric", m.group(0)
    if m := _RE_CITE_NAME_YEAR.search(text):
        return "name-year", m.group(0)
    return None


def _detect_deadline(text: str) -> Optional[tuple[str, str]]:
    m = _RE_DEADLINE.search(text)
    if not m:
        return None
    return m.group(1), m.group(0)


@dataclass
class CFPCandidates:
    """Heuristic extraction result.

    Each field is one of:
      - None (not detected)
      - (value, matched_phrase) tuple (detected; phrase recorded for
        provenance + reviewer context)
    """
    page_limit_main: Optional[tuple[int, str]] = None
    references_counted: Optional[tuple[bool, str]] = None
    anonymization: Optional[tuple[str, str]] = None
    abstract_word_max: Optional[tuple[int, str]] = None
    citation_style: Optional[tuple[str, str]] = None
    submission_deadline: Optional[tuple[str, str]] = None


def extract_candidates(text: str) -> CFPCandidates:
    """Run all heuristics against `text` and return a CFPCandidates."""
    return CFPCandidates(
        page_limit_main=_detect_page_limit(text),
        references_counted=_detect_references_counted(text),
        anonymization=_detect_anonymization(text),
        abstract_word_max=_detect_abstract_max(text),
        citation_style=_detect_citation_style(text),
        submission_deadline=_detect_deadline(text),
    )


def candidates_to_overrides_dict(c: CFPCandidates) -> dict[str, Any]:
    """Turn detected candidates into the `overrides:` block of cfp_overrides.yaml.

    Drops keys whose detection returned None so the YAML stays minimal.
    """
    overrides: dict[str, Any] = {}
    submission: dict[str, Any] = {}
    if c.page_limit_main is not None:
        submission["page_limit_main"] = c.page_limit_main[0]
    if c.references_counted is not None:
        submission["references_counted"] = c.references_counted[0]
    if c.anonymization is not None:
        submission["anonymization"] = c.anonymization[0]
    if submission:
        overrides["submission"] = submission
    if c.abstract_word_max is not None:
        overrides["structure"] = {"abstract_word_max": c.abstract_word_max[0]}
    if c.citation_style is not None:
        overrides["format"] = {"citation_style": c.citation_style[0]}
    return overrides


# ---------------------------------------------------------------------------
# Overrides YAML rendering
# ---------------------------------------------------------------------------


_OVERRIDES_HEADER = (
    "# cfp_overrides.yaml -- generated by cfp_loader.py from a CFP URL.\n"
    "#\n"
    "# This file overlays per-field deltas on top of the curated venue\n"
    "# spec at references/venue/<base_venue_id>.yaml. Layout_audit and\n"
    "# ai_tic_lint read both files via load_workspace_venue().\n"
    "#\n"
    "# IMPORTANT: extraction is heuristic. Every detected field is\n"
    "# listed under `review_required:` -- a reviewer must inspect each\n"
    "# one against the source CFP before it can be trusted. The raw\n"
    "# fetched text is persisted alongside this file as `cfp_raw.txt`.\n"
)


def render_overrides_yaml(
    *,
    base_venue_id: str,
    source: CFPFetched,
    candidates: CFPCandidates,
    extra_notes: Optional[list[str]] = None,
) -> str:
    """Build the textual cfp_overrides.yaml content for a fetched CFP."""
    overrides = candidates_to_overrides_dict(candidates)
    review_required: list[str] = []
    extraction_notes: list[str] = []

    def _flag(path: str, detection: Optional[tuple]) -> None:
        if detection is None:
            return
        review_required.append(path)
        extraction_notes.append(f"{path}: matched on '{detection[1].strip()}'")

    _flag("submission.page_limit_main", candidates.page_limit_main)
    _flag("submission.references_counted", candidates.references_counted)
    _flag("submission.anonymization", candidates.anonymization)
    _flag("structure.abstract_word_max", candidates.abstract_word_max)
    _flag("format.citation_style", candidates.citation_style)
    _flag("submission_deadline", candidates.submission_deadline)

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "base_venue_id": base_venue_id,
        "source": {
            "url": source.url,
            "fetched_at": source.fetched_at,
            "http_status": source.http_status,
            "content_type": source.content_type,
        },
        "overrides": overrides,
    }
    if candidates.submission_deadline is not None:
        payload["submission_deadline"] = candidates.submission_deadline[0]
    if review_required:
        payload["review_required"] = review_required
    notes = ["Heuristic extraction -- review every field under review_required."]
    notes.extend(extraction_notes)
    if extra_notes:
        notes.extend(extra_notes)
    payload["notes"] = notes

    body = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    return _OVERRIDES_HEADER + "\n" + body


# ---------------------------------------------------------------------------
# Overrides loading + overlay
# ---------------------------------------------------------------------------


def load_overrides_file(path: Path) -> dict[str, Any]:
    """Parse a cfp_overrides.yaml file and validate its envelope."""
    if not path.is_file():
        raise CFPOverrideError(f"{path}: file not found")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise CFPOverrideError(f"{path}: top-level must be a mapping")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise CFPOverrideError(
            f"{path}: schema_version must be {SCHEMA_VERSION!r}, "
            f"got {data.get('schema_version')!r}"
        )
    if not data.get("base_venue_id"):
        raise CFPOverrideError(f"{path}: base_venue_id is required")
    overrides = data.get("overrides")
    if overrides is not None and not isinstance(overrides, dict):
        raise CFPOverrideError(f"{path}: overrides must be a mapping")
    return data


def apply_overrides(base: Venue, overrides: dict[str, Any]) -> Venue:
    """Overlay a partial `overrides` dict onto a base Venue.

    Implementation reuses venue_loader.merge_inheritance by constructing
    a synthetic "child" Venue from `base` and patching only the
    sub-mappings that appear in `overrides`. Sub-mapping fields not
    mentioned in `overrides` stay at the base value (default-equal in
    the child -> inheritance picks base).
    """
    if not overrides:
        return base
    # Build a child dict that mirrors base's id/name/etc. but lets the
    # overrides drive each sub-mapping. We round-trip through the
    # validator to catch enum violations early.
    child_dict: dict[str, Any] = {
        "schema_version": base.schema_version,
        "id": base.id,
        "name": base.name,
        "kind": base.kind,
        "domain": base.domain,
        "status": base.status,
        "pin_year": base.pin_year,
    }
    for section in ("submission", "format", "structure", "tone"):
        if section in overrides:
            if not isinstance(overrides[section], dict):
                raise CFPOverrideError(f"overrides.{section} must be a mapping")
            child_dict[section] = overrides[section]
    # Pass-through for list-valued sections if present.
    for section in (
        "review_dimensions",
        "forbidden_constructions",
        "sample_corpus",
    ):
        if section in overrides:
            child_dict[section] = overrides[section]

    child = venue_from_dict(child_dict, source="<cfp_overrides>")
    return merge_inheritance(child=child, base=base)


# ---------------------------------------------------------------------------
# Workspace-level entry point
# ---------------------------------------------------------------------------


def load_workspace_venue(workspace_dir: Path) -> Venue:
    """Resolve the effective Venue for a workspace.

    Reads `<workspace_dir>/manuscript.yaml` to find the base venue, then
    applies in order:
      1. `manuscript.yaml -> overrides:` (per-manuscript scalar overrides)
      2. `<workspace_dir>/cfp_overrides.yaml` (year-specific CFP deltas)

    Returns the merged Venue. Raises CFPOverrideError on schema problems
    in either file.
    """
    manuscript_yaml = workspace_dir / "manuscript.yaml"
    if not manuscript_yaml.is_file():
        raise CFPOverrideError(f"{manuscript_yaml}: file not found")
    manuscript = yaml.safe_load(manuscript_yaml.read_text(encoding="utf-8")) or {}
    venue_id = str(manuscript.get("venue_id") or "").strip()
    if not venue_id or venue_id.startswith("REPLACE_WITH_"):
        raise CFPOverrideError(
            f"{manuscript_yaml}: venue_id is missing or unfilled placeholder"
        )
    try:
        venue = load_venue(venue_id)
    except VenueValidationError as exc:
        raise CFPOverrideError(f"venue {venue_id!r}: {exc}") from exc

    # Precedence (least-specific applied first so most-specific wins):
    #   baseline venue.yaml -> cfp_overrides.yaml -> manuscript.yaml
    # That way a per-manuscript override always beats a year-wide CFP
    # delta, and both beat the curated baseline.
    cfp_overrides_path = workspace_dir / "cfp_overrides.yaml"
    if cfp_overrides_path.is_file():
        cfp_data = load_overrides_file(cfp_overrides_path)
        if cfp_data.get("base_venue_id") != venue_id:
            raise CFPOverrideError(
                f"{cfp_overrides_path}: base_venue_id "
                f"{cfp_data['base_venue_id']!r} does not match "
                f"manuscript.yaml venue_id {venue_id!r}"
            )
        venue = apply_overrides(venue, cfp_data.get("overrides") or {})

    manuscript_overrides_raw = manuscript.get("overrides") or {}
    if isinstance(manuscript_overrides_raw, dict):
        manuscript_overrides = _normalise_manuscript_overrides(manuscript_overrides_raw)
        if manuscript_overrides:
            venue = apply_overrides(venue, manuscript_overrides)

    return venue


def _normalise_manuscript_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    """Translate manuscript.yaml's flat `overrides:` block into the
    nested {section: {field: value}} shape expected by apply_overrides.

    Recognised flat keys (W2): page_limit_main, citation_style.
    """
    out: dict[str, Any] = {}
    if raw.get("page_limit_main") not in (None, ""):
        out.setdefault("submission", {})["page_limit_main"] = raw["page_limit_main"]
    if raw.get("citation_style") not in (None, ""):
        out.setdefault("format", {})["citation_style"] = raw["citation_style"]
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_fetch(args) -> int:
    try:
        fetched = fetch_cfp(args.url, timeout=args.timeout)
    except CFPFetchError as exc:
        print(f"cfp_loader: {exc}", file=sys.stderr)
        return 1
    candidates = extract_candidates(fetched.text)
    try:
        base = load_venue(args.base_venue)
    except VenueValidationError as exc:
        print(f"cfp_loader: base venue {args.base_venue!r}: {exc}", file=sys.stderr)
        return 1
    yaml_text = render_overrides_yaml(
        base_venue_id=base.id,
        source=fetched,
        candidates=candidates,
    )
    if args.dry_run or args.out is None:
        sys.stdout.write(yaml_text)
        return 0
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml_text, encoding="utf-8")
    raw_path = out_path.with_name("cfp_raw.txt")
    raw_path.write_text(fetched.text, encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"wrote {raw_path}")
    return 0


def _cmd_inspect(args) -> int:
    workspace = Path(args.workspace_dir).resolve()
    try:
        venue = load_workspace_venue(workspace)
    except CFPOverrideError as exc:
        print(f"cfp_loader: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(dataclasses.asdict(venue), indent=2, default=str))
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="fetch a CFP URL and emit overrides YAML")
    fetch.add_argument("url")
    fetch.add_argument("--base-venue", required=True, help="curated venue id (e.g., NeurIPS)")
    fetch.add_argument("--out", default=None, help="output path; default stdout")
    fetch.add_argument("--dry-run", action="store_true", help="print to stdout regardless")
    fetch.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    fetch.set_defaults(func=_cmd_fetch)

    inspect = sub.add_parser(
        "inspect", help="print the resolved venue for a workspace dir"
    )
    inspect.add_argument("workspace_dir")
    inspect.set_defaults(func=_cmd_inspect)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
