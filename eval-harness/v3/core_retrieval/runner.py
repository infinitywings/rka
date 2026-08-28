"""Run the provider-free RKA Core retrieval baseline.

The benchmark plants the existing frozen synthetic research corpus into a
temporary SQLite database and exercises the public REST surfaces in process.
Corpus construction, migrations, and FTS rebuilding are deliberately outside
the timed region.  The latency thresholds are broad regression tripwires, not
hardware-independent service-level objectives.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import math
import os
import platform
import sqlite3
import subprocess
import sys
import tempfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns
from typing import Any

import httpx

_RUNNER_PATH = Path(__file__).resolve()
_REPO_ROOT = _RUNNER_PATH.parents[3]
_EVAL_HARNESS_DIR = _RUNNER_PATH.parents[2]
for _path in (_REPO_ROOT, _EVAL_HARNESS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rka.api.app import create_app  # noqa: E402
from rka.config import RKAConfig  # noqa: E402
from rka.infra.database import Database  # noqa: E402
from rka.infra.ids import generate_id  # noqa: E402
from rka.services.reindex import reindex_fts  # noqa: E402
from v3.tracing.runner import (  # noqa: E402
    extract_graph_edges,
    extract_graph_node_ids,
    extract_search_entity_ids,
)

_CORPUS_PATH = _EVAL_HARNESS_DIR / "synthetic" / "corpus.py"
_spec = importlib.util.spec_from_file_location("rka_core_baseline_corpus", _CORPUS_PATH)
assert _spec is not None and _spec.loader is not None
corpus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(corpus)

DEFAULT_THRESHOLDS = {
    "entity_recall_at_k_min": 1.0,
    "linked_node_recall_min": 1.0,
    "linked_edge_recall_min": 1.0,
    "linked_currentness_coverage_min": 1.0,
    "foreign_hits_max": 0,
    "search_p95_ms_max": 500.0,
    "linked_neighborhood_p95_ms_max": 1000.0,
}


def _percentile(values: list[float], percentile: float) -> float:
    """Nearest-rank percentile, suitable for small benchmark samples."""
    if not values:
        raise ValueError("cannot compute a percentile of an empty sample")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _latency_summary(values: list[float]) -> dict[str, float]:
    return {
        "p50_ms": round(_percentile(values, 0.50), 3),
        "p95_ms": round(_percentile(values, 0.95), 3),
        "max_ms": round(max(values), 3),
    }


def _reciprocal_rank(result_ids: list[str], expected_ids: set[str]) -> float:
    for rank, entity_id in enumerate(result_ids, start=1):
        if entity_id in expected_ids:
            return 1.0 / rank
    return 0.0


def _edge_matches(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    allowed = set(expected.get("link_types", []))
    if allowed and actual.get("link_type") not in allowed:
        return False
    source = expected["source"]
    target = expected["target"]
    forward = actual.get("source") == source and actual.get("target") == target
    reverse = actual.get("source") == target and actual.get("target") == source
    return forward or (expected.get("direction") == "either" and reverse)


async def _timed_json(call: Callable[[], Awaitable[httpx.Response]]) -> tuple[Any, float]:
    started = perf_counter_ns()
    response = await call()
    elapsed_ms = (perf_counter_ns() - started) / 1_000_000
    response.raise_for_status()
    return response.json(), elapsed_ms


async def _warm(call: Callable[[], Awaitable[httpx.Response]], count: int) -> None:
    for _ in range(count):
        response = await call()
        response.raise_for_status()


def _evaluate_gates(
    tasks: list[dict[str, Any]],
    neighborhoods: list[dict[str, Any]],
    currency: dict[str, Any],
    isolation: dict[str, Any],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    required_types = {"journal", "claim", "decision", "literature"}
    task_types = {task["entity_type"] for task in tasks}
    checks = {
        "direct_task_coverage": bool(tasks) and task_types == required_types,
        "linked_task_coverage": bool(neighborhoods),
        "entity_recall": all(
            task["recall_at_k"] >= thresholds["entity_recall_at_k_min"]
            for task in tasks
        ),
        "linked_node_recall": all(
            task["node_recall"] >= thresholds["linked_node_recall_min"]
            for task in neighborhoods
        ),
        "linked_edge_recall": all(
            task["edge_recall"] >= thresholds["linked_edge_recall_min"]
            for task in neighborhoods
        ),
        "linked_currentness_coverage": all(
            task["currentness_coverage"]
            >= thresholds["linked_currentness_coverage_min"]
            for task in neighborhoods
        ),
        "project_isolation": (
            isolation["foreign_hits"] <= thresholds["foreign_hits_max"]
            and isolation["foreign_edge_endpoints"]
            <= thresholds["foreign_hits_max"]
        ),
        "foreign_anchor_rejected": isolation["foreign_anchor_nodes"] == 0,
        "decision_current_first": currency["decision_current_first"],
        "decision_currency_visible": currency["decision_currency_visible"],
        "journal_currency_visible": currency["journal_currency_visible"],
        "claim_currency_visible": currency["claim_currency_visible"],
        "superseded_journal_filtered": currency["superseded_journal_filtered"],
        "stale_claim_filtered": currency["stale_claim_filtered"],
        "search_latency": all(
            task["p95_ms"] <= thresholds["search_p95_ms_max"] for task in tasks
        ),
        "linked_neighborhood_latency": all(
            task["p95_ms"] <= thresholds["linked_neighborhood_p95_ms_max"]
            for task in neighborhoods
        ),
    }
    return {"pass": all(checks.values()), "checks": checks}


async def measure_baseline(
    client: httpx.AsyncClient,
    *,
    project_id: str,
    ground_truth: dict[str, Any],
    foreign_ids: list[str],
    repeats: int = 7,
    warmups: int = 1,
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Measure one already-planted corpus through public REST surfaces."""
    if repeats < 1 or warmups < 0:
        raise ValueError("repeats must be positive and warmups cannot be negative")
    thresholds = dict(thresholds or DEFAULT_THRESHOLDS)
    headers = {"X-RKA-Project": project_id}
    foreign_set = set(foreign_ids)
    foreign_hits: set[str] = set()
    foreign_edge_endpoints: set[str] = set()
    task_results: list[dict[str, Any]] = []

    for task in ground_truth["retrieval_tasks"]:
        expected = set(task["expected_ids"])

        def search_call(task: dict[str, Any] = task) -> Awaitable[httpx.Response]:
            return client.post(
                "/api/search",
                headers=headers,
                json={
                    "query": task["query"],
                    "entity_types": [task["entity_type"]],
                    "limit": task["top_k"],
                },
            )

        await _warm(search_call, warmups)
        latencies: list[float] = []
        recalls: list[float] = []
        reciprocal_ranks: list[float] = []
        last_ids: list[str] = []
        for _ in range(repeats):
            payload, elapsed_ms = await _timed_json(search_call)
            ids = extract_search_entity_ids(payload)
            last_ids = ids
            latencies.append(elapsed_ms)
            recalls.append(len(expected & set(ids)) / len(expected))
            reciprocal_ranks.append(_reciprocal_rank(ids, expected))
            foreign_hits.update(foreign_set & set(ids))
        task_results.append(
            {
                "task_id": task["task_id"],
                "entity_type": task["entity_type"],
                "top_k": task["top_k"],
                "expected_count": len(expected),
                "recall_at_k": round(sum(recalls) / len(recalls), 4),
                "mrr": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4),
                "last_result_count": len(last_ids),
                **_latency_summary(latencies),
            }
        )

    neighborhood_results: list[dict[str, Any]] = []
    for task in ground_truth["linked_neighborhood_tasks"]:
        expected_ids = set(task["expected_ids"])
        expected_edges = task["expected_edges"]

        def graph_call(task: dict[str, Any] = task) -> Awaitable[httpx.Response]:
            return client.post(
                "/api/graph/multi-hop",
                headers=headers,
                json={
                    "seeds": [task["seed_id"]],
                    "max_depth": task["max_depth"],
                    "max_nodes": task["max_nodes"],
                },
            )

        await _warm(graph_call, warmups)
        latencies = []
        node_recalls: list[float] = []
        edge_recalls: list[float] = []
        currentness_coverages: list[float] = []
        for _ in range(repeats):
            payload, elapsed_ms = await _timed_json(graph_call)
            node_ids = set(extract_graph_node_ids(payload))
            nodes_by_id = {
                node.get("id"): node
                for node in payload.get("nodes", [])
                if isinstance(node, dict) and node.get("id")
            }
            edges = extract_graph_edges(payload)
            for edge in edges:
                for endpoint in (edge.get("source"), edge.get("target")):
                    if endpoint in foreign_set:
                        foreign_edge_endpoints.add(endpoint)
            latencies.append(elapsed_ms)
            node_recalls.append(len(expected_ids & node_ids) / len(expected_ids))
            edge_recalls.append(
                sum(any(_edge_matches(expected, edge) for edge in edges) for expected in expected_edges)
                / len(expected_edges)
            )
            currentness_coverages.append(
                sum(
                    nodes_by_id.get(entity_id, {})
                    .get("currentness", {})
                    .get("is_current")
                    is True
                    for entity_id in expected_ids
                )
                / len(expected_ids)
            )
            foreign_hits.update(foreign_set & node_ids)
        neighborhood_results.append(
            {
                "task_id": task["task_id"],
                "expected_node_count": len(expected_ids),
                "expected_edge_count": len(expected_edges),
                "node_recall": round(sum(node_recalls) / len(node_recalls), 4),
                "edge_recall": round(sum(edge_recalls) / len(edge_recalls), 4),
                "currentness_coverage": round(
                    sum(currentness_coverages) / len(currentness_coverages), 4
                ),
                **_latency_summary(latencies),
            }
        )

    currency_ids = ground_truth["currency_checks"]
    currency_query = "firmware signature scheme FUOTA design assume"
    decision_response = await client.post(
        "/api/search",
        headers=headers,
        json={"query": currency_query, "entity_types": ["decision"], "limit": 10},
    )
    decision_response.raise_for_status()
    decision_hits = decision_response.json()
    decision_ids = extract_search_entity_ids(decision_hits)
    current_decision = currency_ids["current_decision"]
    old_decision = currency_ids["superseded_decision"]
    current_rank = decision_ids.index(current_decision) if current_decision in decision_ids else None
    old_rank = decision_ids.index(old_decision) if old_decision in decision_ids else None
    by_id = {hit.get("entity_id"): hit for hit in decision_hits if isinstance(hit, dict)}

    all_notes_response = await client.get(
        "/api/notes",
        headers=headers,
        params={"hide_superseded": "false", "limit": 200},
    )
    all_notes_response.raise_for_status()
    all_notes = {
        item["id"]: item
        for item in all_notes_response.json()
        if isinstance(item, dict) and item.get("id")
    }
    notes_response = await client.get(
        "/api/notes",
        headers=headers,
        params={"hide_superseded": "true", "limit": 200},
    )
    notes_response.raise_for_status()
    visible_notes = {
        item["id"] for item in notes_response.json() if isinstance(item, dict) and item.get("id")
    }
    all_claims_response = await client.get(
        "/api/claims",
        headers=headers,
        params={"limit": 200},
    )
    all_claims_response.raise_for_status()
    all_claims = {
        item["id"]: item
        for item in all_claims_response.json()
        if isinstance(item, dict) and item.get("id")
    }
    claims_response = await client.get(
        "/api/claims",
        headers=headers,
        params={"stale": "false", "limit": 200},
    )
    claims_response.raise_for_status()
    current_claims = {
        item["id"] for item in claims_response.json() if isinstance(item, dict) and item.get("id")
    }
    currency = {
        "decision_current_first": bool(
            current_rank is not None and (old_rank is None or current_rank <= old_rank)
        ),
        "decision_currency_visible": bool(
            old_decision in by_id
            and by_id[old_decision].get("status") == "superseded"
            and by_id[old_decision].get("superseded_by") == current_decision
        ),
        "journal_currency_visible": bool(
            currency_ids["current_journal"] in all_notes
            and currency_ids["superseded_journal"] in all_notes
            and all_notes[currency_ids["superseded_journal"]].get("status")
            == "superseded"
            and all_notes[currency_ids["superseded_journal"]].get("superseded_by")
            == currency_ids["current_journal"]
        ),
        "claim_currency_visible": bool(
            currency_ids["current_claim"] in all_claims
            and currency_ids["stale_claim"] in all_claims
            and not all_claims[currency_ids["current_claim"]].get("stale")
            and all_claims[currency_ids["stale_claim"]].get("stale") is True
        ),
        "superseded_journal_filtered": bool(
            currency_ids["current_journal"] in visible_notes
            and currency_ids["superseded_journal"] not in visible_notes
        ),
        "stale_claim_filtered": bool(
            currency_ids["current_claim"] in current_claims
            and currency_ids["stale_claim"] not in current_claims
        ),
        "decision_current_rank": current_rank,
        "decision_superseded_rank": old_rank,
    }

    foreign_anchor_nodes = 0
    if foreign_ids:
        response = await client.post(
            "/api/graph/multi-hop",
            headers=headers,
            json={"seeds": [foreign_ids[0]], "max_depth": 2, "max_nodes": 10},
        )
        response.raise_for_status()
        foreign_anchor_nodes = len(extract_graph_node_ids(response.json()))
    isolation = {
        "foreign_hits": len(foreign_hits),
        "foreign_hit_ids": sorted(foreign_hits),
        "foreign_edge_endpoints": len(foreign_edge_endpoints),
        "foreign_edge_endpoint_ids": sorted(foreign_edge_endpoints),
        "foreign_anchor_nodes": foreign_anchor_nodes,
    }
    gates = _evaluate_gates(
        task_results, neighborhood_results, currency, isolation, thresholds
    )
    return {
        "tasks": task_results,
        "linked_neighborhoods": neighborhood_results,
        "currency": currency,
        "isolation": isolation,
        "thresholds": thresholds,
        "gates": gates,
    }


