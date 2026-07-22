# Revision Check (old vs new, advisory)

Compare a revised draft against the prior review comments and report what the
revision fixed, left unfixed, or regressed. This is advisory input to the
Revision Loop, not a gate: the readiness diagnosis informs the PI, it does not
block compile or submit. Only the mechanical gates
(`verify_provenance.py`, `verify_citations.py`, `layout_audit.py`, the
reference-validation statuses) block.

## 0. Comparison setup

Identify:

- Which draft is the older version and which is the newer version.
- The prior-comments baseline: the spawning `writer-review` or `writer-revision`
  mission `context`, the prior `.planning/REVIEW.md`, or PI-supplied comments.
- Whether any input is missing for a fair comparison.

Then state the run type: full old-vs-new comparison; new-version-only guided by
prior comments; or limited comparison because the old version or prior comments
are incomplete.

## 1. Executive revision diagnosis

- Is the newer manuscript clearly better, somewhat better, unchanged, or worse?
- What are the most successful revisions?
- What earlier problems remain, and did the revision introduce new ones?

Give an advisory readiness judgment (ready after minor editing; needs another
focused revision; needs major restructuring; not ready). Framed as advice for
the PI, not a gate.

## 2. Revision-status tracker

| Prior issue | Status | Evidence in new draft | Remaining problem | Recommended next edit |
|---|---|---|---|---|

Status vocabulary, exactly: `Fixed`, `Mostly fixed`, `Partially fixed`,
`Not fixed`, `Regressed`, `New issue`, `Cannot verify`.

Track the same dimensions as `manuscript_review.md`: title accuracy, abstract
clarity and arithmetic, claim calibration, introduction story, contribution
list, evaluation framing (controlled vs external benchmark emphasis, mixed or
negative result disclosure), table and figure readability, terminology
consistency, limitation placement, related-work positioning, reference and
citation integrity, and anti-AI-tic style.

## 3. Per-dimension re-checks

For each dimension, compare the newer draft against the prior issue:

- **Abstract**: arithmetic and ratios corrected; strongest evidence is the
  centerpiece; no cherry-picking; mixed results disclosed; aligned with the
  evaluation tables.
- **Title, framing, contribution alignment**: title not overclaiming;
  contribution list shorter and each item backed by evidence; design,
  implementation, benchmark, and evaluation contributions separated.
- **Claim calibration**: re-run `scripts/overclaim_lint.py` on the new draft and
  diff its `overclaim_report.json` against the prior run; a resolved hit is
  progress, a new or higher-priority hit is a regression.
- **Introduction, evaluation, figures and tables, terminology**: as in
  `manuscript_review.md`, but scored against the prior issue rather than fresh.
- **Style**: diff `ai_tic_lint.py` output old vs new; `bridge_repetition_check.py`
  for cross-section near-duplicates.

## 4. Revision-comment classification

Map each remaining issue to the four Revision Loop classes so the existing
handlers in `scripts/revision_handler.py` apply:

- R1 factual (sentence-level) -> `handle_factual_r1`.
- R2 style or AI-tic -> `handle_style_r2`.
- R3 cross-section inconsistency -> `handle_inconsistency_r3`
  (`bridge_repetition_check.py`, ratio >= 0.7).
- R4 logical gap or unsupported claim -> `handle_logical_r4` (escalates a
  `writer_evidence_gap` mission to the Brain).

For each remaining issue give: class, severity, location, required action, and
whether the author can fix it by editing text or needs more evidence. The
`REVIEW_STATE.md` iteration cap of 3 applies; the third failed iteration
auto-escalates to a PI checkpoint.

## 5. Remaining reviewer risks and action plan

List the reviewer criticisms that still remain after the revision. For each:
why it may still arise, how severe, how to preempt, and the exact wording to
add, soften, or move. End with a prioritized action list split into must-fix
before submission and optional-but-strengthening.

## Output

Write `.planning/REVISION_CHECK.md`: the revision-status tracker table plus the
remaining-risks action plan. No numeric score.

## Anti-patterns

- DON'T re-litigate an item already marked `Fixed`.
- DON'T gate on the readiness diagnosis; it is advisory.
- DON'T mark a `Cannot verify` item as `Fixed`; surface the missing input to the
  PI instead.
