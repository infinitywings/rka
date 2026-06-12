# Manuscript Quality Self-Review (P7)

A structured checklist the Writer fills in and surfaces to the PI before the
Final Layout checkpoint. It is a **PI-facing checklist, not an autograder.**

## Why this is a checklist and not an LLM-reviewer score

The evidence against gating on an LLM-reviewer score is strong and consistent:

- LLM reviewers correlate only ~r=0.48 with human reviewers and disagree
  sharply with each other (mean abs. score difference 0.91 to 2.73 across
  models).
- They carry systematic, exploitable biases: a monotonic preference for
  longer papers, a positivity bias (rarely assign the lowest score), and a
  self-preference bias (markedly higher scores for LLM-authored prose).
- They are trivially manipulated by injected text and cannot reliably tell
  sound from unsound research (SoundnessBench).

So the Writer must **never** treat a generated review score as a gate or as
ground truth. The value here is a disciplined surfacing of the dimensions
human reviewers actually weigh, each tied to the provenance the manuscript
already carries, so the PI reviews concrete gaps rather than a number.

## The rubric dimensions

These five converge across the 2024-2026 automated-review frameworks
(ReviewEval, DeepReview, ReviewAgents, ASAP). For each, the Writer reports
the **evidence in RKA**, not a judgment.

| Dimension | What the Writer reports (evidence, not score) |
|---|---|
| **Novelty / positioning** | Which `dec_` framing decision and which `lit_` related-work entities position the contribution. Gap: any claim of novelty with no `lit_` contrast anchor. |
| **Soundness / validity** | For each empirical claim, the `jrn_`/`clm_` result entity and whether it is `verified` vs `tested` vs `hypothesis`. Gap: any result asserted at `hypothesis` confidence. |
| **Clarity / organization** | Section order vs the venue file's required sections; ai_tic style score; any structural-detector WARN. |
| **Significance** | The `dec_` / research-question (`ecl_` parent) the work answers, and the magnitude of the reported effects. Gap: results with no upstream RQ. |
| **Completeness / reproducibility** | Venue-required sections present (Limitations, Ethics, Reproducibility checklist); every number traces to a `mis_` report or `jrn_` result. |

## Mechanical inputs (already produced by other scripts)

The self-review aggregates outputs the Writer already has, so it adds no new
LLM judgment:

- `verify_provenance.py` report: every prose claim's citation is EXISTS +
  CURRENT + SUPPORTED + UNCONTESTED (P0/P1/P6). Any BLOCK is a soundness gap.
- `verify_citations.py` report: every `\cite{}` resolves (P4).
- `ai_tic_lint.py` report: style score + structural detectors (clarity).
- `layout_audit.py` report: page limit, undefined refs/cites (completeness).
- RKA confidence levels on every cited `jrn_`/`clm_` (soundness).
- RKA `contradicts` edges among cited claims (does the paper surface known
  disagreements, P6).

## Output

`.planning/QUALITY_REVIEW.md`: a table of the five dimensions, each with
its evidence column and an explicit **Gaps** list drawn from the mechanical
inputs above. The PI reads the gaps and decides; the Writer does not assign or
gate on an overall score.

## Anti-patterns

- DON'T compute or report an overall numeric quality/accept score.
- DON'T run an LLM "reviewer" persona and treat its verdict as a gate.
- DON'T claim novelty, soundness, or significance without the RKA entity that
  supports the claim, exactly as the Iron Law requires for body prose.
