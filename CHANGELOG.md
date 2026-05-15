# Changelog

All notable changes to RKA are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) + semver.

## [2.4.0] — 2026-05-15

### ⚠ BREAKING CHANGES

- **`/api/capabilities` no longer returns the `llm` field.** The response
  is now `{"embedding": {available, reason_unavailable}}` — top-level
  `llm` is absent (not null, not `{available: false}`, gone). Any client
  that read `response.capabilities.llm` before v2.4.0 must update.
  Locked by a regression test in
  `tests/test_api/test_capabilities_route.py`. Rationale: PI directive
  `jrn_01KRNZBS50K250HHHHEC58E4GC` ratified Interpretation A of the
  LLM-capability removal — service code preserved, user-facing surface
  removed.
- **`web/src/hooks/useLLM.ts` and `web/src/pages/Notebook.tsx` are
  deleted.** The Settings page's LLM config card is replaced with a new
  Embeddings card; LLM types are removed from `web/src/api/types.ts`
  and LLM methods from `web/src/api/client.ts`. Server-side
  `rka/infra/llm.py`, `rka/api/routes/llm.py`, and the `rka_ask` /
  `rka_generate_summary` MCP tools are PRESERVED for future re-wiring
  through the orchestrator's Claude Code SDK.
- **`docker-compose.yml` no longer carries `RKA_LLM_*` env var
  references** (commented or active). `RKA_EMBEDDINGS_ENABLED: "true"`
  is set explicitly on both services.

### Added

- **Pluggable embedding backends.** Three concrete implementations
  behind the `EmbeddingBackend` Protocol:
  - **FastEmbed** (local ONNX, default; nomic-768 baseline)
  - **OpenAI-compat HTTP** (OpenAI API, LM Studio, vLLM, Together,
    Anthropic-via-shim — whichever the `base_url` points at; `api_key`
    optional)
  - **Ollama** (singular-prompt `/api/embeddings`; not the
    list-wrapped OpenAI shape)
- **Persistent embedding config at `/data/embedding_config.json`**
  (file-mode 0600, atomic write via tmp+rename, pre-flight backup to
  `embedding_config.backup.json` on every save).
- **REST API for embedding config:**
  - `GET /api/config/embedding` — current config with `api_key`
    redacted to `"***"`
  - `PUT /api/config/embedding` — validate + test + persist; returns
    202 + `{job_id, status_url}` if backfill kicked off, 200 if only
    `api_key` changed
  - `POST /api/config/embedding/test` — probe without persisting;
    returns `{ok, detail, detected_dim, latency_ms}`
  - `GET /api/config/embedding/backfill/status?job_id=…` — polling
    endpoint for the UI progress bar
  - 422 error mapping (Affordance G pattern):
    `{"error": "embedding_config_invalid", "detail": ..., "hint": ...}`
- **Migration 022 (`022_dim_flex_vec_claims.sql`)** — adds
  `claims.embedding_pending` column + partial index; flags every
  existing claim as pending so the configured backend re-embeds them.
- **`rka/services/embedding_reshape.py`** — drops + recreates the
  `vec_claims` virtual table at a config-driven dim. Runs on app
  startup (only when the dim has actually changed) and on
  PUT-with-dim-change.
- **`rka/services/embedding_backfill.py:BackfillService`** — iterates
  pending claims in `id`-ascending order, embeds in batches (default
  32), writes vec_claims rows, clears the flag. Resumable across
  container restarts. Per-claim failures keep the flag for retry;
  batch-level embed failures mark the job state=`failed`.
- **Web UI Settings page → Embeddings tab.** Backend dropdown,
  conditional fields per backend, **Test connection** button,
  confirmation modal for **Save & re-embed**, progress bar polling
  the status endpoint every ~1500 ms. The 422 hint for corrupt config
  renders verbatim from the server.
- **First-run banner.** Dismissible "Semantic search is enabled"
  banner with a link to Settings → Embeddings; dismissal persists in
  `localStorage` (`rka_first_run_banner_dismissed_v2_4`).
- **First-run startup hook.** When `/data/embedding_config.json` is
  absent, app startup persists `DEFAULT_CONFIG` (fastembed + nomic-768)
  via the standard `save_config` path so the config file exists from
  the very first request.
- **Reconcile-dim guard.** Each backend's production `embed()` path
  calls `reconcile_dim(self._dim, observed)` — raises
  `EmbeddingConfigError` on real drift; preserves the legitimate
  populate-from-zero path used by `test_connection()`. Replaces
  silent `self._dim = len(vec)` mutation that previously masked
  config-vs-server-dim divergence.
- **`docs/embedding_backends.md`** — full backend reference: matrix,
  switching procedure, latency table, troubleshooting (LM Studio
  connect-refused, dim mismatch, bind-mount + 0600 caveat).
- **`CHANGELOG.md`** — this file.

### Changed

- `embeddings_enabled` config default flipped from `False` to `True`.
  Override via `RKA_EMBEDDINGS_ENABLED=false` env var if you really
  want the in-process EmbeddingService disabled.
- `EmbeddingService` keeps the same public surface (`embed`,
  `embed_document`, `embed_batch`, `store_embedding`, …) but the work
  is dispatched to a swappable `EmbeddingBackend` chosen at
  construction time. Legacy `EmbeddingService(model_name=...)` calls
  still work and default to FastEmbed.
- `rka_get_status` MCP formatter renders the capabilities LLM line
  conditionally (`if "llm" in caps`) so it gracefully omits it now and
  re-appears if Phase 2 puts the field back.

### Preserved (deliberate non-removals)

- `rka/infra/llm.py`, `rka/api/routes/llm.py` server modules
- `rka_ask`, `rka_generate_summary` MCP tools (graceful no-op when LLM
  unavailable, which is the new default)
- Background enrichment paths in `rka/services/worker.py` (bookkeeper
  invariant: `git diff main -- rka/services/worker.py` is empty across
  every Mission D commit)
- `enrichment_status` column on entries
- LLM-dependent web pages outside Notebook (Timeline, ContextInspector)
  — none imported `useLLM` directly and continue to render unchanged

### Mission reference

- Mission: `mis_01KRNYPVB8N3HDMZ9HK9HM3TB0`
- Motivating decision: `dec_01KRNYJ966H6W4REMK2ZJY2Y9R`
- LLM-removal refinement: `jrn_01KRNZBS50K250HHHHEC58E4GC`
- Mid-mission gate ratification: `dec_01KRP0WFMXAF0TQN6RDXY65WEX`
- Working branch: `feat/v2.4-pluggable-embeddings` (from `main@42e04c6`)
- Test suite at release: 599 passing (511 baseline + 88 mission-D tests)
