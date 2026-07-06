# Design — Writer skill "Review & Revision" capability

Date: 2026-07-06
Status: approved design (pending user spec review)
Scope: `rka/skills/writer/` (mirrored to `plugin/skills/writer/`)
Skill version: `2.4.0 → 2.5.0`

## 1. Problem & motivation

The RKA writer skill is drafting-forward. It enforces the Iron Law
(draft-but-don't-assert, every claim provenance-anchored), Knowledge Currency
(superseded / retracted / contradicted handling), six PI checkpoints, a
reference-validation pipeline, anti-AI-tic enforcement, LaTeX render + layout
audit, and a reactive Revision Loop that classifies PI comments into four
shapes (R1–R4).

What it lacks: a **proactive, reviewer-lens pre-submission review** (claim
calibration, reviewer-risk preemption, evaluation-presentation credibility,
terminology normalization, abstract/intro-specific checks) and an
**old-vs-new revision-checking** pass (compare a revised draft against prior
review comments and report what got Fixed / Partial / Not fixed / Regressed).

Two inputs shape this design:

- **The PI's manuscript-revision prompt template** (`Prompt 1` = pre-submission
  reviewer review; `Prompt 2` = old-vs-new revision checking; plus a fast-pass
  mini-prompt and a systems/security/AI-agent add-on). This is the capability
  content.
- **edwinhu/workflows** — a phase-based Claude Code workflow system
  (`/writing` + `/writing-revise`, internal `writing-review`/`writing-validate`
  phases, reviewer sub-passes, `.planning/` state). We borrow three *portable*
  patterns, not its paradigm.

### The load-bearing constraint (non-negotiable)

The writer skill deliberately **does not gate on LLM-reviewer judgment**.
`references/quality_review.md` documents why: LLM reviewers correlate only
~r=0.48 with humans, disagree sharply with each other, and carry
length / positivity / self-preference biases and injection weakness. So this
capability is **advisory only**: it surfaces concrete, evidence-anchored gaps
to the PI and never blocks compile or submit on its own judgment. The only
gates that block remain the existing mechanical ones (`verify_provenance.py`,
`verify_citations.py`, `layout_audit.py`, the reference-validation statuses).

## 2. What we build

### 2.1 New reference — `references/manuscript_review.md` (Prompt 1)

A PI-facing pre-submission review **checklist** (not an autograder). Runs as
an advisory pass before Checkpoint 6 (Final Layout), or on demand. Sections:

1. **Source, venue & evidence discipline.** State assumptions: target venue
   family (from `venue/<venue>.md` if known), paper type, strongest evidence,
   most fragile evidence. Strict evidence rule: a claim is not safe because it
   sounds plausible — check whether the manuscript itself supports it
   (experiment / citation / limitation text). Point to exact sections /
   figures / tables.
2. **Overall assessment + top 3–5 reviewer-facing risks.**
3. **Claim-calibration table** — `original/likely claim | problem | safer
   revised wording`. Targets absolute wording (`verified`, `guaranteed`,
   `complete`, `eliminates`, `model-agnostic`, `dominant`, `fundamental`,
   `robust to adaptive adversaries`, `generalizes across benchmarks`, `full
   recall`, `no false positives`). **Hook:** cross-reference RKA confidence —
   an absolute claim whose backing `jrn_`/`clm_` is at `hypothesis`/`tested`
   confidence (not `verified`) is a high-priority calibration gap, and this is
   exactly what `scripts/overclaim_lint.py` (§2.3) surfaces mechanically.
4. **Abstract review** — first-sentence problem framing, motivation
   specificity, arithmetic/ratio correctness, strongest-evidence centrality,
   honest framing of mixed/preliminary results, no cherry-picking.
5. **Introduction review** — motivation, gap statement (fair to prior work),
   key-insight clarity, results paragraph matches evaluation, contribution
   list not a second abstract.
6. **Structure & organization** — logical section order; background / threat
   model / design / implementation / evaluation / discussion / related work /
   limitations cleanly separated; limitations early enough; roadmap clarity.
7. **Evaluation-presentation credibility** — denominators explained,
   arithmetic checked, controlled-benchmark vs external-benchmark vs
   model-specific vs ablation vs preliminary results separated, trial counts
   verifiable, outcome categories separated from defense mechanisms,
   statistical claims not overstating independence, per-benchmark limitations
   stated. **Hook:** every reported number should trace to a `mis_` report or
   `jrn_`/`clm_` result (same provenance the Iron Law already requires).
