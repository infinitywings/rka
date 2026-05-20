# Nature (and Nature family)

Phase 2 venue per `dec_01KS2S22VV5P5SWWXNBXQDHMGX` Option A deliverable 4.
Schema follows Phase 1 CHI.md and EMNLP.md (seven fields).

Nature (and its sibling journals: Nature Communications, Nature Methods,
Nature Machine Intelligence, etc.) uses a narrative scientific style
distinct from the conference-paper venues in this registry. The
publisher provides submission-format LaTeX class files via Overleaf
templates and a downloadable ZIP from the journal site.

Note: Nature-family submission conventions are tighter than typical
conference venues; PI ratification per-submission of tone, narrative
arc, and specific journal target is expected.

## 1. Section names and order

Typical Nature Article (often unnumbered in the rendered output):

1. Title and lead-in (one-sentence opener)
2. Lead paragraph (abstract substitute; the "throw"; typically 150-200 words)
3. Body (continuous prose; "Introduction" is often unlabeled or skipped)
4. Results (often the bulk of the manuscript; structured around figures)
5. Discussion (or "Outlook"; placed before Methods unlike most conference venues)
6. Methods (placed AT END unlike most conference venues; longer than typical;
   often 1500-3000 words; detailed enough for replication)
7. References (10-50 typical for an Article; can be much higher for Reviews)
8. Acknowledgments
9. Author Contributions (mandatory)
10. Competing Interests (mandatory)
11. Data Availability statement (mandatory since 2017)
12. Code Availability statement (mandatory since 2020 for code-bearing work)
13. Extended Data (figures and tables; uncounted; up to 10 figures + 10 tables)
14. Supplementary Information (further uncounted material; PDFs, code, data)

Nature Letters are shorter (1500-2500 words main text + 30 references max
typically) and follow the same narrative structure.

## 2. Page-limit class

Nature Articles:

- **5000 words main text** for Articles (the canonical limit).
- Up to 50 references for Articles (less for Letters).
- Extended Data: up to 10 figures + 10 tables, uncounted.
- Supplementary Information: separate, uncounted.

Nature Letters:

- 1500-2500 words main text.
- Up to 30 references.

Nature Methods, Nature Communications, etc., vary; verify per-journal.

Word counts (not page counts) are the binding constraint.

## 3. Tone characteristics

- Narrative-first. Nature prose tells a story; the lead paragraph hooks
  general scientific readers (not just specialists in the field).
- Cross-discipline accessibility: assume the reader is a scientist but not
  necessarily in your specific subfield. Jargon defined early.
- Concise: every word earns its place given the 5000-word ceiling.
- Active voice. Nature has historically pushed authors toward active
  ("we observed") over passive ("it was observed"); this has stabilized.
- First-person plural ("we") is standard.
- Strong claims welcomed when supported; Nature audiences appreciate clear
  framing of significance and surprise.
- The opening sentence carries unusual weight; it is often workshopped
  more than any other sentence.

## 4. Forbidden constructions

- "we propose a novel" (overused across all venues; especially flagged
  given Nature's narrative emphasis).
- Generic claims of "comprehensive" coverage; specify the scope.
- Marketing language: "groundbreaking", "transformative", "paradigm-shifting"
  (Nature's editors strip these in editing).
- "It is important to note" and similar empty connectives (Nature's
  word budget makes these costly).
- Em-dash characters U+2014 and U+2013 (Writer dogfood rule).

Note: Nature editorial style historically permits em-dash in published
prose; the Writer's rule is dogfood-discipline, not Nature-house-style.

## 5. Citation style

Numeric superscript (`...the result^{12}...`) is the Nature signature.
Multi-citation: `...the result^{12,13}...` or `^{12-15}`.

The Nature LaTeX class handles citation formatting via the
`nature.bst` style. References list ordered numerically by first citation.

For Nature Communications and some Nature siblings, numeric inline `[12]`
is also used; verify per-journal.

## 6. Required sections

- **Title**: typically <= 15 words.
- **Lead paragraph**: 150-200 words; hooks general scientific readers.
- **Body**: continuous narrative.
- **Results**: structured around figures.
- **Discussion**: integration of findings; future directions.
- **Methods**: detailed; placed at end; includes statistical analyses.
- **References**: complete bibliography.
- **Author Contributions**: mandatory; per-author breakdown.
- **Competing Interests**: mandatory; declares conflicts.
- **Data Availability**: mandatory since 2017.
- **Code Availability**: mandatory since 2020 for computational work.

Nature requires CONSORT, STROBE, PRISMA, or similar reporting standards
for relevant domains (clinical trials, observational studies, systematic
reviews). The journal's submission guidelines list current reporting
standards.

## 7. Sample corpus pointers

For tone calibration: three to five recent Nature Articles or Letters from
the prior two years in your specific subfield. Cross-field samples are
less useful here than for conference venues; Nature prose varies
substantially across subfields. Sample queries:

- `https://api.openalex.org/works?filter=primary_location.source.id:<Nature-source-id>,publication_year:2025`
- Nature source ID: verify at scaffold time via OpenAlex Sources lookup.

Sample within your subfield: pick three to five recent papers in your
specific topic area, not generic Nature articles.

Store as `lit_` entries with `tags=["venue-sample:Nature", "venue-sample"]`
plus a subfield tag (e.g., `subfield:computer-science`).

## Template notes

Nature ships the canonical class file via Overleaf and the journal site.
The Nature LaTeX template is currently `nature-template.tex` (with the
`nature.cls` class). Update annually as Nature reissues templates.

The `fetch_template.py` (T5) lifecycle SHA-256 verifies the downloaded
class file; the registry pins the URL and checksum.

Engine: pdflatex (default). Nature's class supports lualatex and xelatex
for system-font use cases.

LaTeX is supported but Microsoft Word remains common for Nature
submissions in some subfields; the Writer skill targets LaTeX only.

## Caveats

Nature-family submissions are higher-stakes editorial than the conference
venues in this registry. The Writer skill drafts the LaTeX manuscript; the
PI is expected to engage Nature's editorial process directly post-submission.

PI ratification per-submission is expected for the following Nature-specific
elements that vary by subfield:

- Lead paragraph framing (the "throw")
- Specific Nature journal target (Nature vs Nature Communications vs Nature
  Methods vs subject-specific Nature journal)
- Reporting standard compliance (CONSORT, STROBE, etc.)

## References

- Nature submission guidelines: https://www.nature.com/nature/for-authors/initial-submission
- Nature LaTeX template (Overleaf): https://www.overleaf.com/latex/templates/template-for-preparing-a-submission-to-nature/btysxqgkmkjf
- Nature Code Availability policy: https://www.nature.com/nature-portfolio/editorial-policies/reporting-standards
- Nature reporting standards: https://www.nature.com/nature-portfolio/editorial-policies/reporting-standards
