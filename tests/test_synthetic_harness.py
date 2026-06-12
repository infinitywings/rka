"""Synthetic-corpus stress harness — CI-safe integration test.

Provenance: ported from /tmp/rka-eval/synth (generate.py + stress_test.py),
eval-v3, 2026-06-12. The generator (eval-harness/synthetic/corpus.py) plants
a fully synthetic research arc through the REST API — needles, supersede
chains, a contradiction, a retraction, provenance chains, tag cohorts, and
deliberate edge cases (unicode, FTS-hostile punctuation, oversized entry,
hub node) — and this module grades retrieval/graph/context mechanically
against that planted ground truth. No agents, no LLM, no live server: the
app runs in-process via ASGITransport with LLM + embeddings disabled.

Regression classes the ancestor caught on 2026-06-11/12: the FTS OR/AND
sanitizer bug, missing supersedes graph edges, knowledge-pack re-keying rot,
and context bundles burying pinned PI directives.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from rka.api.app import create_app
from rka.config import RKAConfig
from rka.services.reindex import reindex_fts

# eval-harness/ has a hyphen (not an importable package name); load the
# corpus generator by file path instead.
_CORPUS_PATH = (
    Path(__file__).resolve().parent.parent / "eval-harness" / "synthetic" / "corpus.py"
)
_spec = importlib.util.spec_from_file_location("rka_synthetic_corpus", _CORPUS_PATH)
assert _spec is not None and _spec.loader is not None
corpus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(corpus)

ID_RE = re.compile(r"(?:jrn|dec|lit|mis|clm|ecl|chk)_[0-9A-Z]{26}")

# Report-context probe (copied from stress_test.py test_report_context).
REPORT_DESCRIPTION = (
    "A report on the project's application-layer integrity findings for FUOTA: "
    "the scope and hardware constraints, the threat model, the fragment-injection "
    "and replay results, the battery attack, and the current signature decision."
)
REPORT_ANGLES = [
    "fragment injection", "replay multicast", "battery exhaustion",
    "signature scheme", "threat model", "FUOTA scope",
]

# Raw FTS-hostile queries (copied from stress_test.py test_edge_cases) —
# each one must return 200, never a 500 from the FTS layer.
FTS_HOSTILE_QUERIES = [
    'v2.0-rc1 AND (rollback OR NOT signed)',
    'C++ a*b "quoted"',
    '"""',
    'NEAR(x y)',
]

# Share one event loop across the module so the module-scoped harness
# fixture (app lifespan + generated corpus) is usable from every test.
pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def harness(tmp_path_factory: pytest.TempPathFactory):
    """In-process app + synthetic corpus, generated once per module."""
    project_dir = tmp_path_factory.mktemp("synthetic_harness")
    config = RKAConfig(
        project_dir=project_dir,
        db_path=Path("synth.db"),
        llm_enabled=False,
        embeddings_enabled=False,
    )
    app = create_app(config)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            state: dict[str, str | None] = {"pid": None}

            def headers() -> dict[str, str]:
                # The project-create call itself runs before a pid exists and
                # needs no header; everything after is project-scoped.
                return {"X-RKA-Project": state["pid"]} if state["pid"] else {}

            async def post(path: str, body: dict) -> dict:
                r = await client.post(path, json=body, headers=headers())
                r.raise_for_status()
                out = r.json()
                if path == "/api/projects" and state["pid"] is None:
                    state["pid"] = out["id"]
                return out

            async def put(path: str, body: dict) -> dict:
                r = await client.put(path, json=body, headers=headers())
                r.raise_for_status()
                return r.json()

            async def get(path: str) -> dict:
                r = await client.get(path, headers=headers())
                r.raise_for_status()
                return r.json()

            gt = await corpus.generate(post, put)

            # Rebuild the FTS indexes from source tables (exercises the
            # v2.7.0.7 recovery path and guarantees index/source parity
            # before grading retrieval).
            report = await reindex_fts(app.state.db, project_id=gt["project_id"])
            assert report.ok, f"reindex_fts failures: {report.failures}"

            yield SimpleNamespace(
                app=app, client=client, gt=gt,
                post=post, put=put, get=get, headers=headers,
            )
    finally:
        await lifespan.__aexit__(None, None, None)


async def _search(h, query: str, limit: int = 10) -> list[str]:
    hits = await h.post("/api/search", {"query": query, "limit": limit})
    return [hit["entity_id"] for hit in hits]


def _ids_in(obj) -> set[str]:
    """All entity ids mentioned anywhere in a JSON-serializable response."""
    return set(ID_RE.findall(json.dumps(obj)))


async def test_write_path_integrity(harness):
    """Entity counts, supersedes edges, contradicts edge, superseded_by FK."""
    gt = harness.gt
    db = harness.app.state.db
    pid = gt["project_id"]

    # Mission reports auto-materialize their findings as journal entries
    # (MissionService._materialize_report), so the journal table holds the
    # generator's notes plus those report-derived rows.
    expected = {
        "journal": gt["counts"]["journal"] + gt["counts"]["journal_from_reports"],
        "decisions": gt["counts"]["decisions"],
        "literature": gt["counts"]["literature"],
        "missions": gt["counts"]["missions"],
    }
    for table, want in expected.items():
        row = await db.fetchone(
            f"SELECT COUNT(*) AS n FROM {table} WHERE project_id = ?", [pid]
        )
        assert row["n"] == want, f"{table}: {row['n']} rows in DB vs {want} expected"

    row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM entity_links "
        "WHERE project_id = ? AND link_type = 'supersedes'",
        [pid],
    )
    assert row["n"] == len(gt["supersede_chains"]) == 2, (
        f"expected 2 supersedes entity_links, found {row['n']}"
    )

    row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM claim_edges "
        "WHERE project_id = ? AND relation = 'contradicts'",
        [pid],
    )
    assert row["n"] == 1, f"expected 1 contradicts claim_edge, found {row['n']}"

    dec_chain = next(c for c in gt["supersede_chains"] if c["kind"] == "decision")
    old = await harness.get(f"/api/decisions/{dec_chain['old']}")
    assert old["status"] == "superseded"
    assert old["superseded_by"] == dec_chain["new"]