async def _seed_shadow_project(
    client: httpx.AsyncClient, retrieval_tasks: list[dict[str, Any]]
) -> tuple[str, list[str]]:
    vocabulary = " ".join(task["query"] for task in retrieval_tasks)
    project = await client.post(
        "/api/projects",
        json={"name": "core_retrieval_shadow", "description": "isolation decoy"},
    )
    project.raise_for_status()
    project_id = project.json()["id"]
    headers = {"X-RKA-Project": project_id}
    note = await client.post(
        "/api/notes",
        headers=headers,
        json={
            "content": f"Foreign decoy with overlapping vocabulary: {vocabulary}",
            "type": "note",
            "source": "executor",
            "confidence": "tested",
        },
    )
    note.raise_for_status()
    note_id = note.json()["id"]
    literature = await client.post(
        "/api/literature",
        headers=headers,
        json={"title": vocabulary[:500], "status": "read"},
    )
    literature.raise_for_status()
    decision = await client.post(
        "/api/decisions",
        headers=headers,
        json={
            "question": vocabulary[:500],
            "chosen": "foreign decoy",
            "rationale": "Must never appear in another project's retrieval.",
            "phase": "evaluation",
            "decided_by": "brain",
            "kind": "decision",
            "related_journal": [note_id],
        },
    )
    decision.raise_for_status()
    claim = await client.post(
        "/api/claims",
        headers=headers,
        json={
            "source_entry_id": note_id,
            "claim_type": "result",
            "content": vocabulary,
            "confidence": 0.5,
        },
    )
    claim.raise_for_status()
    return project_id, [
        note_id,
        literature.json()["id"],
        decision.json()["id"],
        claim.json()["id"],
    ]


