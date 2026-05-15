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
- **OpenAI-compat → LM Studio (qwen3-8b)** — when you've already loaded
  a high-quality embedding model in LM Studio. 4096-dim vectors with
  the eval-harness-measured +9 % NDCG@10 improvement on
  semantic-hybrid search. Best for "I want better retrieval quality and
  I'm already running LM Studio."
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
    "dim": 4096
  },
  "updated_at": "2026-05-15T16:00:00Z",
  "updated_by": "pi"
}
```

The `backend` field is one of `"fastembed" | "openai_compat" | "ollama"`.
The `config` subobject's required keys vary by backend (see matrix
above). Schema validation is strict (`extra="forbid"` on the Pydantic
model) — typos in keys surface as a 422 immediately, rather than being
silently dropped.

## Switching backends

1. Open the web UI → **Settings** in the sidebar → **Embeddings** card.
2. Pick the new backend from the dropdown. Form fields update to the
   relevant set.
3. Fill in `base_url`, `model`, etc. for the new backend.
4. Click **Test connection**. The result panel shows `ok`, detected
   `dim`, and `latency_ms`. A failed test is non-destructive; the
   previous config stays active.
5. Click **Save & re-embed**. A confirmation modal estimates the
   re-embed wall-clock (~7–14 min for the current 827-claim corpus on
   qwen3-8b) and warns that existing vectors will be discarded.
6. Confirm → backfill starts in the background; a progress bar in the
   Settings page polls every ~1.5 s until the job reaches `complete`
   or `failed`. FTS continues working during the re-embed; semantic
   search returns empty results for in-flight claims.

## Cost of switching

Re-embedding triggers automatically when `(backend, model, dim)` change.
Changing `api_key` alone does not trigger a re-embed; PUT returns 200
with the updated (redacted) config.

| Backend        | Empirical latency per claim | 827-claim re-embed wall-clock |
|----------------|-----------------------------|-------------------------------|
| FastEmbed nomic-768 | ~50–100 ms                | ~1–2 min                      |
| LM Studio qwen3-8b  | ~0.5–1 s                  | ~7–14 min                     |
| Ollama nomic-embed-text | ~100–200 ms             | ~2–3 min                      |
| OpenAI text-embedding-3-small | ~30–60 ms (network-bound) | ~1 min                |

Numbers are reference points from internal testing — your hardware,
local model server, and network will vary.

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
(`jrn_01KRNZBS50K250HHHHEC58E4GC`). Server-side LLM code is preserved
(`rka/infra/llm.py`, `rka/api/routes/llm.py`, the `rka_ask` /
`rka_generate_summary` MCP tools) and will be re-wired through the
orchestrator's Claude Code SDK in a follow-up release.

`/api/capabilities` no longer returns the `llm` field (BREAKING change
at v2.4.0). Consumers of the `embedding` half of the response are
unaffected.