async def test_needle_retrieval(harness):
    """Every non-synthesis needle is in search top-10 for its question."""
    needles = [n for n in harness.gt["needles"] if n["category"] != "synthesis"]
    assert needles
    missed = []
    for n in needles:
        got = await _search(harness, n["question"], 10)
        if n["entity_id"] not in got:
            missed.append(f"{n['qid']} ({n['category']}): {n['question'][:60]}")
    assert not missed, f"needle recall@10 < 1.0; missed: {missed}"


async def test_supersession_correctness(harness):
    """Current entity surfaces at-or-above the stale one; edge is traversable."""
    for ch in harness.gt["supersede_chains"]:
        got = await _search(harness, ch["question"], 10)
        assert ch["new"] in got, (
            f"{ch['kind']} chain: current entity ({ch['current_fact']}) "
            f"not in top-10 for {ch['question']!r}"
        )
        new_idx = got.index(ch["new"])
        old_idx = got.index(ch["old"]) if ch["old"] in got else len(got)
        assert new_idx <= old_idx, (
            f"{ch['kind']} chain: stale entity ({ch['stale_fact']}) ranked "
            f"@{old_idx} above current ({ch['current_fact']}) @{new_idx}"
        )
        ego = await harness.get(f"/api/graph/ego/{ch['old']}")
        edge_types = {e.get("link_type") for e in ego.get("edges", [])}
        assert "supersedes" in edge_types, (
            f"{ch['kind']} chain: no supersedes edge in ego graph of {ch['old']}"
        )


async def test_contradiction_surfacing(harness):
    """Both sides of the contradiction reachable via search or multi-hop."""
    for c in harness.gt["contradictions"]:
        got = await _search(harness, c["question"], 10)
        both_search = c["a"] in got and c["b"] in got
        out = await harness.post(
            "/api/graph/multi-hop",
            {"query": c["question"], "max_nodes": 30, "max_depth": 2},
        )
        reached = _ids_in(out)
        both_graph = c["a"] in reached and c["b"] in reached
        assert both_search or both_graph, (
            f"contradiction not surfaced: search={both_search} multihop={both_graph}"
        )


async def test_chain_traversal(harness):
    """Multi-hop from the first node of each known chain reaches every node."""
    for ch in harness.gt["chains"]:
        out = await harness.post(
            "/api/graph/multi-hop",
            {"query": ch.get("question", ch["name"]), "seeds": [ch["path"][0]],
             "max_nodes": 50, "max_depth": 3},
        )
        reached = _ids_in(out)
        missing = [nid for nid in ch["path"] if nid not in reached]
        assert not missing, (
            f"chain {ch['name']}: coverage "
            f"{len(ch['path']) - len(missing)}/{len(ch['path'])}, unreachable: {missing}"
        )


async def test_report_context_collection(harness):
    """report-context recall over the curated writeup-arc cohort >= 0.85.

    The ancestor measured 1.0 on the 60-filler corpus; 0.85 (one miss out of
    the 8-entity cohort) leaves headroom for the CI corpus shrink.
    """
    cohort = set(harness.gt["tag_cohorts"]["writeup-arc"])
    out = await harness.post(
        "/api/graph/report-context",
        {"description": REPORT_DESCRIPTION, "angle_queries": REPORT_ANGLES, "max_nodes": 60},
    )
    got = {n["id"] for n in out["nodes"]}
    recall = len(got & cohort) / len(cohort)
    assert recall >= 0.85, (
        f"writeup-arc cohort recall {recall:.2f} < 0.85; missed: {sorted(cohort - got)}"
    )


async def test_context_bundle_pinning(harness):
    """Pinned PI directives lead the session-start context bundle."""
    pi_dirs = harness.gt["tag_cohorts"]["pi-directive"]
    assert len(pi_dirs) == 2
    out = await harness.post("/api/context", {})
    sources = out.get("sources", [])
    front = sources[:4]
    for jid in pi_dirs:
        assert jid in front, (
            f"PI directive {jid} not in the first 4 bundle positions "
            f"(found at {sources.index(jid) if jid in sources else 'MISSING'})"
        )


async def test_fts_hostile_queries_do_not_500(harness):
    """Raw FTS5 operator soup must degrade gracefully, never 500."""
    for q in FTS_HOSTILE_QUERIES:
        r = await harness.client.post(
            "/api/search", json={"query": q, "limit": 5}, headers=harness.headers()
        )
        assert r.status_code == 200, f"hostile query {q!r} -> {r.status_code}: {r.text[:200]}"


async def test_edge_needles(harness):
    """Unicode + FTS-hostile needles are still retrievable in top-10."""
    edge_needles = [n for n in harness.gt["needles"] if n["category"].startswith("edge")]
    assert edge_needles
    for n in edge_needles:
        got = await _search(harness, n["question"], 10)
        assert n["entity_id"] in got, (
            f"{n['qid']} ({n['category']}): {n['question'][:60]!r} missed its needle"
        )
