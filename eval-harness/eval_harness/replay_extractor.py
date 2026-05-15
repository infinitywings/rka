"""Replay extractor — surfaces candidate eval queries from session journals.

Mission: mis_01KRKJ9G20EM5XMA147JTKQCFF · Task T1 (replay half)

Scans recent journal entries via `GET /api/notes?since=...` and
identifies references to RKA retrieval invocations (`rka_search`,
`rka_get_research_map`, `rka_multi_hop_retrieval`) in their `content`
text. Each hit becomes a candidate that Brain + PI curate down to the
~10–15 most representative queries for the eval corpus.

The extractor is intentionally heuristic. Journal content is free-form
narrative (Brain reports, Executor backbriefs, PI directives) where
tool invocations appear in many shapes:

  - rka_search(query="…")             — explicit call syntax
  - rka_search('…')                   — positional arg
  - rka_search in backticked text     — markdown code reference
  - "I called rka_search to find X"   — prose mention

The first two yield extractable query strings; the latter two only
surface the surrounding context so Brain + PI can manually phrase the
implied query.

CLI usage::

    python -m eval_harness.replay_extractor \\
        --api-url http://127.0.0.1:9712 \\
        --lookback-days 28 \\
        --output ../corpus/replayed_candidates.jsonl

The candidates file is intermediate — Brain + PI curate it into the
canonical `corpus/replayed_queries.jsonl` (T1 deliverable).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

import httpx


TOOL_NAMES = (
    "rka_search",
    "rka_get_research_map",
    "rka_multi_hop_retrieval",
)

DEFAULT_API_URL = "http://127.0.0.1:9712"
DEFAULT_LOOKBACK_DAYS = 28
PAGE_LIMIT = 200  # /api/notes server cap

# /api/notes is project-scoped via the `project_id` query parameter
# (or `X-RKA-Project` header). Missing both defaults to `proj_default`
# server-side, which leaves recent entries in other projects invisible
# to the extractor. Callers MUST supply --project-id when scanning
# anything other than the default project.

CONTEXT_CHARS_BEFORE = 120
CONTEXT_CHARS_AFTER = 200

# Match the tool name as a whole-token reference.
_TOOL_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in TOOL_NAMES) + r")\b",
)

# Try to extract a query string from an explicit call right after the tool name.
# Handles:  rka_search("foo")  · rka_search('foo')  · rka_search(query="foo")
_CALL_PATTERN = re.compile(
    r"""\s*\(\s*                              # opening paren
        (?:query\s*=\s*)?                     # optional `query=` keyword arg
        (?P<quote>['"])                       # opening quote
        (?P<query>(?:\\.|(?!(?P=quote)).)*)   # the string content
        (?P=quote)                            # closing quote
    """,
    re.VERBOSE,
)

# JSON tool_use-shape extraction:
#   ..."name": "rka_search"... "query": "foo"...
_JSON_QUERY_PATTERN = re.compile(
    r'"query"\s*:\s*"((?:\\.|[^"\\])*)"',
)


@dataclass
class ReplayCandidate:
    """One candidate query surfaced from a journal-entry scan."""

    query: str | None
    """The extracted query string if the call was structured; None if the
    tool was only referenced in prose (Brain + PI will manually phrase
    the implied query during curation)."""

    tool: str
    """Which retrieval tool the mention pointed at."""

    original_journal_id: str
    """jrn_… ID of the journal entry the mention came from."""

    original_context: str
    """A ~320-char window around the mention (≈120 before / ≈200 after)
    so Brain + PI can read the surrounding narrative when curating."""

    detected_at: str
    """ISO timestamp the journal entry was created at."""

    category: str = "replay"
    """Top-level category — always 'replay' for this extractor. Brain
    refines into specific categories (decision-finding, recent-journal,
    multi-hop, etc.) during curation."""

    source: str = "replay"
    """Matches the canonical queries.jsonl `source` field convention."""

    confidence: str = "candidate"
    """`candidate` until Brain + PI promote during curation."""

    extra_tags: list[str] = field(default_factory=list)
    """Free-form tags the extractor or curator may attach."""

    def to_jsonl_row(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def _fetch_journal_page(
    client: httpx.Client,
    project_id: str | None,
    since_iso: str,
    offset: int,
    limit: int,
) -> list[dict]:
    """Fetch one page of journal entries from /api/notes."""
    params: dict[str, str | int] = {
        "since": since_iso,
        "limit": limit,
        "offset": offset,
        "hide_superseded": "true",
    }
    if project_id is not None:
        params["project_id"] = project_id
    response = client.get("/api/notes", params=params)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError(f"unexpected /api/notes shape: {type(payload).__name__}")
    return payload


def _iter_journal_entries(
    api_url: str,
    since: datetime,
    project_id: str | None = None,
    timeout: float = 10.0,
) -> Iterator[dict]:
    """Yield every journal entry whose `created_at` >= `since` within the
    `project_id` scope (server default is `proj_default` if unset)."""
    since_iso = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    offset = 0
    with httpx.Client(base_url=api_url, timeout=timeout) as client:
        while True:
            page = _fetch_journal_page(client, project_id, since_iso, offset, PAGE_LIMIT)
            if not page:
                return
            yield from page
            if len(page) < PAGE_LIMIT:
                return
            offset += PAGE_LIMIT


def _extract_query_after_match(content: str, match_end: int) -> str | None:
    """Try to pull a quoted query string from a call right after a tool
    name. Returns the string or None if no structured call was found."""
    call = _CALL_PATTERN.match(content, match_end)
    if call:
        raw = call.group("query")
        return raw.encode("utf-8").decode("unicode_escape", errors="replace")
    return None


def _extract_json_style_query(content: str, mention_position: int) -> str | None:
    """In tool_use-style JSON dumps, the `"query"` field can sit a few
    fields away from `"name": "rka_search"`. Scan a 500-char window
    after the tool mention for a `"query":"…"` pair."""
    window = content[mention_position : mention_position + 500]
    json_match = _JSON_QUERY_PATTERN.search(window)
    if json_match:
        raw = json_match.group(1)
        return raw.encode("utf-8").decode("unicode_escape", errors="replace")
    return None


def _surrounding_context(content: str, start: int, end: int) -> str:
    """A trimmed window of journal content around a match. Leading +
    trailing ellipses signal truncation."""
    left = max(0, start - CONTEXT_CHARS_BEFORE)
    right = min(len(content), end + CONTEXT_CHARS_AFTER)
    snippet = content[left:right].strip()
    if left > 0:
        snippet = "… " + snippet
    if right < len(content):
        snippet = snippet + " …"
    return snippet


def extract_candidates_from_entry(entry: dict) -> list[ReplayCandidate]:
    """Pull every tool-mention candidate from a single journal entry."""
    content = entry.get("content") or ""
    journal_id = entry.get("id", "")
    created_at = entry.get("created_at") or ""
    out: list[ReplayCandidate] = []

    for match in _TOOL_PATTERN.finditer(content):
        tool = match.group(1)
        start, end = match.span()

        query = _extract_query_after_match(content, end)
        if query is None:
            query = _extract_json_style_query(content, end)

        out.append(
            ReplayCandidate(
                query=query,
                tool=tool,
                original_journal_id=journal_id,
                original_context=_surrounding_context(content, start, end),
                detected_at=created_at,
            )
        )
    return out


def extract_candidates(
    api_url: str = DEFAULT_API_URL,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    project_id: str | None = None,
    timeout: float = 10.0,
) -> list[ReplayCandidate]:
    """End-to-end: fetch recent journals, scan each, return all candidates.

    Brain + PI then curate this list down to ~10–15 representative
    queries for the eval corpus.
    """
    since = datetime.now(tz=timezone.utc) - timedelta(days=lookback_days)
    candidates: list[ReplayCandidate] = []
    for entry in _iter_journal_entries(api_url, since, project_id=project_id, timeout=timeout):
        candidates.extend(extract_candidates_from_entry(entry))
    return candidates


def write_jsonl(candidates: Iterable[ReplayCandidate], path: Path) -> int:
    """Write candidates as JSONL. Returns the row count written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as fh:
        for c in candidates:
            fh.write(json.dumps(c.to_jsonl_row(), ensure_ascii=False))
            fh.write("\n")
            n += 1
    return n


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Surface candidate eval queries from recent RKA journal entries.",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"RKA REST API base URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help=f"Days of journal history to scan (default: {DEFAULT_LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help=(
            "Project ID to scope the /api/notes query (e.g. prj_01KKQM…). "
            "If omitted, the server defaults to `proj_default` and recent "
            "entries in other projects will be invisible."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output JSONL path for the candidate list.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Per-request HTTP timeout in seconds (default: 10).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        candidates = extract_candidates(
            api_url=args.api_url,
            lookback_days=args.lookback_days,
            project_id=args.project_id,
            timeout=args.timeout,
        )
    except httpx.HTTPError as e:
        print(f"error fetching from {args.api_url}: {e}", file=sys.stderr)
        return 2

    rows = write_jsonl(candidates, args.output)
    with_query = sum(1 for c in candidates if c.query is not None)
    print(
        f"wrote {rows} candidate(s) to {args.output} "
        f"({with_query} with extracted query, {rows - with_query} context-only)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
