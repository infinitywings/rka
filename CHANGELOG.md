# Changelog

All notable changes to RKA are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) + semver.

## [2.5.0+desktop] — 2026-05-15 (tag: `v2.5.0-desktop`; release/desktop branch ONLY)

**Release line note.** v2.5.0-desktop ships from the `release/desktop`
branch as a parallel distribution channel for the macOS .app +
multi-client MCP onboarding. Per the motivating decision
`dec_01KRPAVSTJ4H80VXJVN6DQ82WQ`, this release is **NOT merged into main**
— main stays at v2.4.1 + future patches. Users who want the .app + Tauri
shell pick the tagged build; users who deploy via Docker stay on main.

PEP 440 normalization: the Python `version` field is
`2.5.0+desktop` (local-version syntax per PEP 440). The git tag is
`v2.5.0-desktop` — the hyphen form Brain ratified is preserved for the
tag because git tag names have no PEP 440 constraint.

### Added (release/desktop ONLY)

- **macOS .app distribution path** via Tauri shell + PyInstaller binaries.
  The .app launches `rka-serve` as a sidecar subprocess (not embedded
  in-process), pipes its stdout/stderr into a rotating log writer
  (`~/Library/Logs/RKA/server.log`, 10 MB × 5 rotation), and exposes the
  bundled web UI at the configured backend URL.
- **Multi-client MCP onboarding** in the Tauri shell for 7 clients:
  Claude Desktop, Claude Code, Cursor, VSCode-Copilot, Codex CLI, Codex
  Mac App, Antigravity. Per-client detection probes report whether each
  client's config file exists and whether RKA is already merged; users
  toggle which clients to install on; merge writes are atomic with
  pre-flight backup; remove is reversible.
- **Claude Desktop install-assist (D9)** for users who don't have Claude
  Desktop yet — link-only download flow (no auto-install per Mac
  Gatekeeper conventions).
- **Logs panel (D5)** with diagnostic-copy (clipboard) command.
- **Post-install Settings → Embeddings hint (T2)** in
  `packaging/ui-src/src/components/OnboardingPanel.tsx`: after a
  successful MCP merge, render a one-click "Open Settings → Embeddings"
  button pointing at `${backendUrl}/settings`. Lets the user finish
  embedding-backend setup right after MCP onboarding completes.

### Preserved from v2.4.x (no regressions in the merged code)

- v2.4.0's pluggable embedding backends (FastEmbed / OpenAI-compat /
  Ollama) at `Settings → Embeddings` in the web UI
- v2.4.0's first-run banner + persistent `/data/embedding_config.json`
  with file-mode 0600 + atomic write + pre-flight backup
- v2.4.0's BREAKING `/api/capabilities` shape change (`llm` field absent)
- v2.4.1's httpx 600s default timeout + batch-size-8 default + exception-
  class-in-error-message hotfix
- Server-side LLM service code (`rka/infra/llm.py`, `rka/api/routes/llm.py`,
  `rka_ask` / `rka_generate_summary` MCP tools, worker.py enrichment
  paths) — graceful no-op when LLM unavailable

### Branch + merge model (this release)

- Merged main (v2.4.1 @ `2ad536c`) into `release/desktop` at T0 with
  `--no-ff`. ZERO conflict markers — the mission spec's "3 conflict
  files in `web/src/`" prediction was empirically wrong: per-commit
  audit confirmed all 9 D-commits (D1-D9) live entirely in
  `packaging/`, leaving the web UI untouched. Source-trace calibration
  entry filed at `jrn_01KRPB24577087AH2F63F6CRDY`.
- Brain ratified Option B at `dec_01KRPAVSTJ4H80VXJVN6DQ82WQ`: web UI
  Settings.tsx stays Embeddings-only (no Tabs primitive); Tauri shell's
  existing MCP Clients UI at `packaging/ui-src/` is the home for
  per-client onboarding.
- v2.5.0-desktop tag pushed at T8; release/desktop continues to track
  the desktop release line independent of main.

### Test counts at this release

- Cargo: 63/63 in `packaging/tauri` (32 lib unit + 31 integration matrix
  including the 5 D8 verify-path additions). Run via
  `CARGO_TARGET_DIR=/tmp/rka-tauri-target cargo test --release` from
  `packaging/tauri/` to bypass the FuSpace AppleDouble issue at the
  Tauri permissions-scan build step.
- Python: 599+ (v2.4.1 baseline + any v2.4.1 hotfix tests carried in
  via T0 merge).

### Mission reference

- Mission: `mis_01KRPA2YK4HHQ0X90GX2T3GAVH`
- Motivating decision: `dec_01KRP9ZV7XX7WC9PDWRRTGTEE9`
- Prior Notebook-deletion directive: `jrn_01KRP5Q0FJ67V3HMHNJ0FSR02D`
- Mid-mission gate ratification: `dec_01KRPAVSTJ4H80VXJVN6DQ82WQ`
- Spec source-trace calibration: `jrn_01KRPB24577087AH2F63F6CRDY`

---

## [2.4.1] — 2026-05-15

### Fixed

- **`openai_compat` + `ollama` embedding backends: default httpx timeout
  raised from 30s → 600s.** The prior 30s default made local 8B-class
  embedding servers (LM Studio + qwen3-embedding-8b, Ollama + nomic-large
  variants) fail the first backfill batch with `httpx.ReadTimeout` and no
  claims would land. Constructor still accepts `timeout_seconds=...` so
  fast hosted backends can opt back down.
- **`BackfillService` default batch size lowered from 32 → 8.** A 32-text
  batch against an 8B-class model on a single Mac is multiple seconds even
  under ideal conditions; reducing the default lets the first batch
  complete and keeps the polling UI honest. Constructor still accepts
  `batch_size=...` for hosted-API workloads where 32+ is fine.
- **Backfill failure message now includes the exception class name.** Prior
  `status.error` rendered as `"batch embed failed (cursor at …): "` (empty
  after the colon) when the underlying exception had no string
  representation — e.g. `httpx.ReadTimeout()`. Now renders as
  `"batch embed failed (cursor at …): ReadTimeout: <message>"`. Locked by
  `test_backfill_error_includes_exception_class_when_message_empty`.

### Tests

- 4 new tests in `tests/test_services/test_embedding_backfill.py`:
  - `test_backfill_error_includes_exception_class_when_message_empty`
  - `test_backfill_default_batch_size_is_eight_v241`
  - `test_openai_compat_default_timeout_is_600_v241`
  - `test_ollama_default_timeout_is_600_v241`

### Provenance

- Triggered by PI UI failure observation post-v2.4.0 release: LM Studio
  + qwen3-embedding-8b 4096-dim backfill failed at 0/827 claims after
  ~23 min wall-clock with empty `status.error` after the colon.
- Bookkeeper invariant `git diff main -- rka/services/worker.py` = 0 lines
  held on the v2.4.1 hotfix branch.

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
