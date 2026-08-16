# M4 / PR 8 evaluation-contract exit evidence

- Date: 2026-08-15
- Baseline: `24975997b63093504d43b0a3b9b10c36fe2485e1`
- Branch: `agent/m4-evaluation-contract`
- Scope: claim-centered evaluation contracts, exact result traces, guarded
  evidence missions, and review-only result-unit promotion
- Data safety: the live RKA service and source project were read only; every
  mutation occurred in short-lived loopback containers and disposable volumes

## Contract exercised

The release candidate implements the authority boundary frozen in
[ADR 0008](../../adr/0008-claim-centered-evaluation-contract-and-results-trace.md):

- a provisional, immutable evaluation-stage contract pins one exact native
  manuscript claim version, active RQ decisions, evidence requirements, exact
  experiment-plan versions, observations, locators, and interpretation bounds;
- legacy free-text commitments remain readable but cannot drive canonical
  actions;
- explicit outcome and claim-effect classifications preserve negative,
  inconclusive, and exploratory evidence without inferring support from metric
  direction;
- adverse evidence cannot inherit the old claim's positive allowed wording;
  narrowing or negative-result effects must first revise or replace the claim
  and contract;
- missing evidence becomes one idempotent canonical mission with exact
  planning-version provenance;
- located, claim-aligned evidence may prepare an ADR 0006 semantic proposal,
  but only a separate explicit apply creates the canonical result unit;
- an immutable three-action ledger records mission creation, result proposal
  preparation, and the exact resulting manuscript unit after apply;
- REST, direct MCP, typed query/execute MCP, change cursors, knowledge packs,
  rekeying, integrity checks, and authorized whole-project deletion expose the
  same contract; and
- native spine export/import preserves unit title, ordering, all three evidence
  roles, and exact `advances`, `tests`, and `bounds` relationships.

## Automated verification

| Gate | Result |
|---|---|
| Full Python suite | `3092 passed, 1 warning in 171.54s` |
| Focused evaluation/project/API/MCP/model-drift suite | `924 passed, 1 warning in 4.79s` |
| TypeScript and production Vite build | Passed |
| Targeted changed-workbench ESLint | Passed with zero findings |
| Changed Python Ruff gate outside the legacy monolithic MCP server | Passed |
| MCP server Ruff baseline comparison | Unchanged: 14 existing findings on both `origin/main` and this branch |
| Patch whitespace check | Passed |

The production build retains the repository's existing large-chunk advisory.
The full Python run retains one upstream Pydantic settings forward-reference
warning. Repository-wide ESLint is not green on `main`: it reports the same
seven errors and two warnings in unrelated shared UI, Journal, Research Map,
and Settings files; every changed workbench file passes the targeted gate.

## Browser acceptance walkthrough

The production frontend and feature-branch API were served on
`127.0.0.1:19712` against an isolated import derived from
`prj_01KN51HD73DSY9ZR9C56JYRNYZ` (Invarllm).

1. Loaded manuscript `man_01M04709835GQA8RWNVCAHG3Z2` and selected branch
   `mpb_01M047098BY5B3472T6WRNGGNF`.
2. The matrix projected evaluation artifact
   `pla_01M047098DQB1ZF96FRFVWMJMP` v1 as `Blocked`, pinned exact experiment
   `exp_01M04709879E1FYHEV4N2CGF0S` and plan
   `epv_01M04709879E1FYHEV4N2CGF0T` v1, and showed no observation.
3. The explicit workbench action created mission
   `mis_01M0472QAKWWPMCN4SEDSRFH5J`; the button was replaced by immutable
   action lineage rather than allowing a duplicate.
4. Appended evaluation v2 with observation
   `obs_01M0473K4YXT3TX250EC9WCFSP`, run
   `run_01M04709894M3VEAF927K2B49F`, locator
   `elc_01M0473K507S4NEY7EQ6JCZJAH`, and result artifact
   `art_01M0473K4XQR5MYQN1X0WDMRAE`. The matrix showed the separately recorded
   positive metric direction and the explicit `supports` /
   `supports_as_worded` classification.
5. Filled the bounded result-unit fields and prepared proposal
   `spp_01M04747JFE137VHHTKJC2WR9A`. The manuscript remained unchanged and the
   proposal ledger showed one awaiting review.
6. Explicit apply created canonical result unit
   `mun_01M0474E5ACEFPDR7ATK6KE27D`, advanced the manuscript from revision 2
   to 3, restored the pending-proposal count to zero, and showed the exact
   artifact and allowed/prohibited interpretation in the canonical projection.
7. The workbench showed all three evaluation actions, changed the evaluation
   and outline stages from `Blocked` to `Needs review`, and emitted no browser
   console warning or error.

Visual inspection caught and removed one stale sentence that still described
experiment semantics as missing. The final rebuilt view instead states that
exact contracts classify experiment plans, observations, and locators against
bounded manuscript claims.

## Restart, pack, rekey, and deletion gate

A second disposable Invarllm-derived project exercised the complete service
path and retained exact identifiers for release evidence:

- branch `mpb_01M047ENA46YH4D2X551JAX79Y` at revision 4;
- evaluation artifact `pla_01M047ENA7TZYFCJM7Z4MDEA1S` v2;
- manuscript claim `mcl_01M047EN9XM8WG35Q2KSB1TJ37`;
- experiment `exp_01M047ENA1K629FAZPVEMB6P60`, plan
  `epv_01M047ENA1K629FAZPVEMB6P61`, observation
  `obs_01M047ESR6P0G3NKG09DG12RAZ`, and locator
  `elc_01M047ESR7PHZF4ZJ2EFFXB05H`;
- missing-evidence mission `mis_01M047ESQZSVR324EQ5N87Y16J`;
- proposal `spp_01M047ESRDA7N31VZRAZDG2DQW`; and
- applied result unit `mun_01M047ESRH7AJDQG2SXRWT1JSP` backed by
  `art_01M047ESR6P0G3NKG09DG12RAY`.

After a service restart, the API restored evaluation artifact v2, branch
revision 4, manuscript revision 3, the applied proposal state, the canonical
result unit, and the ordered three-action ledger. Exporting and re-importing
that completed project produced:

- three rekeyed evaluation events;
- one rekeyed result unit and artifact;
- the exact claim-unit relationship `tests`;
- no integrity findings and an empty `PRAGMA foreign_key_check`; and
- one restored managed artifact file.

Authorized deletion of the re-imported project removed three evaluation
events and three self-referential planning versions. This walkthrough exposed
and fixed SQLite's row-by-row `ON DELETE RESTRICT` behavior: immutable planning
versions and parented branches are now removed leaf-first during an authorized
whole-project deletion, without weakening their immutability triggers.

## Compatibility finding retained for M6

The live v2.8.1 exporter still includes five agentic-only staleness columns in
`claims` and `evidence_clusters`, while current `main` intentionally rejects
unknown pack columns. The source pack also contained six already-orphaned
entity links. To obtain a disposable real-project fixture, the test-only copy
removed those five unsupported fields and six invalid links; the live project
was not changed. The feature-branch exporter then round-tripped all PR 8 state
losslessly. General cross-branch migration of the older project remains an M6
intake/hardening concern and is not claimed as solved here.

## Exit decision

PR 8 satisfies its implementation and feature-branch verification gates. The
remaining review gate is GitHub CI and human review after the pull request is
opened. PR 9 may proceed only after this branch is merged; it remains
responsible for progressive outline authoring and manuscript-file drafting.
