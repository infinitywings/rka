# Persuasive Framing and Limitation Discipline

Use this policy when drafting or revising public manuscript prose. The Writer's
internal analysis must be exhaustive; the manuscript must be selective,
contribution-led, and accurate.

The goal is not maximal confession. The goal is maximal persuasive force
inside the evidence and claim boundary.

## Two-channel rule

Keep two channels separate:

1. **Internal author channel.** RKA, the claim spine, and
   `.planning/REVIEW.md` retain counterevidence, fragile assumptions, missing
   experiments, likely reviewer attacks, and unresolved risks. Analyze these
   directly so the authors can repair or defend them.
2. **Public manuscript channel.** Include what a reader needs to understand,
   evaluate, and reproduce the paper's claims, plus disclosures required by
   the venue. Do not copy an internal risk inventory into the paper.

Omission from public prose never deletes, downgrades, or resolves an RKA
record. Internal visibility and public relevance are different decisions.

## Publication boundary

Classify each concern before deciding how it appears in the manuscript.

| Code | Class | Test | Public treatment |
|---|---|---|---|
| M1 | Claim-changing | Omission could change whether a central claim is correct or supported | Disclose prominently beside the affected claim or result. Repair or narrow the claim first when possible. |
| M2 | Scope-changing | Omission could make a reasonable reader overestimate generality, threat-model coverage, comparison fairness, uncertainty, safety, or practical applicability | State the boundary concisely where the affected claim is interpreted. Pair it with rationale, mitigation, and the supported residual claim. |
| M3 | Reproducibility or context | The detail is needed to reproduce or audit the work but does not change the headline interpretation | Put it in Methods, an artifact description, or an appropriate appendix, subject to venue rules. |
| M4 | Internal or non-material | The concern is an abandoned idea, workflow artifact, duplicate, immaterial imperfection, or issue that does not affect a paper claim | Retain it in RKA and the internal risk register; omit it from public prose. |
| S | Speculative | The concern is plausible but unsupported, remote, or unrelated to the actual claims | Retain it in the internal risk register; omit it from public prose unless the venue requires it or it becomes material. |

Materiality test: **Would omission cause a reasonable reader to overestimate
the validity, scope, novelty, comparison, safety, reproducibility, or certainty
of a ratified contribution?** If yes, classify it as M1, M2, or M3 and disclose
it in the appropriate public location.

An M2 boundary may be satisfied by a clear positive statement of the supported
scope. Do not enumerate every untested model, platform, deployment path, or
attack variant. Name an excluded condition only when a reasonable reader could
otherwise infer that it is covered, the condition is needed to interpret a
result, or the venue requires it. A condition already outside an explicit,
salient claim boundary is M4 or S unless new evidence makes it material.

Any mixed or negative result that bears directly on a contribution claim,
headline comparison, or advertised operating condition is M1 or M2. Report it
with the same denominator and context as positive results. For a mitigated
concern, lead with the defense and supporting evidence, then classify any
residual risk using the table.

When classification is uncertain, keep the concern internal and ask the PI.
Never classify a known material problem as M4 or S merely to avoid disclosure.
If the PI asks to omit an M1/M2 issue or a venue-required disclosure, refuse
that omission. Offer three bounded paths: gather evidence that resolves it,
narrow or withdraw the affected claim, or disclose it proportionately with the
strongest supported defense. Record an unresolved clarification checkpoint and
do not advance the affected unit while none of those paths is selected.

## Strength-first paragraph pattern

For a limitation, threat, or reviewer-sensitive point, prefer this order:

```text
contribution or result
-> supporting evidence
-> precise scope boundary
-> design defense or mitigation
-> material residual implication, if any
```

Do not open a paragraph with an apology when the contribution or defense is the
reader's main takeaway. Preserve semantic qualifiers, but remove stacked
hedges, throat-clearing, and repeated caveats that do not change meaning.

### Examples

Self-sabotaging:

> A major limitation is that we evaluated only three models, so the results may
> not generalize.

Strength-first:

> We evaluate three representative model families under the stated threat
> model. The results support the claims within this scope; broader cross-family
> evaluation is a next step.

Self-sabotaging:

> Unfortunately, our system fails in the adaptive setting.

Material and defended:

