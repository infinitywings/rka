# Venue Schema (v1)

Machine-readable spec for every Writer-supported venue. One
`venue/<id>.yaml` per venue; the narrative `venue/<id>.md` is
auto-generated from the YAML + an optional `venue/<id>.notes.md`
freeform tail (for sample-corpus pointers, anonymization quirks, and
review-anecdote anti-patterns that don't fit the structured schema).

Consumed by:

- `scripts/layout_audit.py` — page limits, references-counted policy,
  required checklist, anonymization rules.
- `scripts/ai_tic_lint.py` — forbidden constructions + tone classifiers
  (Phase W2 will load this; today's wiring lands in W1 for page
  limits + reads tone descriptors for future use).
- `mcp_tools/server.py` — venue lookup tool surface.
- `cfp_loader.py` (W2) — fetches `cfp.primary_url` and overlays its
  parsed deltas onto `submission`, `format`, and `structure` for a
  specific year's CFP.

## File layout

```
rka/skills/writer/references/venue/
├── _schema.md                    ← this file
├── CHI.yaml                      ← machine spec (source of truth)
├── CHI.md                        ← auto-generated narrative
├── CHI.notes.md                  ← optional freeform tail
├── NeurIPS.yaml
├── NeurIPS.md
├── ...
└── proposals/
    ├── NSF-PAPPG.yaml            ← universal NSF baseline
    └── solicitations/
        └── NSF-23-560.yaml       ← inherits NSF-PAPPG; deltas only
```

## Schema (v1)

```yaml
schema_version: v1              # MUST be "v1"; bump on breaking change
id: NeurIPS                     # MUST match filename stem
name: Conference on Neural Information Processing Systems
kind: conference                # conference | journal | proposal
domain: cs-ml                   # cs-ml | cs-systems | cs-pl | cs-security
                                # | cs-hci | cs-db | cs-net | cs-arch | cs-se
                                # | sci-general | acct | fin | mgmt | proposal
status: active                  # active | deprecated | year-specific
pin_year: 2025                  # year the spec was verified against

# ---------------------------------------------------------------------------
# Submission constraints — linter-enforced
# ---------------------------------------------------------------------------
submission:
  page_limit_main: 9            # int OR null (null = no hard limit, e.g., journals)
  page_limit_camera_ready: 10   # int OR null (omit if same as main)
  references_counted: false     # do references count toward page limit?
  appendix_counted: false       # does appendix count toward page limit?
  appendix_limit: null          # int OR null (null = unlimited)
  has_required_checklist: true  # e.g., NeurIPS Paper Checklist
  anonymization: required_pre_camera_ready
                                # none | required | required_pre_camera_ready

# ---------------------------------------------------------------------------
# Format — what to compile with
# ---------------------------------------------------------------------------
format:
  template_id: neurips_official # key into template_registry.md
  engine_default: pdflatex      # pdflatex | lualatex | xelatex
  engines_supported: [pdflatex, lualatex, xelatex]
  citation_style: numeric-author-year-mixed
                                # see "Citation style enums" below
  bibliography_style: alphabetical
                                # alphabetical | numeric-cite-order | name-year

# ---------------------------------------------------------------------------
# Structure — section names + order
# ---------------------------------------------------------------------------
structure:
  required_sections:            # MUST appear in every paper
    - Abstract
    - Introduction
    - Method
    - Experiments
    - References
  optional_sections:            # commonly used; not enforced
    - Related Work
    - Theory
    - Discussion
    - Limitations
    - Broader Impact
    - Conclusion
  appendix_sections: []         # typical appendix contents (informational)
  section_order:                # canonical order when all present
    - Introduction
    - Related Work
    - Method
    - Theory
    - Experiments
    - Results and Analysis
    - Discussion
    - Conclusion
    - References
    - Appendices
  abstract_word_min: 150
  abstract_word_target: 200
  abstract_word_max: 300

# ---------------------------------------------------------------------------
# Tone + content style — guides Brain prose composition
# ---------------------------------------------------------------------------
tone:
  voice: first-person-plural    # first-person-plural | third-person | passive | mixed
  hedging: moderate             # low | moderate | high
  marketing_language: discouraged   # encouraged | neutral | discouraged
  math_density: high            # low | moderate | high
  numerical_claims_dominate: true
  ablation_studies_expected: true   # CS empirical convention
  multi_seed_required: true     # e.g., NeurIPS ≥3 seeds with variance
  reproducibility_floor: high   # low | moderate | high

# ---------------------------------------------------------------------------
# Review dimensions — what reviewers score on (informs structure emphasis)
# ---------------------------------------------------------------------------
review_dimensions:
  - name: technical_quality
    weight: high                # high | medium | low
  - name: novelty
    weight: high
  - name: clarity
    weight: medium
  - name: significance
    weight: high
  - name: reproducibility
    weight: high

# ---------------------------------------------------------------------------
# Forbidden constructions — patterns ai_tic_lint.py flags
# ---------------------------------------------------------------------------
forbidden_constructions:
  - pattern: "we propose a novel"
    reason: "extremely overused at this venue; reviewers flag"
    severity: warn              # block | warn | info
  - pattern: "state-of-the-art"
    reason: "requires head-to-head comparison + dataset + metric specification"
    severity: warn

# ---------------------------------------------------------------------------
# Sample corpus — for tone calibration scaffolding
# ---------------------------------------------------------------------------
sample_corpus:
  query_method: openalex        # openalex | semantic-scholar | arxiv | crossref
  filter_template: "primary_location.source.id:S<TBD>,publication_year:{year}"
  recommended_year_range: [2024, 2025]
  diversity_topics:
    - deep_learning_theory
    - llm
    - diffusion
    - rl
    - datasets
    - evaluation
  rka_tag: "venue-sample:NeurIPS"   # tag for ingested calibration samples

# ---------------------------------------------------------------------------
# CFP linkage — what the cfp_loader (W2) reads / overlays
# ---------------------------------------------------------------------------
cfp:
  primary_url: https://neurips.cc/Conferences/2025/CallForPapers
  author_guide_url: https://neurips.cc/Conferences/2025/AuthorInformation
  checklist_url: https://neurips.cc/public/guides/PaperChecklist  # nullable
  last_verified: 2026-05-26

# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------
provenance:
  schema_origin: dec_01KS2S22VV5P5SWWXNBXQDHMGX
  last_updated: 2026-05-26

# ---------------------------------------------------------------------------
# Proposal inheritance (proposals only)
# ---------------------------------------------------------------------------
# For kind=proposal solicitations (NSF specific calls), set:
#   inherits_from: NSF-PAPPG    # base spec to merge under this delta
# Only fields explicitly set here override the base.
```

## Citation style enums

| value | meaning | typical venues |
|---|---|---|
| `numeric` | `[12]` only, bibliography in cite order | USENIX, IEEE-S&P (numeric option) |
| `numeric-cite-order` | `[12]` ordered by first citation | OSDI, ACM SIGCONF default |
| `numeric-author-year-mixed` | both styles supported / venue-dependent | NeurIPS, ICML |
| `name-year` | `(Author 2023)` parenthetical | most natural-sciences venues |
| `author-year` | `Author (2023)` textual, AMA-style | accounting / finance journals |
| `vancouver` | numeric with formatted reference list | medical / biology |

## Domain enums

| value | meaning |
|---|---|
| `cs-ml` | machine learning + AI (NeurIPS, ICML, ICLR, AAAI, IJCAI) |
| `cs-systems` | operating systems + distributed systems (OSDI, SOSP, NSDI, EuroSys) |
| `cs-security` | security + privacy (IEEE-S&P, USENIX-Security, CCS, NDSS) |
| `cs-hci` | human–computer interaction (CHI, CSCW, UIST) |
| `cs-pl` | programming languages (POPL, PLDI, OOPSLA) |
| `cs-db` | databases (SIGMOD, VLDB, ICDE) |
| `cs-net` | networking (SIGCOMM, MobiCom, NSDI) |
| `cs-arch` | computer architecture (ISCA, MICRO, ASPLOS, HPCA) |
| `cs-se` | software engineering (ICSE, FSE, ASE) |
| `sci-general` | general-science multidisciplinary (Nature, Science) |
| `acct` | accounting (TAR, JAR, JAE, CAR, RAS, AOS) |
| `fin` | finance (JoF, JFE, RFS, JFQA) |
| `mgmt` | management (AMJ, AMR, ASQ, SMJ, OrgSci, MSci, JoM) |
| `proposal` | grant proposal (NSF-PAPPG and solicitations) |

## Adding a new venue

1. Author `<id>.yaml` per this schema. Validate via `venue_loader.py
   --strict <id>` (raises on missing required fields).
2. Run `venue_md_generator.py <id>` to produce `<id>.md` (idempotent
   regeneration; preserves a `<!-- BEGIN MANUAL TAIL -->`-fenced
   block at the bottom if it exists).
3. Add the venue to `template_registry.md` if it needs a new
   LaTeX class/style not already covered.
4. (Optional) Drop sample corpus tags via `rka_add_literature` so
   future Brain runs have tone-calibration references.

## Versioning

- Schema bumps are MAJOR-only: any breaking change (renaming a top-
  level key, changing a required→optional or vice versa, removing a
  field) → bump `schema_version`. Adding a new optional field is
  schema-compatible (still v1).
- Per-venue `pin_year` rotates as the venue publishes a new year's
  CFP. Pin rotation requires Brain ratification (LPPL discipline +
  provenance, per dec_01KS2S22VV5P5SWWXNBXQDHMGX).
