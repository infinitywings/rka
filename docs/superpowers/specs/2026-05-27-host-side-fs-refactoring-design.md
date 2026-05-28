# Host-side filesystem refactoring — design spec

**Date**: 2026-05-27
**Branch**: agentic (orchestrator-only; bookkeeper invariant: `git diff origin/main -- rka/` must remain empty, but this touches `rka/` so it lands on main first, then agentic absorbs)
**Status**: Approved in conversation

## Problem

The RKA daemon runs inside Docker. The MCP stdio binary runs on the host as a thin HTTP proxy. Workspace tools (`rka_scan_workspace`, `rka_bootstrap_workspace`) pass host filesystem paths to the REST API inside Docker, which tries to `open()` them and fails with ENOENT. Currently patched with broad bind mounts (`/Users:/Users:rw`, `/Volumes:/Volumes:rw`), which won't work for remote Docker, headless deployments, or Dockerless installs.

## Solution

Split filesystem-touching tools so the MCP layer (which runs on the host) handles all file I/O, then sends content/metadata to the REST API for DB storage. The Docker container never touches the host filesystem.

## Scope

### In scope
- `rka_scan_workspace` — host-side directory walk + classify + hash + preview
- `rka_bootstrap_workspace` — host-side file reading + content POST
- New shared classification module
- Two new REST endpoints (content-based alternatives)
- Service layer modifications to accept content dicts

### Out of scope (no change needed)
- `rka_ingest_document` — already accepts `content: str`
- Phase O `workspace_setup` — already runs on host (direct Python call)
- Web UI — uses file upload, not paths
- Existing REST endpoints — preserved unchanged for backward compat

## Architecture

```
Before:
  Claude Desktop -> rka mcp (HOST, proxy) -> POST {folder_path} -> Docker -> os.walk() ENOENT

After:
  Claude Desktop -> rka mcp (HOST)
    1. os.walk() locally
    2. classify files (shared classify.py)
    3. read previews / hashes
    4. POST {files: [{path, size, hash, preview, category}]} -> Docker
    5. Docker: dedup against bootstrap_log, optional LLM, store scan manifest
    6. For ingest: MCP reads full content locally
    7. POST {content, metadata} per file -> Docker stores in DB
```

## Components

### 1. `rka/services/classify.py` (new, ~80 LOC)

Pure functions extracted from `rka/services/workspace.py`:
- `classify_by_extension(ext) -> category`
- `detect_content_hint(filename, content_preview) -> hint`
- `hint_to_type(hint) -> proposed_type`
- `detect_ingestion_target(category, hint) -> target`
- Extension mapping table (currently inline in workspace.py)
- Content-hint regex patterns

No FS deps, no DB deps, no imports beyond stdlib. Unit-testable in isolation.

### 2. New REST endpoints (additive, ~40 LOC)

`POST /api/workspace/scan/from-host`:
```python
class HostScanRequest(BaseModel):
    root_path: str
    files: list[HostScannedFile]
    total_files_found: int

class HostScannedFile(BaseModel):
    relative_path: str
    filename: str
    extension: str
    size_bytes: int
    file_hash: str
    content_preview: str | None  # first 500 chars; null for binary
    category: str
    content_hint: str
    ingestion_target: str
    proposed_type: str
```

Response: `ScanManifest` (unchanged schema).

`POST /api/workspace/ingest/with-content`:
```python
class IngestFileRequest(BaseModel):
    scan_id: str
    relative_path: str
    content: str          # full text content
    content_type: str     # "text" | "bibtex" | "code"
    metadata: dict        # for PDFs: {title, authors, abstract, year}
    tags: list[str]
    source: str
    phase: str
```

Response: `{ingested: bool, entity_id: str, entity_type: str}`.

### 3. Service layer changes (~60 LOC)

`WorkspaceService.scan_from_host_data(request)`:
- Accepts `HostScanRequest` instead of `folder_path`
- Runs duplicate detection against `bootstrap_log` (DB)
- Skips LLM classification (deferred to ingest)
- Returns `ScanManifest`

`WorkspaceService._ingest_single_file()` modified:
- Checks for inline `content` parameter first
- Falls back to `_safe_read_text(path)` only if content is None (backward compat for bind-mount path)

### 4. MCP tool rewrite (~200 LOC)

`rka_scan_workspace`:
- Host-side: `asyncio.to_thread(walk_and_classify, root_path)`
- `walk_and_classify()` uses `rglob("*")`, `stat()`, `_safe_read_text()` (capped 200K), `hashlib.sha256`
- Classification via `classify.py` (imported from `rka.services.classify`)
- POSTs to `/api/workspace/scan/from-host`
- Formats response same as today

`rka_bootstrap_workspace`:
- Receives scan manifest from user (or re-scans)
- For each file in manifest: reads full content on host via `asyncio.to_thread`
- POSTs each file individually to `/api/workspace/ingest/with-content`
- Reports progress per file

### 5. Optional dependencies

pymupdf + python-docx stay optional on the host:
```python
try:
    import pymupdf
    _HAS_PYMUPDF = True
except ImportError:
    _HAS_PYMUPDF = False
```
PDFs without pymupdf: classified as `pdf` by extension, `preview: null`, literature entry created with filename-derived title only. Same degradation path as the Docker version.

Install command for full support:
```bash
UV_CACHE_DIR=/tmp/uv-cache uv tool install --force ".[workspace]"
```

## Risk mitigations

| Risk | Mitigation |
|---|---|
| pymupdf adds ~35 MB to host install | Optional; graceful degradation without it |
| Large payloads over localhost HTTP | Ingest one file at a time; previews capped at 500 chars |
| LLM classification lost during scan | Deferred to ingest; PI reviews manifest anyway |
| Two codepaths (host MCP + Docker legacy) | Shared classify.py; only I/O envelope differs |
| Blocking FS ops in async MCP | `asyncio.to_thread()` for all blocking calls |
| File race between scan and ingest | Accept (same as today); optionally verify hash |

## Implementation sequence

1. Extract `rka/services/classify.py` + unit tests
2. Add new request models to `rka/models/workspace.py`
3. Add new REST endpoints to `rka/api/routes/workspace.py`
4. Modify `WorkspaceService` to accept content-based inputs
5. Rewrite MCP tools with host-side FS logic
6. Integration tests (both paths)
7. Remove bind mounts from `docker-compose.override.yml`

## Verification

- All existing workspace tests pass unchanged (backward compat)
- New tests cover: classify.py pure functions, from-host scan endpoint, ingest-with-content endpoint, MCP host-side walk + classify, MCP host-side ingest per-file
- Manual smoke test: `rka_scan_workspace` works WITHOUT bind mounts
