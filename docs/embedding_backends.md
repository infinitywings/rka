# Embedding backends (v2.4.0+)

RKA supports three embedding backends; the choice is configurable in the
web UI at **Settings → Embeddings**. Configuration persists at
`/data/embedding_config.json` (file-mode 0600 to protect the optional
`api_key`) and survives `docker compose up -d --build`.

Semantic search is **ON by default** in v2.4.0 with the FastEmbed
baseline. The first-run banner in the web UI points new users at the
Settings page if they want a different backend.

## Backend matrix

| Backend          | Where it runs                         | Default port | Auth       | Required config                |
|------------------|---------------------------------------|--------------|------------|--------------------------------|
| **FastEmbed**    | in-process (ONNX via `fastembed`)     | n/a          | n/a        | `model_name` (default nomic-768) |
| **OpenAI-compat**| any service exposing `/v1/embeddings` | varies       | optional   | `base_url`, `model`, `api_key` (optional), `dim`  |
| **Ollama**       | local Ollama daemon                   | 11434        | none       | `base_url`, `model`, `dim` (auto-detected) |

The OpenAI-compat backend handles many deployment targets: the OpenAI
API itself, LM Studio (`http://host.docker.internal:1234`), vLLM,
Together AI, Anthropic-via-shim. The differentiating field is
`base_url`; `api_key` is optional because LM Studio and several local
proxies don't require auth.

The Ollama backend is intentionally separate: it speaks Ollama's native
`/api/embeddings` (singular `prompt` + singular `{"embedding": [...]}`)
rather than the OpenAI list-wrapped `data: [{"embedding": [...]}]`
shape.

## When to use each

- **FastEmbed** — first run, no external services, fully offline. 768-dim
  vectors are fast and accurate for general English text. Best for "I
  want it to work without doing anything."
- **OpenAI-compat → a managed local sidecar or LM Studio** — when a local
  service exposes `/v1/embeddings`. Models that distinguish query and
  document inputs can use the optional templates described below.
- **Ollama** — when Ollama is your local model server of choice. Pull
  any embedding model with `ollama pull nomic-embed-text`, then point
  the UI at `http://host.docker.internal:11434`.
- **OpenAI-compat → cloud API** — when you want to use OpenAI's
  `text-embedding-3-small` (1536-dim) or Together's hosted embeddings.
  Set `api_key` to your provider key; the field is stored at file-mode
  0600 and never re-displayed after save.

## Config schema

`/data/embedding_config.json`:

```json
{
  "backend": "openai_compat",
  "config": {
    "base_url": "http://host.docker.internal:1234",
    "model": "text-embedding-qwen3-embedding-8b",
    "api_key": "sk-...",
    "dim": 4096,
    "query_template": "{text}",
    "document_template": "{text}"
  },
  "updated_at": "2026-05-15T16:00:00Z",
  "updated_by": "pi"
}
```

The `backend` field is one of `"fastembed" | "openai_compat" | "ollama"`.
The outer object rejects unknown fields. The backend-specific `config`
subobject is intentionally extensible; recognized fields are validated when
the backend is constructed, while consumers should not assume that every
unknown nested key is rejected.

For a pinned local runtime, `embedding_space_id` may carry the immutable
artifact/runtime identity used for embedding metadata. It must change when
model bytes, quantization, pooling, normalization, dimensions, or document
encoding change. `query_template` and `document_template` each contain exactly
one literal `{text}` placeholder. Query-only instruction changes do not require
document re-indexing; changes to the document template or embedding space do.
See [ADR 0017](adr/0017-portable-embedding-runtime-boundary.md).

## Switching backends

1. Open the web UI → **Settings** in the sidebar → **Embeddings** card.
2. Pick the new backend from the dropdown. Form fields update to the
   relevant set.
3. Fill in `base_url`, `model`, etc. for the new backend.
4. Click **Test connection**. The result panel shows `ok`, detected
   `dim`, and `latency_ms`. A failed test is non-destructive; the
   previous config stays active.
5. Click **Save & re-embed**. A confirmation modal explains whether the
   change requires missing-row repair, a same-dimension rebuild, or supervised
   offline maintenance.
6. Confirm → backfill starts in the background; a progress bar in the
   Settings page polls every ~1.5 s until the job reaches `complete`
   or `failed`. During a generation rebuild, vector retrieval is withheld and
   the whole search path remains lexical until coverage and consistency checks
   mark the new generation ready.

## Cost of switching

Re-embedding triggers automatically when the stored embedding-space identity,
document template, dimensions, backend, or endpoint model changes. A changed
embedding space forces a clean rebuild even at the same dimension. Repointing
an endpoint backfills missing rows without discarding compatible vectors.
Changing credentials does not invalidate compatible vectors, but it may
schedule a missing-only repair and return 202 so records created during an
authentication outage are not stranded. Existing compatible rows are kept.
This repair does not rescan same-model metadata for changed content; failed
edit jobs remain visible in the durable job queue and must be retried.

A populated index cannot change vector dimension online. Core returns
`409 embedding_offline_reindex_required`; a supervisor must stop API and
worker peers, perform the resize/full re-index, and restart them.

## Troubleshooting

### "Embedding config could not be loaded"

The Settings page surfaces this banner when `/data/embedding_config.json`
is corrupt. Hint: restore from `/data/embedding_config.backup.json` (a
pre-flight backup is written before every save) or remove the live file
and restart — the startup hook writes a fresh DEFAULT_CONFIG when
neither exists.

### "Connection refused" on Test connection (LM Studio / Ollama)

The Docker container reaches the host via `host.docker.internal`. Make
sure your `docker-compose.yml` has `extra_hosts: ["host.docker.internal:
host-gateway"]` (it does by default in v2.4.0). Then verify LM Studio /
Ollama is bound to all interfaces, not just `127.0.0.1`.

### "Dim mismatch: configured=N, server=M"

You typed a dim that doesn't match what the backend returns. Hit **Test
connection** to auto-detect the dim, then save again. This error is the
T2.5 calibration guard — `embed()` raises rather than silently mutating
`self._dim`, which would otherwise produce a confusing
sqlite-vec-side error far from the actual misconfiguration.

### Bind-mount + file-mode 0600 (R15 note)

`/data/embedding_config.json` is written at `0o600` so the optional
`api_key` is owner-readable only. This works as expected on Linux hosts
where `/data` is a true Docker volume (`docker volume create rka-data`).

If you bind-mount your host filesystem at `/data` (Docker Desktop on
macOS or Windows), the host's POSIX permissions model takes precedence
and `chmod 0600` from inside the container may not produce the intended
effect on the host file. Recommended:

```bash
# After first save, on your host (macOS/Linux):
chmod 600 /path/to/host/data/embedding_config.json
```

For containers that run as root with a bind-mounted host folder, the
file lands as root-owned on the host. Either use a Docker volume (the
default) or run with `--user $(id -u):$(id -g)` to keep host ownership
sane.

## LLM-driven features

Q&A and summary generation that used to live in the web UI were removed
in v2.4.0 per the LLM-capability-removal directive
(`jrn_01KRNZBS50K250HHHHEC58E4GC`). Server-side legacy LLM code remains
outside the embedding and Core retrieval contract. Any future generation
product requires its own explicit boundary decision.

`/api/capabilities` no longer returns the `llm` field (BREAKING change
at v2.4.0). Consumers of the `embedding` half of the response are
unaffected.
