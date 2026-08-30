# ADR 0017: Portable embedding runtime and vector-space boundary

Status: Accepted for staged implementation

## Context

RKA needs useful semantic retrieval on an ordinary research computer without
requiring LM Studio, Docker, a discrete GPU, or manual MCP configuration. The
minimum product target is a 16 GB Apple M1 Mac or a 16 GB Windows machine with
an Intel Core Ultra 7 155H-class processor. Core must remain usable when the
embedding runtime is unavailable.

RKA already supports OpenAI-compatible embedding endpoints, flexible
sqlite-vec dimensions, full backfill, and lexical retrieval. It does not need a
model-specific backend. It did need two missing contracts: query/document input
adaptation and an identity that prevents incompatible vectors from sharing an
index.

## Decision

### Ownership

`rka-core` owns the embedding provider contract, vector-space identity,
sqlite-vec index, re-index behavior, and lexical degradation. It does not
download models, bundle inference binaries, select a GPU, or supervise a model
process.

The separate future `rka-app` owns the portable runtime: downloading and
hash-verifying a pinned model, installing a pinned `llama-server`, selecting a
tested Metal/Vulkan/CPU path, lifecycle and readiness, loopback ports, logs,
upgrades, and rollback. This follows ADR 0014; there is no permanent App branch
inside Core.

### Standard-profile candidate

The standard App profile candidate is the official
[`Qwen3-Embedding-0.6B` Q8_0 GGUF](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF):

- 1024 output dimensions;
- a 639 MB Q8_0 artifact;
- a pinned `llama-server` started with embedding mode, last-token pooling,
  and L2 normalization (`--pooling last --embd-normalize 2`);
- an operational input cap of 4096 tokens for the first release;
- one concurrent embedding slot and small ingestion batches initially;
- CPU as the baseline path to validate on both target machines; Metal or
  Windows acceleration is enabled only after a startup smoke test.

The model is a **candidate**, not yet the released default. It becomes the App
default only after the A/B and two-machine gates below pass. Core's existing
first-run FastEmbed configuration remains unchanged, and existing installations
are never silently migrated.

### Core configuration contract

The App configures Core through the existing `openai_compat` backend:

```json
{
  "backend": "openai_compat",
  "config": {
    "base_url": "http://127.0.0.1:9714",
    "model": "rka-qwen3-embedding-0.6b-q8_0",
    "dim": 1024,
    "embedding_space_id": "rka-space-v1:sha256=<gguf-sha256>;quant=q8_0;tokenizer=<config-sha256>;eos=<policy>;pool=last;norm=l2;truncate=4096;doc=raw-v1;dim=1024;runtime=<llama-revision>",
    "query_template": "Instruct: Given a research-memory query, retrieve records needed to reconstruct the relevant evidence, decisions, and research context.\nQuery: {text}",
    "document_template": "{text}"
  }
}
```

`model` is the transport alias sent to `/v1/embeddings`.
`embedding_space_id` is an opaque, App-generated identity stored in embedding
metadata. It must change when model bytes, quantization, dimensions, pooling,
normalization, tokenizer/config revision, EOS behavior, truncation/context cap,
document encoding/template revision, or pinned runtime revision changes. Core
does not guess an artifact hash or interpret the fields inside this ID.

Embedding configuration mutation has one active API-writer process. The App
must not run rolling multi-process PUTs against the same config file. Core
serializes updates within that process, compensates the file if the database
commit fails or is cancelled, and reconciles file/database identity again at
startup; a distributed configuration transaction is outside this boundary.

Templates contain exactly one literal `{text}` placeholder. Core uses literal
replacement rather than general string formatting. Query and document
templates are applied separately. A query-only template change refreshes the
live backend but does not rebuild stored document vectors. A document-template
or `embedding_space_id` change forces a clean rebuild even when dimensions are
unchanged, so one vec table never contains mixed embedding spaces.

### Dimension transitions

A same-dimension embedding-space change can rebuild online. The active
generation is marked `reindexing`, vector reads are withheld, and retrieval
stays lexical until coverage and consistency checks mark the new generation
ready.

A populated sqlite-vec index cannot change dimension while API or worker peers
may still hold the old virtual-table schema. Core therefore returns
`409 embedding_offline_reindex_required`. The App must stop API and worker
processes, perform the supervised resize and full re-index, and then restart
them. An empty first-run index may be resized directly.

### Failure behavior

Hardware fallback may change the execution device while using the exact same
model artifact and embedding contract. Model-to-model fallback is never
transparent because it would produce incompatible vectors.

If the configured runtime is unavailable, RKA continues through FTS, tags,
graph relations, and other non-vector retrieval. It must report this as a
degraded lexical mode rather than silently switching models. Switching to a
different model is an explicit profile change followed by a complete re-index.

The current explicit backfill endpoint repairs rows that lack current
model/dimension metadata. It is not a general content-hash scrubber. A failed
edit embedding remains on the durable worker/retry path until the separately
tracked hash-aware repair scan is implemented.

## Promotion evaluation

The existing embedding-disabled Core retrieval baseline remains unchanged.
Before running the promotion decision, freeze a reproducible comparison of
lexical-only, current Nomic, and the Qwen candidate from identical
provider-free database copies. The comparison must name its corpus versions,
query set, metric tolerances, repetitions, and hardware protocol.

Before Qwen becomes the App default:

1. all project-isolation and currentness gates remain perfect;
2. every eligible record is represented by exactly one current-space vector
   and metadata row, with no mixed model identities;
3. direct Hit@10 and macro MRR meet the frozen non-regression tolerance against
   Nomic, and Qwen succeeds on hard semantic or cross-language queries that
   lexical retrieval misses;
4. the frozen TraceGuard causal-story contract and at least one independent
   project story reconstruct their required roles, edges, facts, and current
   decisions within a predeclared noise budget;
5. peak RSS, warm-query latency, readiness time, and full-backfill failures are
   measured on both target machines and meet thresholds frozen before the run;
6. Q8 ranking parity against the official model implementation is measured
   using a pinned sample and tolerance.

No numeric performance threshold is release-authoritative until the protocol
and both target-machine measurements are checked into the evaluation record.

## Non-goals

This decision does not add a llama.cpp backend to Core, ship model artifacts in
the Core wheel, auto-detect GPUs in Core, build dual vector indexes, introduce a
background health daemon, or make a one-request model failover. It also does not
change the default model before the evidence gates pass.
