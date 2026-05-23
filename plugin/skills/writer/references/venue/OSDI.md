# OSDI (USENIX Symposium on Operating Systems Design and Implementation) + SOSP umbrella

Phase 2 venue per `dec_01KS2S22VV5P5SWWXNBXQDHMGX` Option A deliverable 4.
Schema follows Phase 1 CHI.md and EMNLP.md (seven fields).

OSDI is hosted by USENIX and shares the USENIX-family LaTeX template
(`usenix2019_v3.1.cls`). SOSP (Symposium on Operating Systems Principles)
is hosted by ACM but follows similar paper structure norms; SOSP uses
`acmart` with `sigplan` or `sigops` options.

OSDI and SOSP are the flagship systems venues; the community values
engineering depth, quantitative evaluation, and reproducibility.

## 1. Section names and order

Typical OSDI paper (six to eight sections):

1. Introduction
2. Background and Motivation (one section is common)
3. Design (system architecture and key insights)
4. Implementation (code-level details, optimizations, hardware notes)
5. Evaluation (benchmarks, measurements, ablations)
6. Related Work (some authors place earlier as Section 2; either layout)
7. Discussion (optional; sometimes folded into Evaluation)
8. Conclusion
9. References
10. Appendices (uncounted; artifact details, additional measurements)

The Design and Implementation split is characteristic: Design covers
high-level architecture; Implementation covers the specific engineering
choices (data structures, lock-free algorithms, kernel hooks).

## 2. Page-limit class

OSDI:

- 12 pages main matter for submission (verify against current year CFP;
  has been 12 since ~2020).
- References are **uncounted**.
- Appendices are uncounted but heavily skimmed by reviewers.

SOSP follows the ACM acmart sigplan template, typically 12 pages.

Both venues run an artifact evaluation track that lets authors earn
artifact-available, artifact-functional, and reproducible badges.

## 3. Tone characteristics

- Engineering-first. Systems papers emphasize what was built, why specific
  design choices were made, and what tradeoffs apply.
- Quantitative paramount. Most pages of an evaluation section carry
  performance numbers (latency, throughput, memory, energy).
- Hardware specificity: state CPU model, RAM, kernel version, hardware
  layout. Reviewers expect specifics.
- First-person plural ("we") is standard. Code listings welcomed (with
  syntax highlighting if the venue style supports it).
- Acronym discipline: define on first use; OSDI reviewers tolerate
  systems-community acronyms (RDMA, NUMA, JIT) without redefinition.
- Hedging is minimal; performance claims are stated with measurements and
  confidence intervals.

## 4. Forbidden constructions

- "we propose a novel" (overused).
- Single-machine benchmarks without scaling analysis (for distributed systems).
- Performance numbers without variance reporting (run at least three trials).
- "Faster" or "more efficient" as bare adjectives (require specific units
  and baselines).
- Em-dash characters U+2014 and U+2013 (Writer dogfood rule).

## 5. Citation style

OSDI: numeric brackets `[12]` per USENIX convention. Style file
`usenix-numeric.bst` or `plain.bst`.

SOSP: numeric brackets `[12]` per `acmart` defaults (sigplan option).

Multi-citation: `[12, 13]` or compressed `[12-15]` with usenix-numeric.bst.

References list ordered numerically by first citation.

## 6. Required sections

- **Abstract**: 200-300 words typical.
- **Introduction**: motivation, problem framing, contribution claims.
- **Background and Motivation**: positions the problem.
- **Design**: system architecture, design rationale.
- **Implementation**: specific engineering choices.
- **Evaluation**: quantitative benchmarks with rigor.
- **Related Work**: positions against prior systems work.
- **Conclusion**: summary, future work.
- **References**: complete bibliography.

OSDI does not currently require an Ethics statement at the top level but
encourages discussion when relevant (e.g., user-facing telemetry systems).

Artifact submission: OSDI and SOSP both run artifact evaluation. Artifacts
include code, build instructions, dataset pointers, and reproducibility
notes; the artifact appendix is a separate submission step.

## 7. Sample corpus pointers

For tone calibration: three to five recent OSDI or SOSP papers from the
prior two years. Sample queries:

- `https://api.openalex.org/works?filter=primary_location.source.id:<OSDI-source-id>,publication_year:2025`
- OSDI source: verify at scaffold time via OpenAlex Sources lookup
  ("USENIX Symposium on Operating Systems Design and Implementation").

Sample across topic areas: distributed systems, storage, networking,
operating system kernels, ML systems, hardware co-design, formal
verification of systems.

Store as `lit_` entries with `tags=["venue-sample:OSDI", "venue-sample"]`.

## Template notes

OSDI uses `usenix2019_v3.1.cls` from the USENIX yearly ZIP. The
`fetch_template.py` (T5) lifecycle SHA-256 verifies the ZIP; the registry
pins the URL and checksum per year.

SOSP uses `acmart` with `sigplan` option:

```latex
\documentclass[sigplan]{acmart}
```

Engine: pdflatex (default for both). lualatex and xelatex compile but
may flag font-substitution warnings.

## References

- OSDI 2025 CFP (verify per year): https://www.usenix.org/conference/osdi25
- USENIX Author Templates: https://www.usenix.org/conferences/author-resources/paper-templates
- SOSP author guide: https://sosp.org/
- ACM acmart for SOSP: https://github.com/borisveytsman/acmart
