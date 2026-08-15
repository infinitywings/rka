# M2 CPSEval Positive Scope-to-Spine Pilot

Date: 2026-08-15

Branch: `feature/rka-cpseval-m2-pilot`

Merged-main baseline: `edb1e6f` (PR 72)

## Purpose

Close the real-project admission gate for the read-only manuscript workbench
without changing live RKA semantics. The pilot asks whether one deliberately
bounded legacy claim can move through the normal canonical scope and native
manuscript interfaces while the UI continues to expose every unresolved
evidence and ratification gate.

## Data isolation

The live RKA `2.8.1` database was opened read-only and copied with SQLite's
online-backup API. The backup passed `PRAGMA integrity_check` and had SHA-256:

```text
279cd694f06c2d580ce28eabfc94580d65e7d7f9c9fee38cd1865892644daf21
```

That snapshot remained unchanged. A second copy was mounted into a disposable
RKA `2.9.0` container on localhost-only port `19713`; only that copy received
migrations and semantic writes. Its post-pilot online backup passed the same
integrity check and had a different SHA-256:

```text
0932ddc190eb294a92eace53e64f6e0f9ca2d66236407cf9d6bef58e335fc62f
```

No live container was restarted, and no live semantic record was updated.

## Bounded case

- project: CPSEval (`prj_01KPVB7NHJ0N33C024TD0E6CZ6`);
- manuscript: ESCAPE (`man_01M00D9BPMA60CN3FXTE86C4W1`);
- canonical method claim: `clm_01M00DCGGK0WHK6QPTZZF60F4P`;
- exact source: `jrn_01M00DCGGJCYMGGD79Q2ZNM72S`.

The selected source statement says that the evaluated setup uses two Factory
IO simulations, Python soft-PLCs, Modbus TCP, and a 20 ms scan cycle (50 Hz).
It is concrete enough to demonstrate applicability boundaries without
promoting one of CPSEval's provisional outcome claims.

The pilot intentionally preserved the canonical claim's original independent
signals:

- `verified = false`;
- `evidence_status = unassessed`;
- no Interpretation Staging candidate was invented for the legacy record;
- no PI ratification or checkpoint resolution was fabricated.

## Normal-interface writes on the disposable copy

1. `GET /api/claims/:id/scope` established scope revision `0` and readiness
   `missing`.
2. `POST /api/claims/:id/scope` appended one reviewed, exact-only contract with
   five typed conditions: two Factory IO simulations, Python soft-PLC,
   Modbus TCP, 20 ms scan cycle, and 50 Hz sampling.
3. The contract marked a statistical falsifier `not_applicable` because this is
   a method/configuration statement; artifact and protocol verification remain
   the separate correctness gate.
4. `PUT /api/manuscripts/:id/argument-spine` advanced the manuscript from
   revision `1` to `2`, adding one active methodological `mcl_` claim and one
   planned method `mun_`, both bound to the selected `clm_` evidence.

The resulting identifiers were:

- scope contract `csc_01M01Z2TD7F1WZQFFZYZBAP98N`;
- manuscript claim `mcl_01M01Z2TDEWJW3945DYY2WJ1CN`;
- manuscript unit `mun_01M01Z2TDFP214ZQ7G5KCYET55`.

## Acceptance result

The scope-to-spine path passed through REST and the production browser:

- canonical scope readiness changed from `missing` to `ready`;
- the manuscript scope stage exposed the `mcl_`, `clm_`, and `csc_` lineage;
- the exact claim-scope deep link rendered all five conditions and immutable
  revision history;
- browser Back restored `?stage=scope`;
- the Paper spine stage rendered the one canonical claim at `?stage=spine`;
- the Outline stage rendered the claim-sized method unit and source claim at
  `?stage=outline`;
- the Context Capsule reported 2 RQs, 6 clusters, 81 claims, 80 blocking
  scopes, 1 ready scope, and 9 relevant semantic changes;
- the browser console contained no warning or error.

The manuscript correctly remained `BLOCK`. Its four findings were
`CLAIM_NOT_RATIFIED`, `EVIDENCE_NOT_MANUSCRIPT_READY`, and the unresolved venue
and outline checkpoints. The scope-review page likewise showed
`source unverified`, `evidence unassessed`, and
`CLAIM_EVIDENCE_UNASSESSED`. This is the desired behavior: applicability
readiness did not become scientific support or drafting readiness.

## Responsive defect and repair

At 390 by 844 pixels, the desktop-only fixed sidebar consumed most of the
viewport and clipped the workbench. The repair:

- hides the fixed sidebar below the `md` breakpoint;
- adds an accessible mobile navigation drawer;
- constrains the header and search to the available width;
- stacks the manuscript loader on narrow screens;
- reduces narrow-screen main padding; and
- makes the first-run banner wrap without forcing horizontal overflow.

The rebuilt production image passed the same CPSEval outline view at 390 by
844 pixels. The drawer opened from **Open navigation**, exposed the current
CPSEval context, closed after navigation, and produced no console warning or
error. The viewport override was reset after testing.

## Verification

- production web build: pass;
- focused ESLint on the five changed layout/workbench files: pass;
- production Docker image build: pass;
- full backend suite: `2,844 passed`, with one existing Pydantic warning;
- desktop CPSEval scope/spine/outline walkthrough: pass;
- 390 by 844 responsive and mobile-navigation walkthrough: pass;
- live backup and post-pilot backup integrity checks: pass.

## Remaining M2 exit work

The real-project positive path and narrow-viewport blocker are closed. Before
enabling M3 mutation UI, freeze the M2 exit evidence with a final keyboard and
accessibility pass plus explicit loading, empty, and capped-count cases. Those
checks must not weaken the epistemic labels demonstrated here.
