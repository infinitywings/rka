# RKA Orchestrator (Phase 1)

LangGraph-driven orchestrator that runs the Brain ⇄ Executor ⇄ PI research loop
against the RKA REST/MCP backend. Phase 1 is a flat 15-node graph with
single-thread execution and a SqliteSaver checkpointer.

## Topology (Phase 1)

- **6 Brain nodes** — strategy / Confirmation Brief / decision presentation /
  cluster review / Gate 1 / final-report synthesis
- **3 Executor nodes** — Backbrief drafting / mission execution / report
  submission
- **3 PI nodes** — interrupt() points for greenlight, decision-selection,
  acceptance review
- **3 Utility nodes** — budget_check, consensus_check, escalation_router

All RKA access is via the MCP client wrapper (`orchestrator/mcp_client.py`).
There are zero direct imports from the `rka` package — enforced by a grep-gate
in T11.

## Three-storage discipline

- **RKA SQLite** — domain truth (decisions, missions, journals, claims)
- **LangGraph SqliteSaver** — workflow position (graph node + state)
- **Claude SDK session** — transient prompt/response context per node

The `workflow_thread_id` is recorded on every RKA write so the orchestrator can
reconstruct which run produced which artifact.

## Local install

```bash
cd orchestrator
pip install -e ".[dev]"
pytest -q
```

## Mission references

- Mission: `mis_01KRKG9K1SSDZNDH90K2Z7ZM92`
- Decision: `dec_01KRKE6ERDPQTFQS6ZGY9A3CK0` (Option B)
- Branch: `agentic` (long-lived, peer to `main`)
