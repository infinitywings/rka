# Eval-v3 Track 1 — self-study metrics extractor

Computes the three §7.1 metrics promised in the RKA paper — **provenance
coverage**, **research-debt trajectory**, and **mission-cycle metrics** —
plus the M-era **pipeline-stage flow**, from a snapshot copy of an RKA
database. Plan: [`docs/superpowers/plans/2026-08-23-rka-research-quality-evaluation-plan.md`](../../../docs/superpowers/plans/2026-08-23-rka-research-quality-evaluation-plan.md)
(Track 1).

## Taking a snapshot (never run against the live DB)

```bash
# from the repo root, with the stack running
docker compose exec rka sqlite3 /data/rka.db ".backup /data/rka-snapshot-$(date +%F).db"
docker compose cp rka:/data/rka-snapshot-$(date +%F).db eval-harness/v3/self_study/snapshots/
```

The extractor opens the file `mode=ro` regardless, but work from a
`.backup` copy so WAL state is consistent and the live volume is never
touched.

## Running

```bash
python eval-harness/v3/self_study/compute_metrics.py \
  --db eval-harness/v3/self_study/snapshots/rka-snapshot-2026-08-23.db \
  --out eval-harness/v3/self_study/results/metrics.json \
  --csv eval-harness/v3/self_study/results/debt_trajectory.csv
# optionally: --project prj_...   (restrict to one project where tables carry project_id)
```

Stdlib-only; no Docker, no rka package import. The output embeds the
snapshot's SHA256 for reproducibility, following the Eval-v1/v2
convention.

## Metric definitions (operationalized)

- **Provenance coverage** — a claim counts as *covered* when any of:
  its `source_entry_id` journal row is researcher-authored (`source =
  'pi'` or a `pi_instruction`/`directive` type); that source entry lists
  `related_literature`; the claim was promoted from an interpretation
  candidate whose source is literature; or a bounded walk (depth ≤ 3)
  over `entity_links` from the claim or its source entry reaches a
  literature entity, a researcher-authored journal entry, or a
  PI-decided decision. `coverage_strict` additionally requires
  `stale = 0`.
- **Research-debt trajectory** — per claim-creation month: claims
  created, covered vs. uncovered *in the snapshot's current state*, and
  the running total of uncovered claims. Time-to-coverage is
  approximated from the covering link's `created_at` (0 for claims
  covered through their own source entry).
- **Mission-cycle metrics** — mission duration (created → completed),
  checkpoints per mission, checkpoint resolution latency, open
  checkpoints, report presence, and completion-to-first-journal latency
  as the mission-to-report proxy.
- **Pipeline flow** — interpretation candidates by review status and
  disposition; canonical-claim scope coverage (`scope_revision ≥ 1`,
  reviewed scope versions); semantic patch proposals by status;
  manuscript claims with evidence bindings and ratifications.

Every section is introspection-guarded: on an older snapshot that
predates a migration, the affected section reports
`{"available": false}` instead of failing.

## Known limitations

- Coverage is a **current-state** reconstruction, not an event replay: a
  claim whose covering link was added months after creation counts as
  covered in every month's `covered_now`. The `time_to_coverage_days`
  distribution is the honest signal for how quickly debt is retired.
- The depth-3 `entity_links` walk is undirected; it can credit coverage
  through a path a strict provenance-direction reading would reject.
  Tighten `BFS_DEPTH_LIMIT`/direction handling before quoting the number
  in the paper if reviewers press on this.
- N=1 caveats from the plan apply: this measures the record, not the
  researcher population.

## Tests

`eval-harness/v3/tests/test_self_study_metrics.py` builds a real migrated
database via `rka.infra.database.Database.initialize_schema()`, inserts a
small synthetic record with known coverage structure, and locks the
metric math. Run with `pytest eval-harness/v3/tests/ -q` (CI collects it
with the main suite).