8. **Figures, tables & layout** — caption/denominator clarity, two-column
   readability, no hidden mixed results, move-to-appendix candidates.
   Complements (does not duplicate) `layout_audit.py`, which handles the
   mechanical layout gates.
9. **Terminology-normalization table** — `current variants | recommended term
   | notes` across system name, threat-model terms, metric names, model names,
   benchmark names, section/figure/table references.
10. **Writing style** — defers to the existing anti-AI-tic machinery
    (`ai_tic_lint.py`, `bridge_repetition_check.py`); this section only adds
    the reviewer-perception framing, not a second lexical list.
11. **Reference & citation integrity** — from a credibility lens; defers
    mechanical checks to `verify_provenance.py` / `verify_citations.py` and the
    reference-validation pipeline. Never invent citations — name the kind of
    source needed.
12. **Venue fit** — reads `venue/<venue>.md` (tone, required sections,
    forbidden constructions).
13. **Reviewer-risk analysis** — `criticism | why a reviewer raises it |
    severity | how to preempt | suggested wording`.
14. **Concrete rewrite package** — revised title options, abstract, key-insight
    paragraph, contribution list, limitation paragraph, evaluation-roadmap
    paragraph, related-work positioning.
15. **Systems/security/AI-agent add-on** (venue-conditional lens): threat-model
    ↔ attack-taxonomy consistency, direct vs indirect attack separation,
    design-guarantee vs implementation-heuristic distinction, conditional
    formal properties, baseline fairness (policy-only / filtering-only /
    taint-only / full-system), CIA + usability claims each backed by the right
    evidence.

**Output artifact:** `.planning/REVIEW.md` — one table per dimension with an
explicit **Gaps** list drawn from the mechanical inputs and RKA evidence. No
numeric score, no accept/reject verdict, no gate.

**Fast pass:** a short "top-10-issues" mode (the PI's mini-prompt) documented as
a lightweight entry that runs sections 2, 3, 7, 8, 9, 13 only.

### 2.2 New reference — `references/revision_check.md` (Prompt 2)

Old-vs-new revision checking. Steps:

1. **Comparison setup** — identify old vs new draft, the prior review comments
   being used as baseline (from the spawning mission's `context`, the prior
   `.planning/REVIEW.md`, or PI-supplied comments), and whether the comparison
   is full / new-only-guided-by-prior / limited.
2. **Executive revision diagnosis** — better / somewhat better / unchanged /
   worse; most successful revisions; remaining problems; regressions; a
   readiness judgment (minor-edit / focused-revision / major-restructure /
   not-ready) framed as advisory input, not a gate.
3. **Revision-status tracker** — `prior issue | status | evidence in new draft
   | remaining problem | recommended next edit`, status ∈ {Fixed, Mostly
   fixed, Partially fixed, Not fixed, Regressed, New issue, Cannot verify}.
   Covers the same dimensions as §2.1.
4. **Per-dimension re-checks** (abstract, title/contribution alignment, claim
   calibration, intro story, evaluation, figures/tables, terminology, style,
   citations) — each compared against the prior issue.
5. **Revision-comment classification** — map each remaining issue to the
   existing **R1–R4** classes so the current Revision Loop handlers apply
   (`handle_factual_r1`, `handle_style_r2`, `handle_inconsistency_r3`,
   `handle_logical_r4`).
6. **Remaining reviewer risks + action plan** — must-fix vs optional.

**Reuses:** `REVIEW_STATE.md`'s `iteration / max:3 / verdict` cap;
`bridge_repetition_check.py` and `ai_tic_lint.py` for old-vs-new diffs.

**Output artifact:** `.planning/REVISION_CHECK.md` — the tracker table.

### 2.3 New script — `scripts/overclaim_lint.py`

A lexical overclaim/calibration detector, in the shape of `ai_tic_lint.py`:

- Scans `sections/*.tex` for calibration words (the §2.1(3) list; extensible
  per-project like the AI-tic config).
- **WARN-only, never BLOCK** (advisory-only decision). Emits
  `overclaim_report.json` (term, file, line, sentence, severity=WARN).
- **RKA-confidence ranking:** when an overclaim word sits in a sentence with a
  nearby `% provenance:` comment, resolve the cited `jrn_`/`clm_` confidence;
  `hypothesis`/`tested` backing raises the flag's priority (an absolute claim
  on non-`verified` evidence). Falls back to plain lexical WARN when no
  provenance comment is adjacent (no RKA call needed).
