#!/usr/bin/env python3
"""Runner for the retention (fade) benchmark.

Grows a working transcript from a scenario's filler tasks and fires
probes at configured context distances under three context-assembly
policies (arms): `rka` (retrieval from a live RKA instance),
`full_context` (plain long-chat), and `rag` (naive lexical top-k over
the transcript). See schema.md.

The completion backend is an injected callable `complete(system, prompt)
-> str`; `make_litellm_completer()` builds the default from RKA_LLM_MODEL
(litellm, matching verify_provenance.py's judge convention). The RKA arm
talks REST via httpx with an injectable transport, so everything is
testable offline.

Usage:
    python eval-harness/v3/retention/runner.py \
        --corpus eval-harness/v3/retention/scenarios.jsonl \
        --arms full_context,rag,rka \
        --rka-url http://localhost:9712 --project prj_... \
        --out-dir eval-harness/v3/retention/results
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

import httpx

_V3_DIR = Path(__file__).resolve().parent.parent
if str(_V3_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_V3_DIR.parent))

from v3.retention.scoring import retention_curve, score_probe  # noqa: E402

Completer = Callable[[str, str], str]

SYSTEM_PROMPT = (
    "You are a research assistant continuing an ongoing project session. "
    "Answer from the provided context; follow any standing directives it "
    "contains; cite entity ids when the context provides them."
)

CHUNK_CHARS = 1_000
RAG_TOP_K = 5


def approx_tokens(text: str) -> int:
    return len(text) // 4


DEFAULT_TIMEOUT_S = 1_800


def make_litellm_completer(
    model: str | None = None, timeout_s: float | None = None
) -> Completer | None:
    """Default completer via litellm (RKA_LLM_MODEL), or None if unavailable.

    ``timeout_s`` guards long-context probes: litellm's own default (600 s) is
    below the prefill time of a 35k-token prompt on local hardware, and a
    timeout there aborts the whole run.
    """
    resolved = model or os.environ.get("RKA_LLM_MODEL")
    if not resolved:
        return None
    try:
        import litellm  # optional dependency ([llm] extra)
    except ImportError:
        return None

    budget = (
        timeout_s
        if timeout_s is not None
        else float(os.environ.get("RKA_LLM_TIMEOUT", DEFAULT_TIMEOUT_S))
    )

    def complete(system: str, prompt: str) -> str:
        response = litellm.completion(
            model=resolved,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            timeout=budget,
        )
        return response["choices"][0]["message"]["content"] or ""

    return complete


def lexical_top_chunks(transcript: str, query: str, k: int = RAG_TOP_K) -> list[str]:
    """Naive RAG baseline: token-overlap-scored transcript chunks."""
    chunks = [
        transcript[i : i + CHUNK_CHARS] for i in range(0, len(transcript), CHUNK_CHARS)
    ]
    query_tokens = set(query.lower().split())
    scored = sorted(
        ((len(query_tokens & set(chunk.lower().split())), index, chunk)
         for index, chunk in enumerate(chunks)),
        key=lambda item: (-item[0], item[1]),
    )
    return [chunk for score, _, chunk in scored[:k] if score > 0]


class RetentionRunner:
    def __init__(
        self,
        completer: Completer,
        rka_url: str | None = None,
        project_id: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._complete = completer
        self._project_id = project_id
        self._client = (
            httpx.AsyncClient(
                base_url=rka_url.rstrip("/"), timeout=60.0, transport=transport
            )
            if rka_url
            else None
        )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def _rka_context(self, query: str, divergences: list[str]) -> str:
        if self._client is None:
            divergences.append("rka: no --rka-url configured")
            return ""
        params = {"project_id": self._project_id} if self._project_id else {}
        try:
            response = await self._client.post(
                "/api/search", json={"query": query, "limit": 10}, params=params
            )
        except httpx.HTTPError as exc:
            divergences.append(f"rka search: transport error {exc!r}")
            return ""
        if response.status_code >= 400:
            divergences.append(f"rka search: HTTP {response.status_code}")
            return ""
        try:
            return json.dumps(response.json(), indent=1)
        except ValueError:
            divergences.append("rka search: non-JSON body")
            return ""

    async def _assemble_context(
        self,
        arm: str,
        seeds_text: str,
        transcript: str,
        probe_prompt: str,
        divergences: list[str],
    ) -> str:
        if arm == "full_context":
            return f"{seeds_text}\n\n{transcript}"
        if arm == "rag":
            chunks = lexical_top_chunks(seeds_text + "\n" + transcript, probe_prompt)
            return "\n---\n".join(chunks)
        if arm == "rka":
            # Seeds are NOT pasted in: they must come back through retrieval.
            return await self._rka_context(probe_prompt, divergences)
        raise ValueError(f"unknown arm: {arm}")

    async def run_000055REDACTED(
        self, scenario: dict[str, Any], arms: list[str]
    ) -> list[dict[str, Any]]:
        seeds_text = "\n\n".join(
            f"[{item['kind']} {item['item_id']}] {item['text']}"
            for item in scenario["seeded_items"]
        )
        kinds = {item["item_id"]: item["kind"] for item in scenario["seeded_items"]}
        pending = sorted(scenario["probes"], key=lambda p: p["after_tokens"])

        results: list[dict[str, Any]] = []
        transcript = ""
        fired: set[str] = set()

        async def fire(probe: dict[str, Any]) -> None:
            distance = approx_tokens(seeds_text) + approx_tokens(transcript)
            for arm in arms:
                divergences: list[str] = []
                context = await self._assemble_context(
                    arm, seeds_text, transcript, probe["prompt"], divergences
                )
                try:
                    response = self._complete(
                        SYSTEM_PROMPT, f"Context:\n{context}\n\nTask: {probe['prompt']}"
                    )
                except Exception as exc:  # completion backends fail in many ways
                    # A dead completion is a failed probe, not a dead run: the
                    # remaining arms and probes still carry information.
                    divergences.append(f"{arm} completion: {type(exc).__name__}: {exc}")
                    response = ""
                score = score_probe(probe["expect"], response)
                results.append(
                    {
                        "scenario_id": scenario["scenario_id"],
                        "probe_id": probe["probe_id"],
                        "arm": arm,
                        "kind": kinds.get(probe["target_item"], "unknown"),
                        "distance_tokens": distance,
                        "passed": score["passed"],
                        "checks": score["checks"],
                        "divergences": divergences,
                        "response_excerpt": response[:400],
                    }
                )
            fired.add(probe["probe_id"])

        for task in scenario.get("filler_tasks", []):
            reply = task.get("canned_response") or self._complete(
                SYSTEM_PROMPT, task["prompt"]
            )
            transcript += f"\n\nUSER: {task['prompt']}\nASSISTANT: {reply}"
            for probe in pending:
                if (
                    probe["probe_id"] not in fired
                    and approx_tokens(transcript) >= probe["after_tokens"]
                ):
                    await fire(probe)

        for probe in pending:  # anything the filler never reached fires at the end
            if probe["probe_id"] not in fired:
                await fire(probe)
        return results


def load_corpus(path: Path) -> list[dict[str, Any]]:
    scenarios = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        scenario = json.loads(line)
        for field in ("scenario_id", "seeded_items", "probes"):
            if field not in scenario:
                raise ValueError(f"{path}:{line_no}: missing required field {field!r}")
        scenarios.append(scenario)
    return scenarios


async def amain(args: argparse.Namespace) -> int:
    completer = make_litellm_completer(args.model, args.timeout)
    if completer is None:
        print(
            "error: no completion backend — set RKA_LLM_MODEL (and install "
            "the [llm] extra) or pass --model",
            file=sys.stderr,
        )
        return 2

    corpus_path = Path(args.corpus)
    scenarios = load_corpus(corpus_path)
    arms = args.arms.split(",")
    runner = RetentionRunner(completer, args.rka_url, args.project)
    try:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        probes_path = out_dir / "probes.json"
        all_results: list[dict[str, Any]] = []
        for scenario in scenarios:
            all_results.extend(await runner.run_000055REDACTED(scenario, arms))
            # flush after every scenario: a later failure must not erase
            # probes that already completed
            probes_path.write_text(
                json.dumps(all_results, indent=2) + "\n", encoding="utf-8"
            )
    finally:
        await runner.close()
    summary = {
        "meta": {
            "corpus": corpus_path.name,
            "corpus_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
            "arms": arms,
            "model": args.model or os.environ.get("RKA_LLM_MODEL"),
        },
        "curve": retention_curve(all_results),
    }
    (out_dir / "metrics.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary["curve"], indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--arms", default="full_context,rag,rka")
    parser.add_argument("--rka-url", help="required for the rka arm")
    parser.add_argument("--project", help="RKA project_id for the rka arm")
    parser.add_argument("--model", help="litellm model id (default: RKA_LLM_MODEL)")
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help=f"per-completion timeout in seconds (default: RKA_LLM_TIMEOUT or {DEFAULT_TIMEOUT_S})",
    )
    parser.add_argument("--out-dir", default=str(Path(__file__).parent / "results"))
    args = parser.parse_args(argv)
    return asyncio.run(amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
