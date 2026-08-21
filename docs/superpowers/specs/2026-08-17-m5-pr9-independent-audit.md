# Independent Audit — M5 Academic Argument and Manuscript Workbench

**Date:** 2026-08-17
**Scope:** (1) draft PR [#80](https://github.com/infinitywings/rka/pull/80)
(`agent/m5-progressive-outline`, M5 / PR 9 "progressive outline editing") and
(2) the proposed M5 redesign ("academic argument-and-drafting workbench",
M5a–M5e).
**Method:** read-only adversarial audit against a detached worktree at the PR
head. Six parallel inspection passes (schema/migrations, services/API/MCP,
web UI, docs/ADR/skills, tests/CI, external reference projects), with
executed reproductions on throwaway SQLite databases and a throwaway venv.
No live database, live project, or manuscript file was touched; the worktree
was left unmodified.

Every claim below is tagged: **[verified-repro]** = confirmed by executing
code end-to-end; **[verified-code]** = confirmed by direct reading with
file:line evidence (load-bearing sites re-checked first-hand by the lead
auditor); **[judgment]** = design opinion; **[inference]** = reasoned
conclusion not directly executed; **[external]** = observation of an external
project.

## Resolution addendum (2026-08-17)

This report remains the contemporaneous audit of PR #80 at head `79aa8a1`;
the baseline, reproductions, and recommendations below have intentionally not
been rewritten. The correction commit
[`f0f6fd9`](https://github.com/infinitywings/rka/commit/f0f6fd99c31da1000aca8b3489af7d0c7bcf4cb9)
subsequently landed on the same PR branch, and PR
[#80](https://github.com/infinitywings/rka/pull/80) was integrated into
`main` at that exact head after both GitHub checks passed and GitHub reported
no base-branch conflicts.

The correction closes all three P1 findings:

- **P1-1:** expansion now writes canonical nested evidence roles and has
  regression coverage for support, qualifier, counterevidence, and claim
  narrowing, including explicit removal.
- **P1-2:** AI proposals require attributed origin/context metadata; AI/MCP
  callers may prepare but cannot apply or reject outline proposals; ADR 0009,
  role tags, the Writer skill, and the API/MCP contract now use the same
  human-review boundary.
- **P1-3:** the editor is isolated by manuscript identity plus revision and
  resynchronizes its local order from canonical units.

The same correction also addresses P2-1, P2-2, P2-3, P2-5, P2-10, P2-12,
and the concrete test/CI defects identified in P2-15. Revalidation recorded in
[`2026-08-15-workbench-m5-pr9-exit-evidence.md`](2026-08-15-workbench-m5-pr9-exit-evidence.md)
includes the 3,126-test Python suite, the production web build, focused
MCP/semantic-patch suites, and a disposable outline run seeded from three
actual claims in `prj_01KN51HD73DSY9ZR9C56JYRNYZ`.

That real-project run did **not** establish complete live-pack portability.
The live export contained forward-only staleness fields and a pre-existing
orphaned entity-link target, so the acceptance run used a documented closed
four-row subset. The unresolved pack hierarchy/rekey and version-skew
integrity work therefore remains correctly assigned to PR 9.1 rather than
being erased from this audit trail. Other non-blocking P2/P3 findings remain
roadmap inputs unless a later change explicitly closes them.

---

## 1. Executive verdict

**Revise, then merge as the M5 foundation — do not merge as written, do not
replace.** (Option 3 of the mandate's §8, with a narrow pre-merge correction
gate.)

PR #80's core machinery is genuinely sound and survived adversarial probing:
proposal/apply integrity, stale- and double-apply protection, transactional
fingerprint rechecks, project scoping, and DB-level cross-project fail-closed
behavior all held under direct attack **[verified-repro]**. The `mun_`
identity model and the 1:1 outline profile are a defensible foundation that
does not structurally block the richer academic model later.

It must not merge in its current state because three P1 defects falsify
exactly the epistemic promises its own ADR and exit evidence claim were
exercised:

1. Explicit **support-evidence narrowing during expand is silently
   discarded** — a child always inherits the parent's full support set while
   the impact report claims the narrowing succeeded **[verified-repro,
   triple-confirmed]**.
2. **AI-authored outline content enters the ledger as `origin="human"` with
   no context manifest**, and the shipped Writer skill instructs the AI to
   prepare *and apply* its own proposals — against ADR 0009's "the researcher
   inspects and explicitly applies" and ADR 0006's AI-disclosure contract
   **[verified-code]**.
3. The outline editor's React keying can **silently hide canonical units**
   when switching manuscripts **[verified-code, mechanism traced]**.

The proposed §5 redesign diagnoses the right semantic gaps (typed rhetorical
roles, warrants, structured literature support, multi-dimensional readiness)
— the audit found live defects that its criticisms predicted (the
inheritance bug is literally the "silently treat parent evidence as
authoritative child support" failure it warns about, made worse). But the
redesign overshoots on process weight and should be adopted as an
**amendment sequence over this foundation**, not a replacement: most of its
value lands as typed bindings and deterministic checks on the existing
schema, not as six new contracts and nine readiness dimensions.

---

## 2. Verified baseline

| Item | Value | Status |
|---|---|---|
| PR #80 state | open, **draft**, `mergeable_state: clean` | verified via GitHub API 2026-08-17 |
| PR head | `79aa8a1559573d4619b16867f53d946ea150040a` | **matches recorded head — no drift** |
| PR base / merge base | `a49475b8cefadeea8486023fa010ad36841a8979` (= current `origin/main`) | matches recorded baseline; PR is up to date with main |
| Commits / diff | 5 commits, 49 files, +2670 / −94 | matches PR description; no scope creep beyond the outline feature + doc/skill mirrors |
| CI | single check `pytest` — **success** on head (run 31925669759, ~6.5 min) | verified |
| Review threads / comments / reviews | 0 / 0 / 0 | verified |
| Closes | issue #60 "[M5] PR 9" (milestone "M5 — Outline and drafting"; milestone contains only #60 and #61/PR 10) | verified |

**Reproduction environment:** clean clone; detached worktree at the PR head;
throwaway venv (Python 3.13.12, `pip install -e ".[llm,academic,workspace,dev]"`).
Docker was not used (audit constraint: disposable state only); the repo's
tests run fine outside Docker.

**Test commands executed** (all against the PR head):

- `python -m pytest tests/test_services/test_outline.py tests/test_db/test_migration_047.py -q` → **8 passed**
- `python -m pytest tests/test_api/test_native_manuscripts.py tests/test_mcp/test_native_manuscript_operations.py tests/test_services/test_knowledge_pack_native.py -q` → **50 passed**
- `python -m pytest --collect-only -q` → **exactly 3114 tests collected** (matches the claimed full-suite count)
- Full suite run to ~85% (~2650 tests) with zero failure markers, then intentionally terminated to save time; combined with green CI on the head, the "3114 passed" claim is credible.
- `tsc -b` and `eslint` on the changed web files: clean.
- Adversarial probes (throwaway scripts through the real services): double-apply **rejected**, stale apply **conflicted with both versions preserved**, cross-project parent **rejected at the DB**, cycles/level-inversions **accepted by raw SQL but rejected by the service validator**, expand-narrowing **bug reproduced end-to-end**.

**Does the recorded verification still apply to the head?** Yes mechanically —
the head is unchanged since the exit evidence was recorded and CI is green.
But three qualifications: (a) the "focused 968" selection is
unreconstructable from the docs (the natural
`test_services+test_api+test_mcp+test_db` selection collects 2475); (b) the
browser walkthrough, restart/resume, deletion-with-outline-data, and all
frontend/lint gates are one-time manual evidence — CI runs pytest only and
never builds the frontend; and (c) one recorded claim is **falsified**: the
exit evidence lists binding-narrowing disclosure as "contract exercised",
and narrowing is broken and untested (finding P1-1).

**Environmental limitations:** no Docker walkthrough was re-run; browser
verification was not repeated; the full pytest suite was not run to 100%
locally (CI covers it).

---

## 3. Goal-fit assessment

**Against issue #60 (the PR's actual mandate):** PR #80 delivers what the
issue asked — L2–L5 expansion/condensation, a writing-rationale view over
`mun_`, reorder with semantic diff, and Outline checkpoint integration —
with the significant caveat that two acceptance criteria are only partially
true: "expansion/condensation preserves semantic bindings" fails for support
narrowing (P1-1), and "reorder operations show downstream impact" covers
changed flat predecessors only, not argument dependencies.

**Against the §2 researcher journey:** the PR implements step 11
(progressive outline) and part of step 10 (claim/evidence binding
visibility) of the twelve-step journey. Steps 1–9 partially exist upstream
(M2–M4 spine, contribution, and evaluation artifacts); step 12
(draft/sync/revise) is correctly deferred. The current M5 tracker (PR 9 +
PR 10) covers steps 10–12 only. So the milestone as tracked is an *outline
and drafting* milestone, not yet the full argument workbench — the ROADMAP
text is honest about this; the gap is between the tracker and the §2
ambition, not inside the PR.

**Cognitive load:** the shipped editor is a per-unit rationale form plus a
drag list with reasonable progressive disclosure (collapsed forms, one open
at a time) **[verified-code]**. It is a competent structured editor, not yet
a load-reducing workbench: the edit form is a flat ten-field grid, there is
no "next consequential decision" affordance (only destructive badges), depth
cues are weak at L5, and a returning researcher must scan badges to find
what to do next. The redesign's complaint that a contract model can become
"a large form" is already mildly true of the shipped profile.

**Readiness honesty:** UI copy is mostly careful ("Rationale complete";
stage verdict "Ready" only after an explicitly resolved checkpoint), but the
API field name `checkpoint_ready`, a five-field shallow predicate, overstates
— and the "missing declared_blocker" badge inverts meaning (P2 findings
below).

---

## 4. Findings by severity

No P0 was found: nothing bypasses ratification, forges before-states, or
destroys provenance. Consolidated and de-duplicated across all six passes.

### P1 — must fix before merge

**P1-1. Expand silently ignores explicit support-evidence narrowing; the
child always inherits the parent's full support set.** [verified-repro;
independently found by three passes; source re-checked by lead auditor]
`rka/services/outline.py:204-243` stages parent support from the exported
flat key `evidence_ids`, validates the requested subset, then writes it
under the key `support_ids` while spreading the full parent dict (including
`evidence_ids`) into the child. The normalizer
(`rka/services/manuscript_native.py:2366-2370`) reads
`evidence.get("support", raw.get("evidence_ids", []))` and never reads
`support_ids`. Qualifier/counterevidence narrowing works only by key-name
coincidence. End-to-end repro: a child requesting `support_ids=[ev_a]` from
a parent bound to `[ev_a, ev_b]` is persisted with **both** as authoritative
support; `support_ids: []` is equally ignored; the proposal's `impact` block
reports `"inherited": ["claim_links", "support", ...]` as if narrowing
worked, and no validation finding fires. Both contradictory keys are frozen
verbatim into the immutable proposal spine. This falsifies ADR 0009 §3
("unless the request explicitly narrows them to subsets"), the plan, and
`skills/writer/references/architecture.md:164-166` — and it is precisely the
"parent evidence silently treated as authoritative child support" failure
the M5 redesign proposal criticizes. No test anywhere narrows any binding.
*Remediation:* emit a nested `evidence: {support, qualifier,
counterevidence}` mapping in `_expand` (the mapping wins in the normalizer)
and drop the leftover flat keys from the parent spread; add narrowing
regression tests for all three roles plus `claim_keys`.

**P1-2. AI provenance hole: outline proposals are hardcoded
`origin="human"` with no context manifest, and the Writer skill instructs
the AI to self-apply.** [verified-code]
`rka/services/outline.py:136` hardcodes `origin="human"` (and `:131`
silently coerces unknown actors to `executor`). ADR 0006 §4 requires
AI-origin proposals to carry an immutable `pcm_` context manifest, enforced
by `rka/models/semantic_patch.py:144-152` — which for `origin="human"`
*forbids* a manifest. Yet `rka/skills/writer/SKILL.md:272-276` routes "all
direct or AI-assisted outline changes" through this endpoint and tells the
Writer to "apply the resulting proposal … in a separate
`apply_semantic_patch_proposal` call" (`references/workflows.md` step 15) —
while ADR 0009 §2 promises "no action mutates the manuscript before the
researcher inspects and explicitly applies that proposal" and the MCP op
docstrings tag the surface "[PI/WEB_UI]"
(`rka/mcp/operation_args.py:2746-2752`). There is no server-side actor
restriction on apply (`ProposalActor` includes `executor`). In the Writer's
mission-spawned unattended path there is no human between prepare and apply,
and AI-authored rationale (jobs, takeaways, evidence plans, citation
intentions) enters the permanent ledger labeled human with no disclosure
record. *Remediation:* accept `origin` + manifest on the outline route
(default human for `web_ui`); either restrict apply of outline proposals to
`pi`/`web_ui` actors or amend ADR 0009 to say explicitly that the
Outline-checkpoint resolution — not per-proposal apply — is the human gate;
make the role tags, skill text, and ADR tell one story.

**P1-3. Outline editor cross-manuscript state bleed can silently hide
canonical units.** [verified-code, mechanism traced]
`web/src/pages/ManuscriptWorkbench.tsx:441` keys `OutlineEditor` by the bare
`outline.manuscript_revision`; `draftOrder` is initialized once per mount
and never resynced (`web/src/components/workbench/OutlineEditor.tsx:48`),
and rendering maps `draftOrder` and silently drops unknown keys (`:57-58`).
Switching between manuscripts that share a revision number (small integers)
with warm react-query caches reuses the component instance: units of the
new manuscript that don't share a `local_key` with the old one are simply
not rendered, overlapping units render in the old order, and a spurious
"Local order preview only" banner appears. The server rejects any resulting
bad reorder (exact-key-set check), so no corruption — but a tool whose
premise is faithful projection of canonical state silently hides canonical
units. *Remediation:* key by `${manuscript_id}:${manuscript_revision}` and
resync `draftOrder` when the canonical order changes.

### P2 — should fix before or immediately after merge

**Service/data layer**

- **P2-1. MCP typed dispatch drops explicit-null patch fields.**
  [verified-repro] `rka/mcp/verb_dispatch.py:3009` uses
  `model_dump(exclude_none=True)`, so `patch={"blocker": null, "title":
  "New"}` silently keeps the blocker while applying the title, and a
  blocker/transition/title/parent can never be cleared via MCP
  (`{"blocker": null}` alone → misleading 422). The codebase already
  special-cases `update_manuscript` for exactly this (`:3001-3007`); the
  outline op didn't get the treatment. REST and the web UI are unaffected.
- **P2-2. The Outline checkpoint dependency snapshot excludes typed
  evidence bindings.** [verified-code]
  `rka/services/manuscript_native.py:1845-1898` hashes claims, units,
  profile fields, and the claim-unit map, but not `manuscript_unit_evidence`
  / `manuscript_claim_evidence` — while the outline UI presents "N evidence
  bindings" as part of what the PI approves. A post-approval binding swap
  does not supersede the resolved checkpoint. (`draft_section` snapshots do
  include bindings, `:1969-1984`.)
- **P2-3. Reorder accepts hierarchy-incoherent flat orders.**
  [verified-repro] A child can be placed before its parent
  (`["INTRO.A","METHOD","INTRO"]` applied cleanly); `_reorder`
  (`rka/services/outline.py:349-380`) checks set-equality only, and the
  hierarchy validator never checks sequence-vs-parent order or subtree
  contiguity. Transition impact reports changed *flat predecessors* only —
  no argument-dependency analysis — and stale `transition_from_previous`
  texts survive reorders without any completeness consequence. The UI's flat
  drag list makes this reachable in two clicks.
- **P2-4. `upsert_argument_spine` remains a full ledger bypass while the
  projection advertises the opposite.** [verified-repro] The pre-existing
  `PUT /api/manuscripts/{id}/argument-spine` (role-tagged **[ANY]**,
  `rka/mcp/operation_args.py:2076-2078`) rewrites every outline field with
  only an `expected_revision` guard and zero proposal entries, while
  `get_outline` returns `"mutation": "semantic_patch_then_explicit_apply"`
  (`rka/services/outline.py:95-100`) and ADR 0009 says every structural edit
  is a proposal. Likely a deliberately retained Writer-sync surface
  [inference], but it makes the advertised policy string false and answers
  the mandate's invariant #6 question in the negative. Decide, restrict, or
  document (PI decision D3 below).
- **P2-5. Unconditional `_resequence` poisons the review signal.**
  [verified-repro] `rka/services/outline.py:127,382-389` renumbers every
  unit to `index*10` on *any* action; on manuscripts whose stored sequences
  aren't already multiples of ten, a one-field rationale edit produces
  sequence diffs for every unit plus a spurious `OUTLINE_ORDER_CHANGED`
  warning naming every key (`rka/services/semantic_patch.py:893-905`) —
  cry-wolf noise inside the exact review gate the apply decision depends on.
- **P2-6. Change-event triggers under-attribute profile events; no delete
  trigger.** [verified-repro] Migration 047's triggers leave the dedicated
  `change_events.manuscript_id`/`manuscript_unit_id` columns NULL (details
  JSON only), unlike every other manuscript-aggregate trigger (035/038
  pattern), so `change_tracking.py:235,247-248` never attributes profile
  events; profile deletion emits no event at all. Masked today because the
  sanctioned write path also updates the unit row. Needs migration 048.
- **P2-7. Knowledge-pack import can materialize hierarchy the service
  refuses, then bricks the proposal pipeline.** [verified-repro] Raw SQL
  accepts cycles/level-inversions/removed-parents (only self-parenting has a
  CHECK); pack import inserts rows verbatim after ID remap, and
  `check_integrity` has no outline category
  (`rka/services/knowledge_pack.py:2123-2152`). After importing a corrupted
  pack, every outline proposal raises "outline hierarchy contains a cycle"
  at prepare *and* apply — the sanctioned editing path is wedged (reads
  still work; recovery requires a raw spine upsert).
- **P2-8. Import rekey misses entity IDs inside the four JSON intention
  columns.** [verified-code] `evidence_plan`, `figure_intentions`,
  `table_intentions`, `citation_intentions` are in neither
  `_JSON_ID_COLUMNS` nor `_PROSE_TEXT_COLUMNS`
  (`rka/services/knowledge_pack.py:707-713`), so `clm_`/`lit_` tokens users
  are encouraged to put there survive import pointing at source-project IDs
  — the exact provenance-rot class the prose-rewrite pass exists to prevent,
  and a poison pill for any future typed extraction of these fields.
- **P2-9. New children can shed qualifiers/counterevidence warning-free.**
  [verified-code] Qualifier narrowing *works* (key-name collision), and the
  `UNIT_EVIDENCE_BINDING_REMOVED` warning compares only units present in
  both snapshots — a brand-new child that keeps a claim but drops its
  qualifiers produces zero findings, against ADR 0006's warning philosophy.
  Combined with P1-1, expand is systematically biased toward over-supported,
  under-qualified children.

**Design/docs**

- **P2-10. L2–L5 semantics are contradictory across normative documents.**
  [verified-code] The pipeline plan
  (`docs/superpowers/plans/2026-08-14-…md:372-375`) defines L3 = section
  skeleton, L4 = claim/paragraph units, L5 = evidence bullets/transitions/
  figures/citations; the shipped skill says L2 = communicative sections →
  L5 = claim-sized units (`rka/skills/writer/SKILL.md:264-266`); tests and
  the walkthrough seed sections at L2; migration 047 defaults everything to
  L4; ADR 0009 uses "L2–L5" eleven times without defining any level. Two
  agents following different documents will build incompatible hierarchies,
  and a stored "L4" is uninterpretable. (Also: the validator error "parent
  must be at a higher outline level" means *smaller number* — confusing.)
- **P2-11. Exit-evidence overstatement.** [verified-code] The plan's release
  gate requires a "disposable **real-project** browser walkthrough"; the
  recorded walkthrough used a two-unit synthetic fixture mirroring the unit
  test (prior milestones used real projects — DelaySteer, CPSEval,
  Invarllm). The spec's "Contract exercised" list asserts binding-narrowing
  disclosure (broken and untested — P1-1) and Writer-guidance conformance
  (backed only by a 2-test byte-identity packaging check). The mechanical
  pack/restart/FK evidence is honestly described; the framing of the
  contract list as semantic adequacy is not.

**UI**

- **P2-12. "missing declared_blocker" badge inverts meaning.**
  [verified-code] The service appends `declared_blocker` to the `missing`
  list when a blocker **exists** (`rka/services/outline.py:59-60`); the UI
  prefixes every entry with "missing" (`OutlineEditor.tsx:201`), telling the
  researcher to *add* a blocker.
- **P2-13. Condense is one click with a fabricated attestation.**
  [verified-code] Unlike edit/expand/reorder (typed reason required),
  condense submits the canned reason "Condense X after reviewing all
  descendant bindings" (`OutlineEditor.tsx:219-234`) — a review claim nobody
  performed, recorded into the immutable ledger — and always condenses all
  descendants although the service supports subsets.
- **P2-14. Assorted UI correctness friction.** [verified-code]
  FastAPI 422 arrays render as `API Error 422: [object Object]`
  (`web/src/api/client.ts:44-53`); creating a checkpoint while proposals are
  pending strands them `conflicted` with no warning (`create_checkpoint`
  bumps the revision, `manuscript_native.py:769`); an external revision bump
  plus focus-refetch remounts the editor and silently discards in-progress
  form text.

**Process**

- **P2-15. Test-integrity and CI gaps.** [verified-repro] The condense-union
  test is vacuous (the child is seeded with the same evidence ID the parent
  already holds; the union code could be deleted and it still passes);
  `test_hierarchy_rejects_unknown_parent_and_cycles` contains **no cycle
  test**; the reorder test never applies its proposal; three headline
  invariants are "verified" by asserting hard-coded constants from the
  service's own `impact` dicts (`rka/services/outline.py:152-156, 261-267,
  341-347, 374-380`). CI runs pytest only — no TypeScript build, no lint, no
  browser smoke: a TS break in the 459 new frontend lines would pass CI
  green. Adversarial probes showed the untested concurrency paths behave
  correctly today, so this is regression exposure, not present defect.

### P3 — track and fix opportunistically

[all verified-code or verified-repro unless noted]

1. `checkpoint_ready` = five-field completeness predicate that ignores
   checkpoint state (`rka/services/outline.py:93`); a superseded checkpoint
   and `checkpoint_ready: true` coexist. Rename (`rationale_complete`) or
   fold checkpoint status in. Two-value `completeness` also diverges from
   ADR 0001's four-value readiness vocabulary.
2. Legacy units silently materialize an invented `outline_level=4` profile
   row on the next spine apply (vs. ADR's "no invented metadata"); legacy
   manuscripts can only expand L4→L5 until re-leveled.
3. Outline checkpoint dependency snapshots changed shape without bumping
   `rka.checkpoint-dependencies/v1` — every pre-upgrade resolved outline
   checkpoint flips `dependency_current: false` and gets superseded on the
   first post-upgrade apply, silently revoking PI approvals. Bump the
   version string and note in CHANGELOG.
4. Pack `_FK_COLUMNS` omits `parent_unit_id` — corrupt packs fail with a
   hard IntegrityError instead of the registry's contractual NULL-out.
5. Condense discards which child contributed which binding/plan (forensic
   ledger diffing is the only record); acceptable for now, relevant to the
   warrant design later.
6. Blank titles (`"   "`) accepted; `claim_keys` cannot be `[]` (a child can
   never opt out of claim inheritance — the redesign's candidate/unallocated
   criticism applies); children copy the parent's `kind`/`artifact_ref`, so
   expanding a `result` unit silently duplicates the artifact binding.
7. `SemanticPatchConflictError` maps to 422 instead of 409 in the
   prepare-race window; silent actor coercion to `executor`
   (`outline.py:131`); "[PI/WEB_UI]" tags vs. instructed callers tell three
   different stories.
8. Write amplification: every one-field edit rewrites the whole spine
   (unconditional unit UPDATEs + profile upserts + delete/reinsert of all
   unit evidence, `manuscript_native.py:2603-2732`) — ~150+ immutable ledger
   rows per edit on a 50-unit manuscript, and the ledger is never pruned.
   Needs no-op detection before manuscripts grow; also a hard blocker for
   any future append-only child contracts.
9. Dead surface: `ManuscriptUnitCreate`/`Update` grew 11 outline fields no
   code consumes, with none of the real path's validation
   (`rka/models/manuscript_native.py:241-290`); UI types for
   title/level/parent patches that the form never sends; the eagerly fetched
   `workbench.spine` query whose only consumer this PR deleted.
10. JSON CHECKs validate array-shape only (non-string elements storable by
    direct writers); 20k-char fields render unclamped in unit cards; drag
    cannot drop at the end of the list; intention lists dedup silently;
    "PR 9 outline contract" jargon can leak into user-facing toasts.

### What was verified sound (rely on this)

- **Proposal/apply integrity under attack** [verified-repro]: preparation
  never mutates; apply is the only write path; double-apply and stale apply
  are rejected with evidence preserved (`conflicted` status, both bases in
  the event log, raise-after-commit); preview/persist share one
  `BEGIN IMMEDIATE` snapshot — no TOCTOU.
- **Concurrency tokens at both hops** [verified-repro]: `expected_revision`
  on prepare (409) plus revision+SHA-256 fingerprint recheck inside the
  apply transaction; every canonical mutation path bumps the revision.
- **Scoping fails closed** [verified-repro]: project-scoped services and
  proposal reads (cross-project apply = 404); composite
  `(id, manuscript_id, project_id)` FKs with `PRAGMA foreign_keys=ON`
  reject cross-project parents at the DB.
- **Migration 047 is idempotent and atomic** [verified-repro]; the
  `schema.sql` omission is *not* a fresh-install bug (fresh installs run the
  full migration chain); 1:1 profile enforced by PK; pre-047 units project
  honest defaults and are surfaced `needs_review`.
- **Knowledge pack and deletion wiring** for the new table (registration,
  insert order, direct-ID rekey including `parent_unit_id`, prose-column
  rewrite, purge order) is present and round-trip-tested — modulo P2-7/P2-8.
- **Hierarchy validation on its path** (unknown/self/removed parent, level
  order, cycles, duplicate keys, L5-expand refusal, condense descendant
  closure, reorder exact-set) [verified-repro].
- **MCP/REST/type parity**: typed unions, schema registry, dispatch, and UI
  types match field-for-field; the PR's updated op counts (150 = 67 reads +
  83 writes) are **accurate** (independently counted; the pre-PR "139"
  docs were already stale).
- **Skill mirrors** `rka/skills/writer` ≡ `plugin/skills/writer`
  byte-identical.
- **No silent exception swallowing** in the new code; REST routes are thin
  adapters per project convention.

---

## 5. Academic-writing model assessment

**Unit identity (mandate Q3).** `mun_` as the stable identity across L2–L5
is correct and should be kept. One abstraction can carry sections through
paragraph plans because identity, hierarchy, and bindings are the shared
substance; captions and result units fit as `kind`-typed units. What a
single abstraction should *not* carry is the proposed L5 "atomic rhetorical
move / drafting beat" as a canonical record — that is drafting-time
deliberation, cheap to create and destroy, and making each beat a `mun_`
with a profile row would explode the ledger (see P3-8) and the researcher's
bookkeeping. **[judgment]** Keep canonical `mun_` for L2–L4 (+L5 where a
unit genuinely owns evidence, e.g. a caption); represent beats, if at all,
as an ordered list *inside* a paragraph-level unit's plan.

**Level semantics (Q3, §5.2).** The most urgent semantic fix is not adding
meaning to levels but removing it: the plan and the skill already ship
**contradictory content-based level definitions** (P2-10). Encoding "what
kind of thing this is" in a depth number conflates two dimensions and is
already causing drift. **[judgment]** Redefine level as *pure depth* and add
a typed `unit_role` (section / argument-block / paragraph-plan / result /
caption / appendix …). This resolves the contradiction without data
migration (existing levels stay valid as depths), makes genre variation
natural (a short paper's argument block can sit at depth 2), and gives the
readiness engine a role to key requirements on — which is the §5.3 insight
worth keeping.

**The Academic Writing Unit Contract (§5.3, Q4).** Directionally right,
wrong packaging. The six contracts as six new record types would triple the
surface and duplicate existing authorities: the evidence contract overlaps
`manuscript_unit_evidence` + `ecl_` locators; the literature contract
overlaps the reference authority; the argument contract's claim link
overlaps `manuscript_claim_units`. **[judgment]** Land the same content as
(a) a few typed fields on existing rows and (b) two new *binding* tables:

- **Reader contract** → mostly exists (job, takeaway, quick-reader role);
  add `reader_question` and `significance` only if role-required, not on
  every unit.
- **Argument contract** → `unit_role` + rhetorical `move` on the unit;
  warrant on the binding (below); dependencies as typed unit-to-unit edges
  only when the reorder validator learns to use them.
- **Evidence contract** → extend `manuscript_unit_evidence` with
  `supported_proposition` and `warrant`; "missing evidence" is a stored gap
  marker (ARIS's `DATA_NEEDED` pattern [external]), not free text in
  `evidence_plan`.
- **Literature contract** → a per-unit citation-binding table referencing
  the existing reference authority (see below), *replacing* the free-text
  `citation_intentions` over time.
- **Defense contract** → deliberation-plane records linked to units; only
  the materiality classification (M1/M2 vs. M4/S, which the Writer skill
  already defines) belongs in canonical state.
- **Draft contract** → belongs entirely to the PR 10 sync slice.

The current free-text `evidence_plan`/`*_intentions` lists **will become
unstructured text dumps** — they already hold entity IDs that the pack
rekey misses (P2-8). Treat them as a transitional UX affordance, keep them,
but plan their contents' graduation into typed bindings, and fix the rekey
now so the prose stays extractable.

**Warrants (Q2, §5.4).** A warrant is authorial reasoning about *why this
evidence supports this claim under these assumptions* — per
claim-evidence-use, not per claim and not per unit. **[judgment]** It
belongs as a reviewable text attribute on the claim↔evidence binding
(optionally shared/versioned later if the same warrant is reused across
units), not as a first-class entity in v1 (premature — no consumer yet
justifies the lifecycle cost) and not as a generated view (it is authored
content; nothing existing derives it). ARA's `Conditions` +
`Falsification criteria` on claims [external] are the complementary
claim-side fields and double as ARA-projection enablers.

**Rhetorical moves and literature (§5.5, Q7).** Adopt a small core move
enum plus genre templates as *data* (venue/genre template records), not
code — the §5.5 catalog is a fine starting template library, not a schema.
For citations, the answer to "how to avoid duplicating the reference
authority" is structural: the new record is a **binding** (reference key →
unit, with `citation_role`, `supported_proposition`, `verification_state`,
optional comparison axis), never a copy of bibliographic data. ARA's
five-way `imports|bounds|baseline|extends|refutes` typing [external] is a
field-tested starting enum; PaperSpine's rule that `verified` requires a
stable identifier (DOI/arXiv/URL) or it counts as self-attestation
[external] should be adopted verbatim — it operationalizes invariant #9.

**Readiness (§5.6, Q6).** Nine dimensions with four verdicts each is the
right *reporting* shape but the wrong *gating* shape. Deterministic and
therefore block-eligible: structural readiness, claim-link presence,
evidence-binding presence, citation `verification_state`, source-sync
fingerprints (later). Warn-only (judgment involved, human or LLM):
rhetorical fit, contribution alignment, cross-section coherence,
venue/genre fit — following ARIS's rule that automation may *drive* but
never *acquit* [external]. The current binary five-field check is an
acceptable v1 of the "structural" dimension; the defect is its name
(`checkpoint_ready`) and the two-value vocabulary, not its existence.

**Evaluation and defense.** M4 already ratified evaluation contracts; the
workbench needs to *connect* RQ→evaluation→result units in views (the
Claims-Evidence Matrix pattern [external]), not remodel them.

**Private/public boundary (§B, invariant 11).** The Writer's
`persuasive_framing.md` was read adversarially and is **balanced**: the
materiality test, the PI-refusal rule ("refuse that omission … do not
advance the affected unit"), and the integrity boundary directly implement
"strength-first without concealing material limitations"; no text was found
that pushes toward invented citations or fluent unsupported prose
[verified-code]. Two soft spots to close: an *uncertain* materiality
classification defaults to internal-only with no rule blocking the affected
unit while the question is open; and the "salient boundary" judgment has no
mechanical check. Both are one-paragraph skill amendments.

**Epistemic pipeline conformance.** No automatic promotion between classes
was found; `upsert_argument_spine` never creates ratifications; checkpoints
resolve only via same-project PI decisions [verified-code]. The one design
tension: expand's default inherit-*all* claim links means a new unit
acquires claim bindings without a per-child decision, and those defaulted
bindings then satisfy the `intended_claim` completeness check — disclosed,
but defaulted-on (see Q5 below).

---

## 6. Architecture alternatives

**Simpler alternative — "typed bindings, no contracts" [judgment]:**
keep the 047 profile exactly as shipped; add only (a) `unit_role` on the
profile, (b) `warrant` + `supported_proposition` on
`manuscript_unit_evidence`, (c) one citation-binding table over the existing
reference authority, and (d) readiness as a *computed view* (no stored
verdicts). No deliberation plane in the DB — alternatives and reviewer
simulations live in files/journal entries as today. *Strengths:* ~2 small
migrations; no new lifecycle; every invariant preserved; delivers the three
highest-value semantic gaps (roles, warrants, verified citations).
*Weaknesses:* no dependency-aware reorder; coherence QA stays manual;
defense analysis remains unstructured; readiness can't accumulate reviewer
state.

**Stronger alternative — "argument graph plane" [judgment]:** first-class
typed edges — claim→unit allocation (with candidate/allocated status),
unit→unit dependencies (`defines_for`, `uses`, `answers`,
`validated_by`), and versioned warrant records on claim-evidence edges —
plus readiness as graph queries and reorder validation over dependencies
(definition-before-use, RQ-to-result). *Strengths:* makes §5.7's reorder
semantics and §5.6's coherence checks actually computable; natural ARA
projection; candidate/allocated status solves the P1-1 class structurally.
*Weaknesses:* substantial service rework — the current full-spine
delete-and-reinsert write path (P3-8) is incompatible with edge lifecycles
and must be rebuilt first; higher modeling risk of over-formalization; the
UI cost of making researchers maintain edges is real (Q5).

**Recommended path:** simpler alternative first (M5a′ below), graduating
toward specific graph features (allocation status, then dependencies) only
when a consumer exists (dependency-aware reorder, coherence QA) — never as
speculative schema.

---

## 7. Revised milestone and migration recommendation

Smallest safe sequence, each PR shippable and invariant-preserving:

- **PR 9 corrections (pre-merge, on `agent/m5-progressive-outline`):**
  P1-1 (+ narrowing tests for all roles), P1-2 (origin/manifest parameters
  + one-paragraph ADR 0009 amendment recording the apply-actor policy),
  P1-3 (React key + draft-order resync), P2-12 (badge wording), P2-5
  (resequence only on reorder/expand/condense), P2-1 (MCP `exclude_unset`
  for the outline patch), P2-15's test repairs (real condense-union test,
  real cycle test, reorder-apply test). Roughly a day of focused work; no
  schema change.
- **Merge PR #80** relabeled in ROADMAP/CHANGELOG as the **M5 outline
  foundation** (structure + rationale + proposals), explicitly not the
  argument workbench.
- **PR 9.1 — hardening (migration 048):** trigger attribution columns +
  delete trigger (P2-6); pack outline-integrity category + JSON-intention
  rekey (P2-7/P2-8); checkpoint snapshot: include typed evidence bindings
  and bump the dependency-payload version (P2-2, P3-3); rename
  `checkpoint_ready`→`rationale_complete`; qualifier-drop warning parity
  (P2-9); reorder parent-before-child validation (P2-3); no-op detection in
  spine writes (P3-8 — prerequisite for everything later).
- **PR 9.2 — M5a′ semantic core (migration 049):** `unit_role` +
  level-as-depth ADR amendment (P2-10, D2); `warrant` +
  `supported_proposition` on unit-evidence bindings; citation-binding table
  with `verification_state` (stable-identifier rule); `conditions` +
  `falsification_criteria` on manuscript-claim versions (ARA-projection
  enablers); readiness v2 = deterministic dimensions with
  `pass/warn/not_applicable` (structural may block; nothing else blocks).
- **PR 10 — narrowed M5c v1:** Markdown-only, read-first sync — stable
  non-rendering anchors, per-unit fingerprints, drift *detection* and
  import-as-proposals before any write/merge capability; LaTeX and
  three-way merge deferred until the anchor protocol survives a real
  project. (No external prior art exists for the two-authority protocol —
  all three reference projects are single-authority [external] — so
  de-risk it in the smallest possible slice.)
- **M5b — workbench views + deterministic writing-packet assembler**
  (ARA-manifest / ARIS-query-pack shape: size-capped, regenerated,
  provenance-listing [external]); AI stays host-agent-driven,
  proposal-only — no embedded LLM service is needed; the packet assembler
  is the only new server capability required.
- **M5d — QA as advisory checks:** contribution-promised-vs-delivered and
  RQ-vs-results matrices (deterministic joins), citation-support and
  fourth-wall lints (deterministic), reviewer-simulation (LLM, warn-only).
- **M5e — real-project validation as a standing gate for every slice
  above** (restoring the real-project walkthrough discipline PR 9's exit
  evidence dropped), not a terminal milestone.

**Compatibility strategy:** keep migration 047 as-is (no destructive
rework — the composite-key design deliberately supports child tables);
all later changes additive; fix the JSON rekey *before* any typed
extraction of intention prose so imported projects don't carry dangling
IDs into the typed era; bump the checkpoint-dependency payload version
whenever snapshot shape changes.

---

## 8. Test and evaluation plan

**Deterministic (pytest), priority order** — the ten gaps from the test
audit, all implementable today: (1) condense with *distinct* child bindings
asserting exact unions and absence of removal findings; (2) cycle and
level-inversion rejection via outline proposals; (3) reorder applied
end-to-end (final order, sequences, bindings via DB); (4) stale + double
apply on the outline path; (5) project deletion with profile rows +
`PRAGMA foreign_key_check`, and unit-delete RESTRICT; (6) migration 047
constraint suite (level bounds, JSON CHECKs per column, self-parent, update
trigger, idempotent re-run per the 019/023 convention); (7) pre-047
compatibility projection (absent profile → level 4, `needs_review`,
`checkpoint_ready` false); (8) expand subset semantics for all three
evidence roles + `claim_keys` + superset rejection + L5 rejection; (9) REST
error contract (409/404/422, cross-project isolation); (10) checkpoint
robustness (pending stays pending across prepare/apply) + unicode/20k-char
round-trips. Add property-based tests (hypothesis) for hierarchy validation
and reorder over generated trees.

**CI additions:** frontend `tsc` + production build + ESLint (currently a
TS break passes CI green); a scripted Playwright smoke replacing the manual
browser walkthrough; optionally the pack round-trip on a fixture with a
multi-level outline.

**Test-integrity rule:** stop asserting the service's own hard-coded
`impact` constants as verification of invariants — assert re-queried
canonical state.

**Human/expert evaluation (cannot be deterministic):** outline-content
quality, rhetorical fit, and readiness-guidance usefulness need the M5e
real-project set — at minimum one security/systems paper, one empirical
ML paper, one noisy longitudinal RKA project, one existing multi-file LaTeX
manuscript (for PR 10), and one paper+ARA dual projection. Each slice's
exit evidence should name the real project used, per the pre-PR-9
convention.

---

## 9. Merge recommendation for PR #80

**Keep draft; land the pre-merge correction list on the same branch; then
merge, relabeled as the M5 outline foundation.** Explicitly:

- **Blocking (must land before merge):** P1-1 + narrowing tests; P1-2
  (origin/manifest + apply-policy ADR sentence + skill-text reconciliation);
  P1-3; P2-12; P2-5; P2-1; the three test repairs in P2-15.
- **Strongly recommended with merge:** P2-13 (condense reason form),
  checkpoint-while-pending warning (P2-14), 422-detail formatting (P2-14).
- **Explicitly deferred to PR 9.1/9.2** (file follow-up issues at merge
  time): P2-2, P2-3, P2-4 (needs PI decision D3), P2-6, P2-7, P2-8, P2-9,
  P2-10 (needs D2), P2-11 (process), all P3s.

**Why not the other options:** *merge as written* ships a falsified
contract clause with the exit evidence claiming it was exercised; *split*
buys nothing — the 49 files are one coherent feature and its doc/skill
mirrors, and carving it up now costs more than the corrections; *keep
draft for a schema redesign* is unjustified — the schema audit found the
1:1 profile does **not** paint the richer model into a corner (composite
keys support child tables; the real forward risks are the JSON rekey gap
and the write-path amplification, both fixable additively); *replace* would
discard a verified-sound proposal/concurrency/scoping core that took real
care to build and that the redesign would have to rebuild identically.

**Delivery consequences:** PR 10 stays blocked until the foundation merges;
the correction gate is small (est. one focused day) and does not require a
new migration; ADR 0009 needs a short amendment, not a rewrite; issue #60's
acceptance criteria become true as written once P1-1 and the reorder note
land.

---

## 10. PI decisions required

Only choices that code, evidence, or established principles cannot settle:

- **D1 — Outline apply authority.** May an unattended Writer agent apply
  its own outline proposals (with the Outline checkpoint as the sole human
  gate), or is per-proposal apply restricted to `pi`/`web_ui`? ADR 0009's
  current sentence and the shipped skill contradict each other (P1-2); the
  server enforces neither. This decision also fixes the "[PI/WEB_UI]" role
  tags.
- **D2 — Level vocabulary.** Adopt level-as-pure-depth + typed `unit_role`
  (auditor recommendation), or keep content-based levels — and if the
  latter, which of the two shipped contradictory definitions (plan vs.
  skill) wins and what backfills existing L4 defaults?
- **D3 — The `upsert_argument_spine` escape hatch.** Keep it [ANY] and
  document it as the orchestrator bulk-sync path (correcting the projected
  `policy` string), restrict its role, or route it through auto-applied
  ledger proposals. Invariant #6 is currently false as advertised.
- **D4 — Milestone framing.** Re-scope the M5 tracker to the M5a′/9.1/9.2 +
  narrowed PR 10 sequence in §7, or keep the current two-issue plan and
  treat §5's redesign as M6 material.
- **D5 — Readiness blocking policy.** Confirm that only deterministic
  structural checks may ever block an Outline checkpoint, with all
  judgment-based dimensions warn-only (the §7/§8 plans assume this).
- **D6 — Exit-evidence standard.** Reinstate the real-project walkthrough
  requirement for milestone gates (PR 9's gate was recorded against a
  two-unit synthetic fixture).

---

## Appendix — Answers to the ten auditor questions (§9 of the mandate)

1. **Right problem?** Yes at the semantic layer (roles, warrants, citation
   verification, readiness honesty fix real observed failures — one of
   which, P1-1, the audit reproduced); no at the process layer as specced —
   six contracts × nine dimensions on every unit would out-weigh the
   cognitive load it claims to reduce. Adopt the semantics, halve the
   ceremony.
2. **Warrants:** typed attribute on the claim↔evidence binding, reviewable;
   promote to shared versioned records only when reuse demands it; never a
   generated view (authored content).
3. **Single `mun_` abstraction:** yes for sections→paragraph plans, result
   units, captions, appendices (via `kind`/`unit_role`); no for atomic
   drafting beats — keep those inside a unit's plan, out of the ledger.
4. **Canonical vs. deliberative vs. file-local:** canonical = identity,
   hierarchy, role, claim/evidence/citation bindings + warrants,
   materiality classifications, readiness *inputs*; deliberative =
   alternatives, reviewer simulations, defense analyses, exploratory
   sketches, readiness *verdicts* from judgment; file-local = exact prose,
   formatting, beat ordering.
5. **Candidate/unallocated inheritance:** useful safety — P1-1 and the
   `claim_keys min_length=1` constraint show today's default-inherit-all is
   already causing epistemic over-attribution. Keep bookkeeping cheap:
   inherit as *candidate*, one-click accept-all, and gate only readiness
   (not editing) on allocation.
6. **Deterministic-enough coherence checks to block:** claim allocation
   presence, citation verification state, structural hierarchy/order,
   fingerprint currency, contribution↔RQ↔result *presence* joins. Not
   block-eligible: any semantic-fit judgment (definition-before-use beyond
   declared dependencies, tone, differentiation quality).
7. **Citation support without duplicating the reference authority:**
   bindings referencing `lit_`/reference keys, never copied bibliographic
   fields; verification state lives on the binding; adopt the
   stable-identifier-or-self-attestation rule.
8. **Exploratory vs. publication drafts:** sufficient *if* exploratory text
   is structurally non-citable from canonical records (no binding may point
   into an exploratory sketch) and discoveries route back through
   interpretation→claim→review; with those two rules it strengthens rather
   than weakens provenance.
9. **Two-authority source sync:** feasible for Markdown with per-unit
   anchors + fingerprints + import-as-proposals; genuinely risky for
   multi-file LaTeX (macros, includes, generated text, Git merges rewriting
   anchor lines). No external prior art exists among the reference projects
   [external]. De-risk read-first (§7); treat write-side three-way merge as
   earn-in, not a commitment.
10. **Smallest genuinely valuable M5 increment:** the corrected PR #80 +
    PR 9.2's typed core (`unit_role`, warrants on bindings, verified
    citation bindings, claim conditions/falsification) — that alone lets a
    researcher see *which claims are carried where, on what evidence, why,
    and with what verified literature support*, which is the argument
    workbench's actual value proposition.

## Appendix — External reference projects (observations)

- **PaperSpine** (`WUBING2023/PaperSpine`): a 12-stage gated prompt
  pipeline over Markdown artifacts; no database, no outline levels. Worth
  borrowing: the unit doctrine ("smallest writing unit needing a deliberate
  choice" — a workable L5/paragraph-plan definition), the whole-work
  framework rationale as a required root record, Claim Boundary +
  evidence-required/available/missing, allowed/not-allowed interpretation
  fences, the citation stable-identifier rule, and the fourth-wall
  (scaffolding-leak) lint. Reject: Markdown-as-database and the rigid
  linear pipeline.
- **ARA** (`ARA-Labs/Agent-Native-Research-Artifact`): a file-system
  protocol with a machine-checked schema (pinned `ara-cli` in CI). Worth
  borrowing: typed related-work links
  (`imports|bounds|baseline|extends|refutes` + delta + claims-affected),
  claim `Conditions`/`Falsification criteria`, value←source«verbatim quote»
  grounding, the `user|ai-suggested|ai-executed|user-revised` provenance
  enum with no auto-upgrade, before/after revision ledgers, and the
  ~200-token manifest + progressive disclosure (a template for both the ARA
  projection and AI writing packets). Its projection constraints: RKA
  manuscript claims need conditions/falsification fields, claim text
  separated from evidence values, and a `support_level` on reconstructed
  trace records. Reject as store (single-authority files), adopt as
  projection target.
- **ARIS** (`wanshuiyin/auto-claude-code-research-in-sleep`):
  governance-rich autonomous-research harness. Worth borrowing:
  single-owner-per-field write rules, deterministic evidence pre-checks
  before any LLM verdict, "a loop can drive, it cannot acquit",
  Claims-Evidence Matrix views, `DATA_NEEDED` markers instead of
  fabrication, never-from-memory citation discipline, and the
  `sound-modulo-imports` intermediate claim status. Keep its cross-model
  orchestration outside RKA.
- None of the three has prior art for RKA's two-authority prose sync —
  that part of PR 10 is novel ground and should be de-risked accordingly.
