# Comprehensive Code Review (2026-03-12)

## Scope and Method

This review covered backend (`rka/`), API wiring, DB infrastructure, and a light frontend/tooling check.

Checks performed:

- Static code scan with Ruff across `rka`, `tests`, and `web/src`.
- Import/runtime sanity via `python -m compileall -q rka`.
- Architectural read-through of API app lifecycle, dependency injection, DB layer, and LLM config routes.

## Executive Summary

The codebase is generally well-structured and readable, with clear service boundaries and pragmatic async DB patterns. Main risks are concentrated in:

1. App configurability/testability issues (factory argument not honored).
2. Operational hardening (public mutating routes without authentication controls).
3. Maintainability debt (large set of lint findings and private-attribute coupling).

## Findings

### 1) `create_app(config=...)` argument is currently ignored (High)

- `create_app` accepts an optional `config` parameter but never uses it.
- The app lifecycle always pulls config from global cached `get_config()`.
- Impact: tests and embedding/integration scenarios cannot reliably inject isolated config; behavior depends on process-global state.

**Evidence:** `rka/api/app.py` defines `create_app(config: RKAConfig | None = None)` yet reads config from `get_config()` in `lifespan` and route handlers. 

**Recommendation:**
- Wire the provided `config` into app state during `create_app`, and have `lifespan`/routes use `request.app.state.config` (with a fallback to `get_config()` if needed).

### 2) Reliance on private internals in infrastructure and health checks (Medium)

- DB connection uses aiosqlite private internals (`_execute`, `_conn`) to enable/load extensions.
- API health/status logic uses `llm._available` directly.
- Impact: potential breakage on dependency upgrades due to private attribute changes.

**Evidence:** private access patterns in `rka/infra/database.py` and `rka/api/app.py`/`rka/api/routes/llm.py`.

**Recommendation:**
- Encapsulate extension-loading logic behind a helper with explicit compatibility guards and version pinning notes.
- Expose `LLMClient.available` (public property) and stop reading `_available` externally.

### 3) Missing API authentication/authorization for write operations (Medium)

- Routes include create/update operations for project state, notes, missions, checkpoints, etc. and runtime LLM config mutation.
- No auth dependency or access control appears in route registration.
- Impact: if service is bound outside localhost or proxied insecurely, state tampering risk is high.

**Evidence:** API routes are mounted directly in `create_app` without auth middleware/dependency checks (`rka/api/app.py`).

**Recommendation:**
- Add optional auth modes (API key/JWT) at router or global dependency level.
- Default to loopback bind + explicit warning logs when bound to non-local interfaces without auth.

### 4) Global mutable singletons in dependency module reduce isolation (Medium)

- Module-level mutable globals (`_db`, `_llm`, `_embeddings`, `_search`, `_context`) are used as service backplane.
- Impact: test parallelism and multi-app process patterns may experience cross-talk.

**Evidence:** `rka/api/deps.py` singleton pattern.

**Recommendation:**
- Move long-lived resources into `app.state` and pass via FastAPI dependency callables that receive `Request`.

### 5) Lint and cleanup backlog is sizable (Low)

- Ruff reports 34 issues (unused imports, ambiguous variables, unnecessary f-strings, unused locals).
- Most are auto-fixable; leaving them unresolved increases review noise and can hide real defects.

**Recommendation:**
- Run `ruff check --fix` and enforce in CI.
- Add a minimal CI gate (`ruff + pytest`), even if some tests are marked optional/skipped in constrained environments.

## Positive Notes

- Service-layer architecture is consistent and easy to follow.
- DB wrapper cleanly centralizes schema/migration setup.
- Context/search/LLM capabilities are organized with clear separation of responsibilities.

## Suggested Next Sprint Plan

1. **Hardening:** add auth mode + secure defaults.
2. **Config/Testability:** remove global config coupling in app factory/deps.
3. **Stability:** encapsulate private-attribute accesses.
4. **Hygiene:** clear Ruff backlog and add CI checks.
