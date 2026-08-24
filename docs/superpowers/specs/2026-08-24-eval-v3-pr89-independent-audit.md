# Independent audit — PR #89 (Eval-v3 + retrieval fixes)

**Date**: 2026-08-24
**Subject**: PR [#89](https://github.com/infinitywings/rka/pull/89),
`claude/rka-performance-eval-2d20e9` @ `acfa44a`, vs `main` @ `3fb0cd7`.
**Auditor independence**: this audit was performed by the remote session that
originally built the Eval-v3 harness (PR #88, superseded). It did **not**
author any of the production fixes, the skill rewrites, the corpora, or the
experiment runs under audit, and it reviewed them against a fresh checkout.

## Verdict

**APPROVE.** The production fixes are correctly scoped, well-argued, and
pinned by regression tests that demonstrably fail on `main`. The experiment
write-ups are honest, including two self-corrections and the retention
track's negative result. Findings below are minor and none blocks merge.

## What was verified, and how

### 1. Regression-test claim — verified empirically

The 12 new production-facing tests were copied into a clean worktree at
`main@3fb0cd7` and executed there. **10 of 12 fail on main exactly as the PR
claims**, pinning: the missing search currency fields (2), the
`embedding_pending` flag-drift backfill gate (1), `_backend_signature`
ignoring `base_url` (1), the absent backfill endpoint (2), and the
unclassified MCP surface (4).

The other 2 — `test_backend_signature_ignores_api_key` and
`test_already_embedded_claim_is_not_reprocessed` — **pass on main**: they are
behavior-preservation locks, not defect pins. The PR's sentence "every one
failing against the previous code" is therefore slightly overstated; the
substantive claim (every *defect pin* fails before) holds. Recorded for
precision, not as an objection.

### 2. Search currency fill (`SearchService._attach_currency`) — sound

- Applied at the single public exit; both the constrained and unconstrained
  return paths route through it, so all four retrieval strategies are
  covered without touching their construction sites.
- Batched one query per entity type present; ids parameterized; table and
  column names come from a fixed literal map (no injection surface);
  project-scoped (`AND project_id = ?`).
- Column existence verified against the migrated schema for all five mapped
  tables (`decisions.status/superseded_by`, `journal.status/superseded_by`,
  `claims.stale`, `missions.status`, `literature.status`).
- Degrades on pre-migration snapshots via a logged `except` rather than
  failing the search.
- The REST model change is additive (`status`/`superseded_by`/`stale`
  optional, default `None`) — backward compatible for existing clients.

### 3. Embedding-backfill flag fix — sound, one hygiene note

The claims pending predicate now matches every other entity type (absence of
an `embedding_metadata` row) instead of the drifting `embedding_pending`
flag, while still clearing the flag post-embed for external readers —
consistent and minimal. Note (minor, non-blocking): the `NOT EXISTS`
subquery matches on `(entity_type, entity_id)` only, while the
`embedding_metadata` primary key leads with `project_id` — so the probe
cannot use the PK index and scans. Correct today because entity ids are
globally unique ULIDs; at current scale (≈5k metadata rows) the cost is
negligible. If stores grow 100×, add an index on
`(entity_type, entity_id)`.

### 4. `_backend_signature` + `base_url` — safety argument checked

The claimed invariant was traced in code: with an unchanged `dim`,
`reshape_all_vec_tables_if_needed` is a no-op, and backfill's pending
predicate only ever *adds* vectors for entities that have none — so a
`base_url` change triggers reconciliation without discarding any existing
vector. An `api_key` rotation still compares equal (locked by test). The
signature reads `base_url` or `host`, covering both config shapes.

### 5. Cached-client swap — both branches now covered

The 202/backfill branch already swapped `app.state.embeddings` before this
PR; the fix adds the swap to the previously-missing no-backfill branch. The
defect class ("UI reports a backend that queries do not use") is closed on
both paths.

### 6. New `POST /api/config/embedding/backfill` — acceptable

422 when no backend is configured; 202 + job id otherwise; background
exceptions land in the job status (not just a logger). Unknown
`entity_types` tokens raise inside `run_backfill` and surface as a *failed
job* rather than a pre-flight 422 — visible, not silent; a pre-validation
422 would be marginally friendlier (P3 suggestion). No auth, consistent
with the rest of the single-user local REST surface.

### 7. MCP maturity gating — browse-only, dispatch untouched — verified

The diff confirms the `oneOf`+discriminator dispatch schema is unchanged;
only the `rka_describe('')` browse index filters preview operations, reports
how many were hidden, and restores them with `include_preview=True`.
Classification derives from category plus a short named list, guarded by
four drift tests (including "every operation is classified"). The stale
"139 operations" docstring drift was fixed in passing.

### 8. Skills, mirrors, spine — light review

Skill guidance now matches the measurements (type scoping, the supersession
hazard, corrected query-length advice); the wrong anti-pattern #5 mechanism
is gone. `plugin/` ↔ `rka/` mirrors and the shared-H2 spine are locked by
tests; the deliberate non-merge of Guardrails vs Anti-Patterns is reasoned
and recorded.

### 9. Experiment write-ups — honest and internally consistent

- The corrections section retracts two of the author's own earlier claims
  (the "semantic lift" that was recovered timeouts; the confounded
  embeddings-contribute-nothing comparison) and keeps both keyword-only and
  semantic runs in-tree so the degradation is measurable, not asserted.
- The retention track's negative result (fade regime never reached at 35k
  tokens against a 262k window; the `rka` arm's 0.17 attributed to a
  paragraph-shaped query) is reported as such rather than spun.
- The Eval-v3 extractor's own `--project` scoping bug — found by the runs —
  is fixed with endpoint-scoped link walks and regression tests; the
  rationale for scoping by endpoint (56 legacy NULL-stamped link rows) is
  correct against the schema history.

### 10. Full suite

CI run #194 on the audited head (`acfa44a`) completed green: 3 285 tests.
An additional from-scratch re-run in the audit environment was started;
its result is recorded in the addendum when available.

## Non-blocking recommendations

1. **R1**: adjust the "every one failing" sentence (see §1) or reclassify
   the two preservation locks — precision only.
2. **R2**: pre-validate `entity_types` in the backfill route (422 on unknown
   token) instead of failing the job.
3. **R3** (next measured target, already in REPAIR-PLAN's P2): bundle noise —
   precision ≈0.21 and the uncapped `/api/graph/ego` (355-node hub bundles).
4. **R4**: document that the new `status` field is table-local (literature's
   workflow states vs decisions' lifecycle states), so consumers do not
   treat it as one enum.
5. **R5**: index `(entity_type, entity_id)` on `embedding_metadata` if the
   store grows well beyond current scale.

## Outstanding items that need the PI (not this PR)

- Ratify the 20 tracing scenarios (`scenarios.CAREER.jsonl`,
  `scenarios.rka_development.jsonl`) — results are labeled
  ratification-pending.
- Resolve the 4 superseded decisions whose successor ids do not exist.
- Decide when to re-run retention in a genuine fade regime (150k+ distances
  or session-boundary probes).

## Audit addendum — delta `acfa44a..5d73b64` (supersession repair surface)

Two commits landed after the audit above; the delta was reviewed
separately and the verdict is unchanged (**APPROVE**).

- `c76e9f2` exposes the existing `rka admin repair-supersedes` capability
  beyond the CLI, as thin adapters at all four layers
  (`GET /api/decisions/orphan-supersedes`,
  `POST /api/decisions/link-supersession`,
  `rka_query(operation="orphan_supersedes")`,
  `rka_execute(operation="link_supersession")`). Design points verified:
  `apply` defaults to a dry-run preview (a wrong pointer being worse than a
  missing one), the repair replays the full supersede sequence
  (scope-version bump, entity_link, staleness cascade, review row, event)
  idempotently, and no new logic was added outside the already-tested
  service (12 service-layer tests). This directly discharges part of the
  "4 orphaned decisions" outstanding item: the repair path now exists for
  agents and the web UI; the remaining orphan pairs still need the PI to
  name the successors.
- `5d73b64` fixes a real reachability bug the first commit shipped:
  FastAPI registration order let `/decisions/{dec_id}` shadow the new
  literal path (404 "Decision orphan-supersedes not found"). The fix moves
  the literal routes above the parameterised one with an explanatory note,
  and adds three API-level tests — including a shadowing test verified by
  reverting the route order — closing the "adapter tested only at the
  service layer" gap the bug exposed.
- Independent verification at `5d73b64`: CI full suite green (run #196);
  this audit re-ran `test_decisions_supersede_routes.py`,
  `test_admin_repair.py`, and the v2.7.0 drift tests locally — 951 passed.

## Audit addendum — suite runs

- CI (`pytest` run #194, ubuntu, Python 3.13) on `acfa44a`: **success,
  3 285 tests**.
- Worktree cross-check (audit environment, Python 3.11, `main@3fb0cd7` +
  the 12 new production tests): 10 fail / 2 preservation locks pass — the
  basis of §1.
- From-scratch full-suite re-run of `acfa44a` in the audit environment
  (Python 3.11, fresh dependency install): **3 285 passed, 0 failed**
  in 9 m 38 s — matching CI exactly. No divergence.
