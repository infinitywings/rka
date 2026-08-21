# M5 PR 9.2 Exit Evidence: Typed Academic-Writing Core

Date: 2026-08-17
Baseline: `origin/main` at `f70d360`
Implementation branch: `codex/m5-typed-writing-core`

## Scope exercised

- Migration 049 on a fresh database, on restart, and as a late migration over
  legacy manuscript rows.
- Typed claim boundaries (`conditions`, `falsification_criteria`).
- Typed unit roles and rhetorical moves.
- Evidence-use propositions and warrants for support, qualifier, and
  counterevidence bindings.
- Unit-level citation uses with reference-manifest membership and current
  validation checks.
- Progressive outline expansion/condensation, semantic patches, checkpoints,
  change tracking, project deletion, and knowledge-pack rekey/import paths.
- MCP typed-operation parity and workbench rendering/edit controls.
- Deterministic academic-readiness v2 with structural blockers and advisory
  judgment checks.
- Draft-section dependency snapshots cover section-local claim boundaries,
  propositions, warrants, citations, unit roles, and rhetorical moves.
- Private claim-level qualifiers and counterevidence remain visible through
  progressive disclosure, with non-blocking allocation advisories.
- Pack rekeying rewrites auditable checkpoint components and recomputes their
  digest; ambiguous condense collisions fail closed.
- Pre-components v2 checkpoint snapshots remain current when their semantic
  digest matches, while a real dependency change still supersedes them.
- The legacy MCP direct-upsert operation is explicitly deprecated and performs
  no network write; its actor-routing role remains within the documented role
  vocabulary, and agents use attributed semantic-patch proposals instead.

## Disposable real-project-derived pilot

The pilot test
`test_invarllm_derived_pilot_preserves_argument_boundaries_and_tradeoffs`
uses a read-only snapshot of three claim identities and bounded findings from
RKA project `prj_01KN51HD73DSY9ZR9C56JYRNYZ`. It recreates those rows only in
the isolated pytest database; it does not mutate the live project.

The pilot proves that one strength-first paper claim can retain, in the same
auditable substrate:

- the favorable eTaF1/precision result;
- the exact HAI 21.03/configuration conditions;
- a protocol-matched falsification criterion;
- the recall/scenario-coverage qualifier;
- counterevidence that the predicted AffF1 recovery did not materialize;
- proposition-specific warrants; and
- one currently verified citation plus one explicitly self-attested citation.

Expected readiness behavior also passed: structure, claim allocation, evidence
presence, evidence-use explanation, claim boundaries, and rhetorical annotation
pass; the self-attested citation produces a non-blocking citation warning.

## Independent-audit remediation

The first independent audit of commit `fa30021` found three P1 acceptance
defects and four P2/P3 contract or evidence defects. The remediation adds
adversarial coverage for:

- same-unit approval invalidation and unrelated-unit approval preservation;
- conflicting same-ID evidence and citation metadata during condense;
- unallocated private qualifier/counterevidence visibility;
- resolved outline-checkpoint export/import/rekey currency;
- MCP deprecation without an unreachable REST write;
- stale-current citation rendering; and
- migration cross-project FKs, update/delete events, and transactional rollback.
- backward-compatible approval currency across the v2 snapshot representation
  expansion, without weakening semantic-change invalidation.

The second exact-commit audit of `2461e457` confirmed the original remediation
and found one upgrade-compatibility P1 plus one schema-contract P3. The current
candidate preserves matching hash-only v2 approvals, invalidates them after a
real semantic change, and keeps `role_tag` within its documented actor-routing
vocabulary while reporting operation deprecation separately.

The PR remains draft until the corrected snapshot receives a fresh independent
audit.

## Automated evidence

| Gate | Result |
| --- | --- |
| Corrective migration/service/outline/pack/MCP suite (command below) | **92 passed** |
| MCP schema/model-drift suite (command below) | **994 passed** |
| Disposable INVARLLM pilot (command below) | **1 passed** |
| Changed Python files: Ruff lint (commands below) | **Passed** |
| Python compile check: `python -m compileall -q rka` | **Passed** |
| Git whitespace/error check: `git diff --check f70d360 --` | **Passed** |
| Web production build: `(cd web && npm run build)` | **Passed**; existing large-chunk warning remains |
| Changed web files: `(cd web && npx eslint src/api/types.ts src/components/workbench/OutlineEditor.tsx)` | **Passed** |
| Full Python suite: `python -m pytest -q` | **3,153 passed in 210.41s** |

Corrective suite command:

```text
python -m pytest -q tests/test_db/test_migration_049.py tests/test_services/test_outline.py tests/test_services/test_native_manuscript_service.py tests/test_services/test_knowledge_pack_native.py tests/test_mcp/test_native_manuscript_operations.py
```

MCP schema/model-drift command:

```text
python -m pytest -q tests/test_mcp/test_v270_model_drift.py tests/test_mcp/test_mcp_tool_surface.py tests/test_mcp/test_native_manuscript_operations.py
```

Disposable pilot command:

```text
python -m pytest -q tests/test_services/test_native_manuscript_service.py::test_invarllm_derived_pilot_preserves_argument_boundaries_and_tradeoffs
```

Ruff commands:

```text
python -m ruff check rka/mcp/operations_schema.py rka/services/knowledge_pack.py rka/services/manuscript_native.py rka/services/outline.py tests/test_db/test_migration_049.py tests/test_mcp/test_native_manuscript_operations.py tests/test_services/test_knowledge_pack_native.py tests/test_services/test_native_manuscript_service.py tests/test_services/test_outline.py
python -m ruff check --ignore E402,F401,F841 rka/mcp/server.py
```

The narrow ignores on the legacy monolithic MCP server are recorded explicitly;
they suppress only pre-existing file-wide import-placement and unused-symbol
findings. The modified deprecation handler is exercised by the corrective test
suite.

The disposable local virtual environment omitted the optional `llm` extra, so
the full-suite run made its cached `sqlite-vec` 0.1.9 package available on
`PYTHONPATH`. This is equivalent to running the canonical command in a complete
development environment with the sqlite-vec dependency installed; without it,
embedding-persistence tests fail because vector storage is intentionally
disabled.

## Review interpretation

The implementation remains in draft-PR review. The focused change surface,
migration paths, web build, and real-project-derived academic workflow are
green. Repository-wide status and the second independent verdict are recorded
only after they complete; no narrower check is described as production
readiness.
