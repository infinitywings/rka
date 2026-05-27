# CHI (ACM Conference on Human Factors in Computing Systems)

Phase 1 seed venue per `dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D` Q3 (HCI domain).

## 1. Section names and order

Typical CHI Papers structure (six to nine sections):

1. Introduction
2. Related Work (or "Background and Related Work")
3. Method (or "System Design and Method")
4. Findings / Results / Evaluation (one or more sections; mixed-methods papers may split per study)
5. Discussion
6. Limitations (recommended as a top-level section since 2024)
7. Conclusion (optional; some authors fold into Discussion)
8. Acknowledgments (post-conclusion, pre-references)
9. References

Subsections are typical at depth 2; depth 3 is acceptable but should be sparing.

## 2. Page-limit class

14 pages main matter (CHI Papers 2024 onward; subject to per-year confirmation against the CFP). Appendix is **uncounted**. References are **uncounted** (since 2020).

Verify the current year's CFP before relying on this; CHI page limits have historically been stable but have been revised.

## 3. Tone characteristics

- First-person plural ("we", "our") is standard and expected.
- Reflexivity is expected for qualitative or design work (positionality statement common in §3 or §6).
- Hedged claims preferred over absolute claims for design work. Empirical sections may use stronger claims with appropriate statistical support.
- Mixed-methods is common; integration framing (not just side-by-side) is expected.
- Math density is low to moderate; CHI is not a math-heavy venue. Equations are presented selectively.
- Quotes from participants are common in qualitative work; format per ACM acmart conventions (italic with attribution after the period).

## 4. Forbidden constructions

- `we propose a novel ...` (overused since 2022; reviewers flag).
- `comprehensive` as a hedge against scope criticism.
- Bold-faced claims of contribution in the Introduction without supporting detail.
- Unsupported claims of generalizability for small-sample qualitative work.
- Em-dash characters U+2014 and U+2013 (Writer dogfood rule, applies project-wide).

These are venue-specific anti-patterns layered on top of the universal Anti-AI-tic enforcement in `references/ai_tics.md`.

## 5. Citation style

Numeric (`[42]`), sorted by appearance. Set via `\documentclass[sigconf]{acmart}` (default). Multi-citation: `\cite{key1, key2, key3}` produces `[42, 43, 44]` (no en-dash range).

References list ordered numerically by first citation, not alphabetically. The acmart class handles this automatically; do not override the bibliography style.

## 6. Required sections

- **Introduction**: motivation, problem framing, contribution claims.
- **Related Work**: positions against prior literature; rule of thumb is 50 to 80 citations for a full-length CHI paper.
- **Method**: detailed enough that another researcher could replicate the study.
- **Findings or Results**: data-driven section(s).
- **Discussion**: implications and connections to broader literature.
- **Limitations**: recommended as top-level since 2024 (reviewers expect it). Acceptable to subsection within Discussion if space-constrained.
- **References**: numeric, complete bibliography.

Acknowledgments are conventional but not required. Reproducibility statement is encouraged (subset of authors fold it into the Method section).

Ethics: CHI does not require a formal Ethics section, but human-subjects studies require IRB or equivalent statement and protocol description in the Method section.

## 7. Sample corpus pointers

For tone calibration, the Writer scaffolding should reference three to five recent published CHI papers from the prior two years. Recommended sample queries via OpenAlex:

- `https://api.openalex.org/works?filter=primary_location.source.id:S4310306537,publication_year:2025&per-page=25` (CHI 2025 by source ID; verify the source ID at scaffold time).
- Hand-pick three to five papers spanning empirical and design domains for tone-diversity.

Sample papers should be stored as `lit_` entries with `tags=["venue-sample:CHI", "venue-sample"]` so the Writer can retrieve them via `rka_search(query="venue-sample CHI", entity_types=["literature"])`.

## Notes on acmart wrapper

If a project needs project-specific commands or environments without modifying the acmart class file (LPPL Component-1 requires renaming on modification), create a wrapper class in the manuscript directory:

```latex
% myproject-acmart.cls
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{myproject-acmart}[2026/05/19 v1.0 Project wrapper around acmart]
\LoadClass[sigconf, anonymous, review]{acmart}

% Project-specific commands here
\newcommand{\projecttool}[1]{\textsc{#1}}
% ...
```

Then `\documentclass{myproject-acmart}` in `main.tex`.

This pattern preserves LPPL compliance while allowing per-project additions.

## References

- ACM CHI Call for Papers (verify per year): https://chi.acm.org/
- acmart documentation: https://github.com/borisveytsman/acmart
- ACM Publications Workflow: https://www.acm.org/publications
