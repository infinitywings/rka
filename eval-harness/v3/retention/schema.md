# Eval-v3 Track — directive/evidence retention (fade) benchmark

Question: **do directives and evidence planted early survive context
growth?** RKA's bet is that retention should not depend on the context
window at all — seeded knowledge lives in the store and is re-retrieved.
Each scenario plants items, grows a working transcript, and probes at
increasing context distances under three context-assembly policies (arms):

| Arm | Context given to the model at each probe |
|---|---|
| `rka` | Context retrieved from a live RKA instance (`/api/search` with the probe query) — the planted items must have been ingested into the project under test. |
| `full_context` | The seeds plus the entire transcript so far (plain long-chat baseline). |
| `rag` | Top-k lexically-scored transcript chunks (naive RAG baseline). |

The model and completion backend are injected (litellm by default, matching
`verify_provenance.py`'s judge convention: set `RKA_LLM_MODEL`). The scorer
is mechanical, so runs are reproducible; add a judged pass for nuanced
compliance later if needed.

## Scenario format (`scenarios.jsonl`, one JSON object per line)

| Field | Type | Description |
|---|---|---|
| `scenario_id` | slug | Stable identifier. |
| `seeded_items` | array | Items planted at distance 0. Each: `{"item_id", "kind": "directive"\|"evidence", "text"}` — `text` is what enters the transcript (and, for the `rka` arm, what must be ingested as a `pi_instruction`/finding beforehand). |
| `filler_tasks` | array | Tasks that grow the context: `{"prompt", "canned_response"?}`. When `canned_response` is present the runner uses it verbatim (deterministic, no tokens spent); otherwise the completer generates it. |
| `probes` | array | `{"probe_id", "target_item": item_id, "after_tokens": int, "prompt", "expect": Expectation}` — fired once the transcript passes `after_tokens` (approximated as chars/4). |

`Expectation` (all fields optional; a probe passes when every present check passes):

| Field | Check |
|---|---|
| `must_include` | Every term appears in the response (case-insensitive). |
| `must_not_include` | No term appears — e.g. the stale value after a pivot, or the action a directive forbids. |
| `expected_citations` | Every entity id appears (provenance-correct recall; mainly meaningful for the `rka` arm). |
| `numeric` | `{"value": float, "tolerance": float}` — some number in the response is within tolerance (guards against confidently-wrong specifics). |

## Outputs

Per probe × arm: pass/fail with per-check detail and the context distance at
firing. Aggregated: **retention curve** — pass rate per arm per distance
bucket — plus per-kind (directive vs evidence) breakdown. The headline chart
is retention vs. distance per arm: flat for `rka`, decaying for the
baselines, if the thesis holds.

## Honest-run requirements

- The same completer/model serves all arms of a scenario.
- For the `rka` arm, ingest the seeded items into a disposable project first
  (`rka` REST or MCP), so retrieval is exercised for real — never paste them
  into the probe prompt directly.
- `after_tokens` is approximate (chars/4); report bucket edges, not
  false-precision token counts.
- Filler must be topically adjacent to the seeds (same research area) or the
  RAG baseline wins too easily; the example corpus shows the pattern.
