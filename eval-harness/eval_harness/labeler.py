"""Interactive CLI for PI graded labeling (T4 deliverable).

Mission `mis_01KRKJ9G20EM5XMA147JTKQCFF` Task T4.

The labeler reads ALL configs' raw results, deduplicates the
(query, result_id) pairs across configs, and presents each unique
pair to the PI for a 0/1/2 graded rating. The mission spec's
labeler-deduplication design (T2 refinement) keeps PI labeling
burden at ~300–500 unique pairs instead of the naive ~1200 (4
configs × 30 queries × 10 results).

CLI usage::

    python -m eval_harness.labeler \\
        --results-dir results/raw \\
        --queries corpus/queries.jsonl \\
        --output results/labels/labels.jsonl

The output is a single labels.jsonl that all configs share — each
line `{"query", "result_id", "rating", "rated_at", "note"}`.

Resume support: re-running the labeler skips any (query, result_id)
already in the labels.jsonl. PI can interrupt + resume freely.

Heartbeat per observation #4: the labeler prints progress every
PROGRESS_HEARTBEAT_EVERY ratings so a long session doesn't look
stuck. Final notification on completion per observation #7 (loud
visible message, never silent-fail).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


RATINGS = ("0", "1", "2")
RATING_HELP = {
    "0": "irrelevant",
    "1": "somewhat relevant",
    "2": "highly relevant",
}
PROGRESS_HEARTBEAT_EVERY = 20  # observation #4


@dataclass
class LabelRow:
    query: str
    result_id: str
    rating: int
    rated_at: str
    note: str = ""


@dataclass
class Candidate:
    """One unique (query, result_id) needing a rating."""

    query: str
    result_id: str
    snippet: str
    seen_in_configs: list[str]


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Dedup logic — load all configs' raw results into unique (query, result_id)
# ---------------------------------------------------------------------------


def collect_unique_candidates(
    results_dir: Path,
) -> list[Candidate]:
    """Walk every results/raw/*.jsonl and deduplicate by (query, result_id).

    For each unique pair, we keep the FIRST snippet encountered + the
    list of configs that returned it (useful for "is this widely
    returned or just one config?" context during labeling).
    """
    seen: dict[tuple[str, str], Candidate] = {}
    for raw_path in sorted(results_dir.glob("*.jsonl")):
        config_name = raw_path.stem
        with raw_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                query = payload["query"]
                for result in payload.get("results", []):
                    rid = result.get("id")
                    if not rid:
                        continue
                    key = (query, rid)
                    if key in seen:
                        if config_name not in seen[key].seen_in_configs:
                            seen[key].seen_in_configs.append(config_name)
                    else:
                        seen[key] = Candidate(
                            query=query,
                            result_id=rid,
                            snippet=result.get("snippet") or "",
                            seen_in_configs=[config_name],
                        )
    return list(seen.values())


def load_existing_labels(path: Path) -> set[tuple[str, str]]:
    """Return the set of (query, result_id) already rated, for resume."""
    if not path.exists():
        return set()
    seen: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            seen.add((row["query"], row["result_id"]))
    return seen


def append_label(path: Path, row: LabelRow) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row.__dict__, ensure_ascii=False))
        fh.write("\n")


# ---------------------------------------------------------------------------
# Interactive prompt
# ---------------------------------------------------------------------------


def _read_rating(prompt: str) -> tuple[int, str, bool]:
    """Return (rating, note, abort).

    Accepts 0/1/2 + optional ` note`. Special inputs: `q` quits the
    session, `s` skips this candidate without rating, `?` shows help.
    """
    while True:
        try:
            raw = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return (0, "", True)
        if raw == "":
            continue
        if raw == "q":
            return (0, "", True)
        if raw == "s":
            return (-1, "", False)  # signal skip
        if raw == "?":
            print("  Rate the result above:")
            for r, label in RATING_HELP.items():
                print(f"    {r} = {label}")
            print("  Append a note after a space: e.g. `2 strong match for X`")
            print("  Other:  s = skip · q = quit + save · ? = help")
            continue
        first, _, note = raw.partition(" ")
        if first not in RATINGS:
            print(f"  Unrecognized rating {first!r}. Type ? for help.")
            continue
        return (int(first), note.strip(), False)


def _print_candidate(idx: int, total: int, c: Candidate) -> None:
    width = max(20, len(c.query))
    print()
    print("─" * 78)
    print(f"  Query [{idx}/{total}] :: {c.query}")
    print(f"  Result ID       :: {c.result_id}")
    if c.seen_in_configs:
        print(f"  Returned by     :: {', '.join(c.seen_in_configs)}")
    print()
    print("  --- snippet ---")
    for line in (c.snippet or "(no snippet captured)").splitlines():
        print(f"  {line}")
    print()


def run_labeler(
    *,
    results_dir: Path,
    output_path: Path,
    query_filter: set[str] | None = None,
) -> int:
    """Drive the interactive labeling session.

    Returns the count of NEW labels written this session (excludes
    pre-existing labels reused via resume)."""
    candidates = collect_unique_candidates(results_dir)
    if query_filter is not None:
        candidates = [c for c in candidates if c.query in query_filter]

    already_rated = load_existing_labels(output_path)
    todo = [
        c for c in candidates if (c.query, c.result_id) not in already_rated
    ]

    total_unique = len(candidates)
    print(
        f"[labeler] {total_unique} unique (query, result) pairs across configs · "
        f"{len(already_rated)} already rated · {len(todo)} pending"
    )
    if not todo:
        print("[labeler] nothing to do; all candidates already rated.")
        return 0

    n_new = 0
    aborted = False
    for i, candidate in enumerate(todo, start=1):
        _print_candidate(i, len(todo), candidate)
        rating, note, abort = _read_rating(
            "  Rating (0/1/2 + optional note · ? = help · s = skip · q = quit): "
        )
        if abort:
            aborted = True
            break
        if rating < 0:
            # Skip without persisting.
            continue
        row = LabelRow(
            query=candidate.query,
            result_id=candidate.result_id,
            rating=rating,
            rated_at=_now_iso(),
            note=note,
        )
        append_label(output_path, row)
        n_new += 1
        if n_new % PROGRESS_HEARTBEAT_EVERY == 0:
            print(
                f"  [labeler] heartbeat · {n_new} new labels written this "
                f"session · {len(todo) - i} pending"
            )

    if aborted:
        # Loud termination message per observation #7 — never silent-fail.
        print()
        print(
            f"  [labeler] ⚠ SESSION INTERRUPTED — {n_new} labels saved to "
            f"{output_path}. Resume by re-running the same command."
        )
    else:
        print()
        print(
            f"  [labeler] ✓ DONE — {n_new} new labels written this session "
            f"(total {len(already_rated) + n_new} of {total_unique} unique pairs)."
        )
    return n_new


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Interactive 0/1/2 graded labeling, deduplicated across configs."
        ),
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        required=True,
        help="Directory with per-config <name>.jsonl raw results.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="labels.jsonl path (append-only; resume-safe).",
    )
    parser.add_argument(
        "--queries",
        type=Path,
        default=None,
        help=(
            "Optional corpus/queries.jsonl path. If supplied, candidates "
            "are restricted to queries listed in this file (useful for "
            "labeling subsets)."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    query_filter: set[str] | None = None
    if args.queries is not None:
        query_filter = set()
        with args.queries.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                query_filter.add(json.loads(line)["query"])
    run_labeler(
        results_dir=args.results_dir,
        output_path=args.output,
        query_filter=query_filter,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