> In 120 adaptive-attack trials, attack success is 31%. This measured boundary
> excludes general adaptive robustness from the present claim; the supported
> result remains Z under the stated threat model.

Neutral scope:

> ShieldFlow is designed and evaluated for server-side deployment.

Do not append a catalog of untested deployment variants. Do not use the
neutral-scope pattern when an omitted condition is inside an advertised claim
or materially changes the interpretation.

## Quick-reader checks

A rushed reviewer should recover the same central argument from each of these:

- title and subtitle;
- abstract;
- first two introduction paragraphs;
- contribution list;
- first overview figure and caption;
- results-roadmap paragraph and primary result table or figure;
- conclusion.

Run four named scans:

1. **Title and abstract scan.** Recover one central problem, the contribution,
   the strongest result, and why it matters.
2. **Introduction and contribution scan.** Recover the field gap, technical
   insight, approach, and distinct evidence-backed payoff of each contribution.
3. **Evidence scan.** Find the principal result quickly in a result heading,
   table or figure, and caption that states the comparison, denominator, and
   significance.
4. **Boundary scan.** Understand the tested scope and every M1 or M2 material
   limitation without wading through the internal risk register.

Across all four scans, define specialist terms on first use, minimize acronym
switching, give each paragraph one communicative job, and lead with its
takeaway. If a scan fails, revise or escalate to the PI. Never make a scan pass
by deleting a material limitation or unsupported result.

Run these scans on the public prose with provenance comments hidden. A reader
should encounter a research argument, not the shape or vocabulary of the RKA
record. Use `discourse_synthesis.md` to repair a section whose claims are
grounded but whose logic still reads as a list.

Accessibility does not mean removing technical precision. Use a plain-language
sentence first, then add the formal or implementation detail.

## Reviewer defense

Preempt a criticism in public prose when it is both plausible and consequential
and the paper has a real defense. Prefer evidence-backed defenses:

- explicit threat-model and assumption boundaries;
- baseline-selection rationale and apples-to-apples comparison;
- matched ablations or control conditions;
- sensitivity or robustness analysis;
- denominator and trial accounting;
- implementation checks and reproducibility artifacts;
- explanation of why an alternative design was rejected.

Do not invent a defense, attack prior work unfairly, or use confidence as a
substitute for evidence. If the defense is incomplete and the concern is
material, narrow the claim and state the residual boundary.

## Internal risk register

Record reviewer-facing concerns in `.planning/REVIEW.md` with:

| Location or claim | Likely criticism | Evidence | Materiality code | Existing defense | Repair | Public treatment | Public manuscript location |
|---|---|---|---|---|---|---|---|

`Public treatment` must be one of:

- `lead-with-defense`;
- `neutral-scope`;
- `material-limitation`;
- `venue-required-disclosure`;
- `internal-only`;
- `repair-before-submission`.

The risk register is an author tool, not manuscript text. Convert selected
items into polished prose using the strength-first pattern. Before an affected
unit advances to `drafted`, every M1/M2 row must name the paragraph, figure,
table, caption, or claim where its public treatment appears. If no location is
appropriate yet, keep `repair-before-submission` and escalate.

## Language discipline

Avoid gratuitous concession markers such as:

- "a major weakness of our work";
- "unfortunately";
- "we only";
- "merely";
- "an obvious limitation";
- "our method fails" when a precise operating condition is available;
- repeated "may," "might," "possibly," and "potentially" around one claim.

Do not remove qualifiers that carry scientific meaning. Replace emotional or
global language with the exact condition, observed effect, and claim boundary.

## Integrity boundary

Never use persuasive framing to:

- fabricate support, certainty, novelty, or generality;
- cherry-pick trials, baselines, metrics, denominators, or time windows;
- suppress a mixed or negative result that bears on a contribution claim;
- hide an unresolved contradiction or a known violation of a stated
  assumption;
- omit a material safety, security, validity, or reproducibility issue;
- move a claim-relevant adverse result to an appendix solely to evade review;
- present an untested condition as supported;
- bypass a venue-required limitations, ethics, or reproducibility disclosure.

If persuasive presentation and scientific validity conflict, preserve
validity, repair or narrow the claim, and then make the bounded contribution as
clear and compelling as possible.
