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

from v3.tracing.metrics import (  # noqa: E402
    aggregate,
    aggregate_story,
    score_scenario,
    score_story_variant,
    story_scores,
)

# Prefix-agnostic on purpose: Core now has experiment/run/observation,
# evidence-locator, artifact, and scope entities in addition to the original
# journal/decision set.  The ULID-shaped suffix keeps ordinary prose from
# becoming an entity hit while allowing future 2-3 letter Core prefixes.
ENTITY_ID_PATTERN = re.compile(r"\b[a-z]{2,3}_[0-9A-Z]{26}\b")
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


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


def extract_graph_edges(payload: Any) -> list[dict[str, str]]:
    """Order-preserving graph edges found in a JSON payload."""
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            source = node.get("source") or node.get("source_id")
            target = node.get("target") or node.get("target_id")
            link_type = node.get("link_type") or node.get("relation")
            if (
                isinstance(source, str)
                and isinstance(target, str)
                and isinstance(link_type, str)
                and ENTITY_ID_PATTERN.fullmatch(source)
                and ENTITY_ID_PATTERN.fullmatch(target)
            ):
                key = (source, target, link_type)
                if key not in seen:
                    seen.add(key)
                    found.append({"source": source, "target": target, "link_type": link_type})
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found


def resolved_entity_ids(packet: dict[str, Any] | None, expected_project_id: str) -> list[str]:
    """IDs whose full records were actually resolved in the requested project."""
    if not packet or packet.get("project_id") != expected_project_id:
        return []
    return [
        entity_id
        for entity_id, resolution in packet.get("entities", {}).items()
        if resolution.get("found") is True
        and resolution.get("outcome") == "resolved"
        and resolution.get("project_id") == expected_project_id
    ]


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

    async def _get_ids(self, label: str, coro, divergences: list[str]) -> list[str]:
        surface = await self._get_surface(label, coro, divergences)
        return surface["ids"]

    async def _get_surface(self, label: str, coro, divergences: list[str]) -> dict[str, Any]:
        try:
            response = await coro
        except httpx.HTTPError as exc:
            divergences.append(f"{label}: transport error {exc!r}")
            return {"ids": [], "edges": [], "payload": None}
        if response.status_code >= 400:
            divergences.append(f"{label}: HTTP {response.status_code}")
            return {"ids": [], "edges": [], "payload": None}
        try:
            payload = response.json()
        except ValueError:
            divergences.append(f"{label}: non-JSON body")
            return {"ids": [], "edges": [], "payload": None}
        return {
            "ids": extract_entity_ids(payload),
            "edges": extract_graph_edges(payload),
            "payload": payload,
        }

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
            self._client.get(f"/api/graph/ego/{anchor}", params=self._params({"depth": 2})),
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

    async def _resolve_story_entities(
        self, ids: set[str], divergences: list[str]
    ) -> dict[str, Any] | None:
        if not ids:
            return None
        surface = await self._get_surface(
            "resolve",
            self._client.post(
                "/api/entities/resolve",
                json={
                    "ids": sorted(ids),
                    "include_sources": True,
                    "include_edges": True,
                },
                params=self._params(),
            ),
            divergences,
        )
        return surface["payload"]

    async def run_story_variant(
        self, scenario: dict[str, Any], variant: dict[str, Any]
    ) -> dict[str, Any]:
        """Run one query-only story probe; the gold anchor is never sent."""
        divergences: list[str] = []
        query = variant["query"]
        retrieval = scenario.get("retrieval", {})
        search_limit = retrieval.get("search_limit", 10)

        search = await self._get_surface(
            "search",
            self._client.post(
                "/api/search",
                json={"query": query, "limit": search_limit},
                params=self._params(),
            ),
            divergences,
        )
        multi_hop = await self._get_surface(
            "query_multi_hop",
            self._client.post(
                "/api/graph/multi-hop",
                json={
                    "query": query,
                    "max_depth": retrieval.get("max_depth", 3),
                    "max_nodes": retrieval.get("multi_hop_max_nodes", 25),
                },
                params=self._params(),
            ),
            divergences,
        )
        report_context = await self._get_surface(
            "report_context",
            self._client.post(
                "/api/graph/report-context",
                json={
                    "description": query,
                    "max_depth": retrieval.get("max_depth", 3),
                    "max_nodes": retrieval.get("report_max_nodes", 25),
                    "seed_limit": retrieval.get("seed_limit", 4),
                },
                params=self._params(),
            ),
            divergences,
        )

        surfaces = {
            "search": search,
            "query_multi_hop": multi_hop,
            "report_context": report_context,
        }
        expected_project_id = scenario["project_id"]
        union_ids = {entity_id for surface in surfaces.values() for entity_id in surface["ids"]}
        entity_packet = await self._resolve_story_entities(union_ids, divergences)
        resolver_edges = extract_graph_edges(entity_packet) if entity_packet else []
        surface_ids = {name: surface["ids"] for name, surface in surfaces.items()}
        surface_edges = {name: surface["edges"] for name, surface in surfaces.items()}
        # Bulk resolution is a normal second-stage retrieval call: it verifies
        # full facts/currentness and supplies the induced edges among the
        # candidate nodes without introducing oracle IDs.
        if entity_packet:
            surface_edges["resolve"] = resolver_edges

        result = score_story_variant(
            scenario,
            variant,
            surface_ids,
            surface_edges,
            search["ids"],
            entity_packet,
            divergences,
            anchor_k=search_limit,
        )
        result["raw"] = {
            "search_ids": search["ids"],
            "query_multi_hop_ids": multi_hop["ids"],
            "report_context_ids": report_context["ids"],
            "resolved_ids": resolved_entity_ids(entity_packet, expected_project_id),
        }
        return result

    async def _run_story_oracle(self, scenario: dict[str, Any]) -> dict[str, Any]:
        """Measure graph ceiling from the gold anchor; never a headline result."""
        divergences: list[str] = []
        anchor = scenario["anchor_decision"]
        ego = await self._get_surface(
            "oracle_ego",
            self._client.get(f"/api/graph/ego/{anchor}", params=self._params({"depth": 3})),
            divergences,
        )
        multi_hop = await self._get_surface(
            "oracle_multi_hop",
            self._client.post(
                "/api/graph/multi-hop",
                json={"seeds": [anchor], "max_depth": 3, "max_nodes": 80},
                params=self._params(),
            ),
            divergences,
        )
        ids = set(ego["ids"]) | set(multi_hop["ids"])
        packet = await self._resolve_story_entities(ids, divergences)
        edges = ego["edges"] + multi_hop["edges"]
        confirmed_ids = set(resolved_entity_ids(packet, scenario["project_id"]))
        if packet:
            edges.extend(extract_graph_edges(packet))
        confirmed_edges = [
            edge
            for edge in edges
            if edge.get("source") in confirmed_ids and edge.get("target") in confirmed_ids
        ]
        return {
            "scores": story_scores(
                scenario["story"],
                confirmed_ids,
                confirmed_edges,
                packet,
                resolution_expected_ids=ids,
                expected_project_id=scenario["project_id"],
            ),
            "raw_candidate_ids": sorted(ids),
            "divergences": divergences,
        }

    async def run_story_scenario(self, scenario: dict[str, Any]) -> dict[str, Any]:
        variants = [
            await self.run_story_variant(scenario, variant)
            for variant in scenario["query_variants"]
        ]
        return {
            "scenario_id": scenario["scenario_id"],
            "kind": "story",
            "variants": variants,
            "oracle_diagnostic": await self._run_story_oracle(scenario),
        }

    async def run_corpus(self, scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results = []
        for scenario in scenarios:
            if "story" in scenario:
                results.append(await self.run_story_scenario(scenario))
            else:
                results.append(await self.run_000055REDACTED(scenario))
        return results


def load_corpus(path: Path) -> list[dict[str, Any]]:
    scenarios = []
    scenario_ids: set[str] = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        scenario = json.loads(line)
        for field in ("scenario_id", "anchor_decision"):
            if field not in scenario:
                raise ValueError(f"{path}:{line_no}: missing required field {field!r}")
        scenario_id = scenario["scenario_id"]
        if not isinstance(scenario_id, str) or not SLUG_PATTERN.fullmatch(scenario_id):
            raise ValueError(f"{path}:{line_no}: scenario_id must be a kebab-case slug")
        if scenario_id in scenario_ids:
            raise ValueError(f"{path}:{line_no}: duplicate scenario_id {scenario_id!r}")
        scenario_ids.add(scenario_id)
        if "story" in scenario:
            if not scenario.get("project_id"):
                raise ValueError(f"{path}:{line_no}: story scenario requires project_id")
            variants = scenario.get("query_variants")
            if not isinstance(variants, list) or not variants:
                raise ValueError(f"{path}:{line_no}: story scenario requires query_variants")
            variant_ids: set[str] = set()
            for index, variant in enumerate(variants, 1):
                for field in ("variant_id", "query"):
                    if field not in variant:
                        raise ValueError(
                            f"{path}:{line_no}: query_variants[{index}] "
                            f"missing required field {field!r}"
                        )
                variant_id = variant["variant_id"]
                if not isinstance(variant_id, str) or not SLUG_PATTERN.fullmatch(variant_id):
                    raise ValueError(
                        f"{path}:{line_no}: query_variants[{index}].variant_id "
                        "must be a kebab-case slug"
                    )
                if variant_id in variant_ids:
                    raise ValueError(f"{path}:{line_no}: duplicate variant_id {variant_id!r}")
                variant_ids.add(variant_id)
            if not scenario["story"].get("roles"):
                raise ValueError(f"{path}:{line_no}: story.roles must not be empty")
        elif "expected_trace" not in scenario:
            raise ValueError(f"{path}:{line_no}: missing required field 'expected_trace'")
        scenarios.append(scenario)
    return scenarios


async def amain(args: argparse.Namespace) -> int:
    corpus_path = Path(args.corpus)
    scenarios = load_corpus(corpus_path)
    story_projects = {scenario["project_id"] for scenario in scenarios if "story" in scenario}
    if len(story_projects) > 1:
        print("error: one run cannot mix story project_ids", file=sys.stderr)
        return 2
    corpus_project = next(iter(story_projects), None)
    if args.project and corpus_project and args.project != corpus_project:
        print("error: --project does not match story corpus project_id", file=sys.stderr)
        return 2
    run_project = args.project or corpus_project
    runner = TraceRunner(args.rka_url, run_project)
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

    trace_results = [result for result in results if result.get("kind") != "story"]
    story_results = [
        variant
        for result in results
        if result.get("kind") == "story"
        for variant in result["variants"]
    ]
    summary = {
        "meta": {
            "corpus": corpus_path.name,
            "corpus_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
            "rka_url": args.rka_url,
            "project_filter": run_project,
        },
        "aggregate": aggregate(trace_results) if trace_results else None,
        "story_aggregate": aggregate_story(story_results) if story_results else None,
    }
    (out_dir / "metrics.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary["story_aggregate"] or summary["aggregate"], indent=2))
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
