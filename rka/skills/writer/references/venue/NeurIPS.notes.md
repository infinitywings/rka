# NeurIPS (Conference on Neural Information Processing Systems)

Phase 2 venue per `dec_01KS2S22VV5P5SWWXNBXQDHMGX` Option A deliverable 4.
Schema follows Phase 1 CHI.md and EMNLP.md (seven fields).

NeurIPS ships year-specific style files at the conference website each
year (typically `neurips_<year>.sty`). The pin in `template_registry.md`
tracks the latest released year and is rotated at venue-year changes.
ICML and ICLR share similar conventions but use their own style files.

## 1. Section names and order

Typical NeurIPS Paper (five to eight sections):

1. Introduction
2. Related Work
3. Method (or "Approach", "Model")
4. Theory or Theoretical Analysis (optional; common in theory papers)
5. Experiments (datasets, setup, baselines, ablations)
6. Results and Analysis (often merged with Experiments)
7. Discussion (optional)
8. Conclusion (optional; some authors omit)
9. NeurIPS Paper Checklist (**mandatory since 2021**; uncounted; appendix slot)
10. References
11. Appendices (uncounted; proofs, extended results, dataset documentation)

The NeurIPS Paper Checklist is filled in at submission time; it covers
reproducibility, code availability, dataset documentation, broader impact,
and ethics. Missing or stub answers are a common reviewer complaint.

## 2. Page-limit class

NeurIPS:

- 9 pages main matter for submission (subject to per-year confirmation;
  has been 9 since 2021).
- References are **uncounted**.
- NeurIPS Paper Checklist is **uncounted** (appendix slot).
- Appendices are uncounted but reviewers may skim.

Camera-ready may gain one additional page (typically 10 pages main matter).

## 3. Tone characteristics

- Numerical claims dominate. Most pages of an empirical paper carry tables
  or figures of results.
- Ablation studies are expected; "we ablate X by removing it and re-running"
  is a standard sentence shape.
- First-person plural ("we") is standard.
- Math notation is welcomed but should be defined clearly.
- Hedging is moderate; "we observe" is preferred over "we prove" for
  empirical claims, and vice versa for theoretical sections.
- The community is critical of marketing language. "State-of-the-art" claims
  need head-to-head comparison tables.

## 4. Forbidden constructions

- "we propose a novel" (extremely overused; reviewers flag).
- "state-of-the-art" without head-to-head comparison plus dataset and
  metric specification.
- Single-seed experimental claims. NeurIPS expects at least three seeds
  with variance reporting for any quantitative claim.
- "Robust" without operational definition (e.g., "robust under adversarial
  perturbation at L_inf <= 0.03").
- Em-dash characters U+2014 and U+2013 (Writer dogfood rule).

## 5. Citation style

Numeric `[12]`, but the NeurIPS style uses author-year inline citations
plus a numbered References list. The style is:

- `\citep{...}` produces `(Author et al., 2023)` style parenthetical
- `\citet{...}` produces `Author et al. (2023)` textual

References list alphabetical by first author, then chronological.

## 6. Required sections

- **Abstract**: typically 200-250 words; tight.
- **Introduction**: motivation, contributions, brief preview of results.
- **Related Work**: positions against prior literature.
- **Method**: detailed enough for replication; include training details,
  hyperparameters, hardware notes.
- **Experiments / Results**: main results table, ablations, baselines.
- **NeurIPS Paper Checklist**: 8 sections (Claims, Limitations, Theory,
  Experimental Result Reproducibility, Open Access to Data and Code, Ethics,
  Broader Impact, Other). Mandatory since 2021.
- **References**: complete bibliography.

Limitations: NeurIPS encourages an explicit Limitations section since 2021;
required-by-checklist if not present elsewhere.

Broader Impact: required since 2020 (may be folded into the checklist or
its own section).

Reproducibility checklist: filled in at submission time; uncounted.

## 7. Sample corpus pointers

For tone calibration: three to five recent NeurIPS papers from the prior
two years. Sample queries:

- `https://api.openalex.org/works?filter=primary_location.source.id:<NeurIPS-source-id>,publication_year:2025`
- NeurIPS source: verify at scaffold time via OpenAlex Sources lookup
  ("Conference on Neural Information Processing Systems").

Sample across topic areas: deep learning theory, large language models,
diffusion / generative, RL, dataset papers, evaluation studies. Store as
`lit_` entries with `tags=["venue-sample:NeurIPS", "venue-sample"]`.

## Template notes

NeurIPS releases `neurips_<year>.sty` at the conference website each year.
The `fetch_template.py` (T5) lifecycle SHA-256 verifies the downloaded
file; the registry pins the URL and checksum per year. Year transitions
require a pin update with Brain ratification.

Engine: pdflatex (default). lualatex and xelatex compile but may flag
font-related warnings.

Anonymization: pre-camera-ready submissions are anonymous; the style file
has a `[final]` option for camera-ready that surfaces the author block.

## References

- NeurIPS 2025 Call for Papers (verify per year): https://neurips.cc/Conferences/2025/CallForPapers
- NeurIPS Paper Checklist guidelines: https://neurips.cc/public/guides/PaperChecklist
- NeurIPS author resources: https://neurips.cc/Conferences/2025/AuthorInformation