async def _plant_cross_project_edge(
    db: Database,
    *,
    local_project_id: str,
    local_source_id: str,
    foreign_target_id: str,
) -> None:
    """Plant an imported/corrupt edge whose project stamp and target disagree."""
    await db.execute(
        """INSERT INTO entity_links
           (id, source_type, source_id, link_type, target_type, target_id,
            created_by, project_id)
           VALUES (?, 'decision', ?, 'references', 'decision', ?, 'system', ?)""",
        [
            generate_id("link"),
            local_source_id,
            foreign_target_id,
            local_project_id,
        ],
    )
    await db.commit()


def _git_revision() -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=_REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return {"commit": commit, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


async def run_baseline(*, repeats: int = 7, warmups: int = 1) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="rka-core-retrieval-") as temp_dir:
        config = RKAConfig(
            project_dir=Path(temp_dir),
            db_path=Path("baseline.db"),
            llm_enabled=False,
            embeddings_enabled=False,
        )
        app = create_app(config)
        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://rka-core-baseline"
            ) as client:
                state: dict[str, str | None] = {"project_id": None}

                def headers() -> dict[str, str]:
                    return (
                        {"X-RKA-Project": state["project_id"]}
                        if state["project_id"]
                        else {}
                    )

                async def post(path: str, body: dict[str, Any]) -> dict[str, Any]:
                    response = await client.post(path, headers=headers(), json=body)
                    response.raise_for_status()
                    payload = response.json()
                    if path == "/api/projects" and state["project_id"] is None:
                        state["project_id"] = payload["id"]
                    return payload

                async def put(path: str, body: dict[str, Any]) -> dict[str, Any]:
                    response = await client.put(path, headers=headers(), json=body)
                    response.raise_for_status()
                    return response.json()

                ground_truth = await corpus.generate(post, put)
                shadow_id, foreign_ids = await _seed_shadow_project(
                    client, ground_truth["retrieval_tasks"]
                )
                await _plant_cross_project_edge(
                    app.state.db,
                    local_project_id=ground_truth["project_id"],
                    local_source_id=ground_truth["currency_checks"]["current_decision"],
                    foreign_target_id=foreign_ids[2],
                )
                for project_id in (ground_truth["project_id"], shadow_id):
                    report = await reindex_fts(app.state.db, project_id=project_id)
                    if not report.ok:
                        raise RuntimeError(f"FTS rebuild failed: {report.failures}")
                measured = await measure_baseline(
                    client,
                    project_id=ground_truth["project_id"],
                    ground_truth=ground_truth,
                    foreign_ids=foreign_ids,
                    repeats=repeats,
                    warmups=warmups,
                )
        finally:
            await lifespan.__aexit__(None, None, None)

    source_bytes = _CORPUS_PATH.read_bytes()
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": _git_revision(),
        "corpus_source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "transport": "in-process ASGI",
            "database": "temporary SQLite WAL",
            "embedding_mode": "disabled",
            "llm_mode": "disabled",
            "writer_dependency": False,
            "ci": bool(os.environ.get("CI")),
        },
        "protocol": {
            "warmups_per_task": warmups,
            "repetitions_per_task": repeats,
            "timed_region": "REST request only; corpus build, migrations, and FTS rebuild excluded",
        },
        **measured,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write the full JSON result")
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--check", action="store_true", help="exit nonzero when a gate fails")
    args = parser.parse_args()
    result = asyncio.run(run_baseline(repeats=args.repeats, warmups=args.warmups))
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    print(
        json.dumps(
            {
                "pass": result["gates"]["pass"],
                "tasks": len(result["tasks"]),
                "output": str(args.output) if args.output else None,
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 1 if args.check and not result["gates"]["pass"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
