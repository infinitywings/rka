# Core retrieval baseline

Run the deterministic Core release gate from the repository root:

```bash
python eval-harness/v3/core_retrieval/runner.py \
  --check --repeats 7 --warmups 1 \
  --output /tmp/rka-core-retrieval.json
```

The runner uses a temporary database, in-process REST transport, the frozen
synthetic corpus, and no LLM or embedding provider. The full contract,
threshold rationale, and interpretation boundary are documented in
[`docs/CORE_RETRIEVAL_BASELINE.md`](../../../docs/CORE_RETRIEVAL_BASELINE.md).
