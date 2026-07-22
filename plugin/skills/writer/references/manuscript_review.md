# Pre-Submission Manuscript Review (advisory)

This is a **PI-facing gap surfacer, not an autograder.** It never gates compile
or submit. The only blocking gates remain the mechanical ones:
`verify_provenance.py`, `verify_citations.py`, `layout_audit.py`, and the
reference-validation statuses. This review adds the reviewer-facing
presentation and claim-calibration checks that those gates do not cover, and it
reports concrete gaps for the PI to weigh, never a numeric score or an
accept/reject verdict.

It complements [`quality_review.md`](quality_review.md): that reports the RKA
evidence behind each rubric dimension; this adds the reviewer-perception lens
(claim calibration, evaluation credibility, reviewer risk). Neither scores. See
`quality_review.md` for why gating on an LLM-reviewer score is unsound (LLM
reviewers correlate only r=0.48 with humans and carry length / positivity /
self-preference biases).

Run this before the Final Layout checkpoint, or on demand. Point to exact
sections, pages, paragraphs, figures, and tables throughout. Where a claim
needs support, name the RKA entity (`lit_`, `jrn_`, `dec_`, `clm_`) or the kind
of source needed; do not invent one.

## 0. Source, venue, and evidence discipline

Before commenting, state your assumptions:

- Target venue or venue family (read `references/venue/<venue>.md` if the venue
  is known), and paper type (systems, security, AI, HCI, NLP, empirical, theory).
- The strongest evidence in the manuscript.
- The weakest or most fragile evidence in the manuscript.

Strict evidence rule: a claim is not safe because it sounds plausible. Check
whether the manuscript itself supports it through an experiment, a citation, a
formal argument, or explicit limitation text. If it is unsupported, ask for
evidence or suggest softer wording.

## 1. Overall assessment and top reviewer-facing risks

- Is the central story clear?
- Do the title, abstract, introduction, contribution list, and results align?
- Does the manuscript read like a polished submission or an expanded technical
  report?
- Are claims calibrated to the evidence?
- Is the strongest evidence placed where a reviewer will see it?
- What are the top 3 to 5 reviewer-facing risks?

Be direct. If something is strong, say why. If something invites reviewer
skepticism, name it.

## 2. Claim-calibration table

| Claim (original or likely) | Problem | Safer revised wording |
|---|---|---|

Target absolute or promotional wording. The calibration word list:
`verified`, `guaranteed`, `complete`, `completely`, `eliminates`,
`model-agnostic`, `dominant`, `fundamental`, `robust to adaptive adversaries`,
`generalizes across benchmarks`, `full recall`, `no false positives`,
`provably`, `never fails`.

**Hook:** cross-reference RKA confidence. An absolute claim whose backing
`jrn_`/`clm_` is at `hypothesis` or `tested` confidence (not `verified`) is a
high-priority calibration gap. `scripts/overclaim_lint.py` surfaces these
mechanically: it is WARN-only and marks `priority="high"` when a governing
`% provenance:` comment resolves to weak-confidence evidence. Fold its
`overclaim_report.json` into this table rather than re-scanning by eye.

The goal is not to weaken the paper. It is to make the claims precise,
defensible, and reviewer-proof.

## 3. Abstract review

- Does the first sentence establish the problem clearly?
- Is the motivation specific rather than generic?
- Are the contributions accurate without overclaiming?
- Are all numbers, ratios, and percentage-point changes correct?
- Is the strongest evidence the centerpiece, and are weaker or preliminary
  results framed honestly (no cherry-picking, no hidden mixed result)?

Provide remaining abstract problems and a revised abstract draft that is
shorter, clearer, and more credible, with a one-line note on why it is better.

## 4. Introduction review

Check the opening motivation, motivating example, gap statement (fair to prior
work, not an unfair attack), key insight, why prior work is insufficient, the
transition from problem to approach, the results paragraph, and the
contribution list. Flag sentences that are too broad, too absolute, or
promotional; repetition; missing transitions; and a contribution list that has
become a second abstract. Provide a revised introduction outline, suggested
wording for the key-insight paragraph, and a shorter, more defensible
contribution list.

## 5. Structure and organization

- Are sections in a logical order?
- Are background, threat model, design, implementation, evaluation, discussion,
  related work, and limitations cleanly separated (design not tangled with
  evaluation configuration)?
- Do limitations appear early enough?
- Is the evaluation easy to follow, and does the paper need a clearer roadmap?

Provide a proposed section outline and specific movement suggestions (for
example, "move this table to the appendix" or "move this limitation earlier").

## 6. Evaluation-presentation credibility

- Is the evaluation story easy to understand, and is the main result clearly
  identified?
- Are controlled-benchmark, external-benchmark, model-specific, ablation, and
  preliminary results separated?
- Are trial counts and denominators easy to verify, and do captions explain the
  denominators?
- Are outcome categories separated from defense mechanisms?
- Are statistical claims presented without overstating independence, and are
  repeated trials treated appropriately?
