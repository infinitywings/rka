#!/usr/bin/env python3
"""Runner for the decision back-tracing eval.

REST-direct against a running RKA instance (same convention as Eval-v2):
per scenario it exercises `/api/search` (when an `nl_query` is present),
`/api/graph/ego/{anchor}` at depth 2, and `/api/graph/multi-hop` seeded
with the anchor decision, then scores the union trace against the
scenario's expected entities.

Non-2xx responses are recorded as divergences, never crashes — a repeat
of the v2.5.x multi-hop 422 must show up as data.

Usage:
    python eval-harness/v3/tracing/runner.py \
        --corpus eval-harness/v3/tracing/scenarios.jsonl \
        --rka-url http://localhost:9712 \
        --out-dir eval-harness/v3/tracing/results \
        [--project prj_...]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx

_V3_DIR = Path(__file__).resolve().parent.parent
if str(_V3_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_V3_DIR.parent))

from v3.tracing.metrics import aggregate, score_scenario  # noqa: E402

ENTITY_ID_PATTERN = re.compile(
    r"\b(?:jrn|lit|dec|mis|clm|ecl|chk|prj|lnk|scn)_[0-9A-Z]{10,26}\b"
)


def extract_entity_ids(payload: Any) -> list[str]:
    """Order-preserving unique entity ids found anywhere in a JSON payload."""
    found: list[str] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            for match in ENTITY_ID_PATTERN.findall(node):
                if match not in seen:
                    seen.add(match)
                    found.append(match)

    walk(payload)
    return found


class TraceRunner:
    def __init__(
        self,
        rka_url: str,
        project_id: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._client = httpx.AsyncClient(
            base_url=rka_url.rstrip("/"), timeout=60.0, transport=transport
        )
        self._project_id = project_id

    async def close(self) -> None:
        await self._client.aclose()

    def _params(self, extra: dict | None = None) -> dict:
        params = dict(extra or {})
        if self._project_id:
            params["project_id"] = self._project_id
        return params

    async def _get_ids(
        self, label: str, coro, divergences: list[str]
    ) -> list[str]:
        try:
            response = await coro
        except httpx.HTTPError as exc:
            divergences.append(f"{label}: transport error {exc!r}")
            return []
        if response.status_code >= 400:
            divergences.append(f"{label}: HTTP {response.status_code}")
            return []
        try:
            payload = response.json()
        except ValueError:
            divergences.append(f"{label}: non-JSON body")
            return []
        return extract_entity_ids(payload)

    async def run_000055REDACTED(self, scenario: dict[str, Any]) -> dict[str, Any]:
        divergences: list[str] = []
        anchor = scenario["anchor_decision"]

        search_ids: list[str] | None = None
        if scenario.get("nl_query"):
            search_ids = await self._get_ids(
                "search",
                self._client.post(
                    "/api/search",
                    json={"query": scenario["nl_query"], "limit": 20},
                    params=self._params(),
                ),
                divergences,
            )

        ego_ids = await self._get_ids(
            "ego",
            self._client.get(
                f"/api/graph/ego/{anchor}", params=self._params({"depth": 2})
            ),
            divergences,
        )
        multi_hop_ids = await self._get_ids(
            "multi_hop",
            self._client.post(
                "/api/graph/multi-hop",
                json={
                    "seeds": [anchor],
                    "max_depth": 2,
                    "query": scenario.get("nl_query", "") or None,
                },
                params=self._params(),
            ),
            divergences,
        )

        result = score_scenario(
            scenario,
            {"ego": ego_ids, "multi_hop": multi_hop_ids},
            search_ids,
            divergences,
        )
        result["raw"] = {
            "search_ids": search_ids,
            "ego_ids": ego_ids,
            "multi_hop_ids": multi_hop_ids,
        }
        return result

    async def run_corpus(self, scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [await self.run_000055REDACTED(scenario) for scenario in scenarios]


def load_corpus(path: Path) -> list[dict[str, Any]]:
    scenarios = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        scenario = json.loads(line)
        for field in ("scenario_id", "anchor_decision", "expected_trace"):
            if field not in scenario:
                raise ValueError(f"{path}:{line_no}: missing required field {field!r}")
        scenarios.append(scenario)
    return scenarios


async def amain(args: argparse.Namespace) -> int:
    corpus_path = Path(args.corpus)
    scenarios = load_corpus(corpus_path)
    runner = TraceRunner(args.rka_url, args.project)
    try:
        results = await runner.run_corpus(scenarios)
    finally:
        await runner.close()

    out_dir = Path(args.out_dir)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for result in results:
        (raw_dir / f"{result['scenario_id']}.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )

    summary = {
        "meta": {
            "corpus": corpus_path.name,
            "corpus_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
            "rka_url": args.rka_url,
            "project_filter": args.project,
        },
        "aggregate": aggregate(results),
    }
    (out_dir / "metrics.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary["aggregate"], indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--rka-url", default="http://localhost:9712")
    parser.add_argument("--out-dir", default=str(Path(__file__).parent / "results"))
    parser.add_argument("--project", help="optional project_id filter")
    args = parser.parse_args(argv)
    return asyncio.run(amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