- Mirrors `ai_tic_lint.py`'s CLI + report shape so the Writer treats it as one
  more mechanical input to `.planning/REVIEW.md`.

### 2.4 SKILL.md changes

- New **"Pre-Submission Review"** section: advisory input to Checkpoint 6 (not
  a new gating checkpoint); points to `manuscript_review.md`; lists
  `overclaim_lint.py` among the mechanical inputs; states the advisory-only
  rule.
- Extend **"Revision Loop"** with a "Revision-check (old-vs-new)" subsection
  pointing to `revision_check.md` and wiring its output to R1–R4.
- **edwinhu patterns folded in:** (a) fresh-review vs. midpoint re-entry
  (mirror `/writing` vs `/writing-revise`) documented as two entry modes; (b)
  the `.planning/REVIEW.md` + `.planning/REVISION_CHECK.md` state artifacts
  added to the `.planning/` convention; (c) a **mission-spawned `writer-review`**
  path parallel to today's `writer-revision`, threaded through Session Start
  path (b): Brain spawns `rka_create_mission(..., tags=["writer-review",
  "manuscript:<jrn_id>"], motivated_by_decision="dec_...")`; the subagent runs
  the review and reports via `rka_submit_report`.
- Housekeeping: update the Supplementary-references list, the Scripts list, the
  Related section, and add two Anti-Patterns: "DON'T gate on the reviewer pass
  — advisory only"; "DON'T compute an accept/reject or numeric quality score
  (see quality_review.md)." Bump frontmatter `version: 2.4.0 → 2.5.0`.
- Cross-link `quality_review.md` (the RKA-evidence rubric) and
  `manuscript_review.md` (the reviewer-perception lens) as complementary — the
  former reports RKA evidence per dimension, the latter adds the reviewer-facing
  presentation/claim-calibration checks. Neither scores.

## 3. Non-goals (YAGNI / principle preservation)

- No LLM-reviewer score, accept/reject verdict, or gate on reviewer judgment.
- No new PI checkpoint (review is advisory input to Checkpoint 6).
- No phase restructure of the skill (that was rejected approach D; edwinhu is a
  standalone-workflow paradigm, not RKA's skill-in-a-knowledge-graph paradigm).
- No new RKA orchestration beyond the `writer-review` mission tag — bookkeeper
  invariant holds: new files only under `rka/skills/writer/` and
  `tests/skills/writer/`.
- No third-party content vendored; the calibration word list is authored from
  the PI's prompt, consistent with the Phase-1 posture in
  `dec_01KS12H9KT1T03DHX2Q6FKTXHH`.

## 4. Integration & data flow

```
Pre-submission review (advisory)                 Revision-check (advisory)
  trigger: before Checkpoint 6, or on demand,      trigger: new draft vs prior
           or Brain-spawned writer-review mission           comments/old draft
  reads:  sections/*.tex, venue/<venue>.md,        reads: old + new drafts,
          verify_provenance/citations/layout              prior REVIEW.md or
          reports, ai_tic_report.json,                    mission context
          overclaim_report.json, RKA confidence
  writes: .planning/REVIEW.md (gaps, no score)     writes: .planning/REVISION_CHECK.md
  next:   PI reads gaps → Checkpoint 6 decision    next:  remaining issues → R1–R4
                                                           handlers → REVIEW_STATE cap
```

## 5. Testing

- `tests/skills/writer/test_overclaim_lint.py`: fixture `.tex` with known
  overclaim words → expected WARN report; a sentence with a `% provenance:`
  comment pointing at a `tested`-confidence entity ranks higher than a bare
  lexical hit (RKA confidence mocked, no live call).
- Doc-consistency is already covered: `tests/test_skills_packaging.py` enforces
  `plugin/skills/` == `rka/skills/` parity and package-data coverage, so the two
  new references + script ship on a fresh install.

## 6. Consistency & rollout

`rka/skills/writer/` is the source of truth. After edits: mirror to
`plugin/skills/writer/` via the documented rsync, run the packaging tests,
reinstall the wheel + refresh the plugin cache (per
`project_skill_tool_consistency`). Ship behind the same commit discipline as
the rest of the repo (no push without explicit PI request).

## 7. Open questions

None blocking. The skill-version bump (2.4.0 → 2.5.0) is a content-version bump
local to the skill frontmatter, distinct from the RKA release version; called
out here for visibility.