- Are the limitations of each benchmark stated, and are positive results that
  should read as preliminary framed that way?

Look for arithmetic errors, confusing denominators, and ambiguous terms (trial,
scenario, attack evaluation, task success, safe tool call, blocked, bypass).
**Hook:** every reported number should trace to a `mis_` report or a
`jrn_`/`clm_` result, the same provenance the Iron Law already requires for body
prose. Provide a clearer evaluation narrative, caption improvements, and a
numerical-consistency checklist to run before submission.

## 7. Figures, tables, and layout

For each important figure or table: is the caption clear and does it explain the
denominator; is it readable in two-column format; does it support the main
argument; is it duplicative; does it overstate the result; is a mixed or
negative result hidden in a dense table? This complements (does not duplicate)
`layout_audit.py`, which handles the mechanical layout gates (page limit,
undefined refs and cites, overfull boxes). Provide better titles and captions,
visual-simplification suggestions, and move-to-appendix candidates.

## 8. Terminology normalization

| Current variants | Recommended term | Notes |
|---|---|---|

Check the system name, title phrase, threat-model terms, attack-category names,
evaluation metrics, model names, dataset and benchmark names, policy names,
provenance and measurement labels, and section / figure / table references.

## 9. Writing style

Defer to the existing anti-AI-tic machinery: `ai_tic_lint.py` (lexical tiers
plus structural detectors) and `bridge_repetition_check.py` (near-duplicate
sentences across sections). This section adds only the reviewer-perception
framing (does the prose read as hyped, repetitive, or generated) and does not
introduce a second lexical list.

## 10. Reference and citation integrity

Review citations from a credibility lens: claims about prior work that need
citations; citations that are too broad or poorly placed; sentences that cite a
source but make a stronger claim than the source supports; related-work
comparisons that may not be apples-to-apples; whether the paper distinguishes
its own results from prior reported numbers. Defer the mechanical checks to
`verify_provenance.py`, `verify_citations.py`, and the reference-validation
pipeline. Do not invent citations; where support is missing, name the kind of
source needed.

## 11. Venue fit

Read `references/venue/<venue>.md`: expected tone, section order, required
sections (for example Limitations at EMNLP, Ethics at ACL 2024+, Reproducibility
checklist at NeurIPS), forbidden constructions, and whether math, system detail,
user-study detail, or benchmark detail is too much or too little for the venue.
If the venue is unknown, list the venue-dependent checks the PI should make.

## 12. Reviewer-risk analysis

| Criticism | Why a reviewer raises it | Severity | How to preempt | Suggested wording |
|---|---|---|---|---|

Include risks such as: the paper overclaims; baselines look weak or unfair; the
strongest result is not emphasized; the abstract hides a mixed result;
evaluation numbers are hard to reconcile; the threat model is inconsistent with
the attack taxonomy; the writing is repetitive; figures or tables are too dense;
limitations appear too late.

## 13. Concrete rewrite package

Provide a focused, submission-ready package: revised title options, a revised
abstract, a revised key-insight paragraph, a revised contribution list, a
revised limitation paragraph, a revised evaluation-roadmap paragraph, and a
revised related-work positioning paragraph.

## 14. Systems, security, and AI-agent add-on (venue-conditional)

Use this lens for tool-using LLM-agent security papers (and similar
systems/security work):

- Is the threat model consistent with the attack taxonomy?
- Are direct and indirect attacks clearly separated?
- Does the paper distinguish design guarantees from implementation heuristics?
- Are formal properties stated as conditional on clearly-stated assumptions?
- Are policy-only, filtering-only, taint-only, and full-system baselines framed
  fairly?
- Are evaluation outcomes separated from defense mechanisms, external-benchmark
  results adapted transparently, and controlled-benchmark results not oversold?
- Are mixed results acknowledged in the main text?
- Do final claims distinguish architecture-level generality from empirical
  results on the tested models?
- Are confidentiality, integrity, availability, and usability claims each
  supported by the right evidence?

## Output

Write `.planning/REVIEW.md`: one table per dimension above, each with an explicit
**Gaps** list drawn from the mechanical inputs (`verify_provenance.py`,
`verify_citations.py`, `ai_tic_report.json`, `overclaim_report.json`,
`layout_audit.py`) and RKA evidence (confidence levels, `contradicts` edges).
No numeric score. No accept/reject verdict.

## Fast pass

A quick top-10-issues mode runs sections 1, 2, 6, 7, 8, and 12 only: overall
risks, claim calibration, evaluation credibility, figures and tables,
terminology, and reviewer risk. Same advisory posture and same `.planning/REVIEW.md`
output, abbreviated.

## Anti-patterns

- DON'T compute or report an accept/reject or numeric quality score.
- DON'T treat this review as a gate; only the mechanical gates block.
- DON'T assert a review claim without pointing at the manuscript location or the
  RKA entity that supports it.
