# LaTeX Template Registry

Pinned-by-checksum registry of venue templates. `scripts/fetch_template.py`
(Phase 2 full lifecycle per `mis_01KS2S871YPQ3D5RVY5K3PSQY6` T5) reads this
registry, fetches the upstream archive, verifies SHA-256, and installs into
`manuscripts/<project>/<venue>/styles/`. Mismatched checksums cause refusal.

Phase 2 status: full lifecycle implemented. SHA-256 placeholders below are
populated on first fetch per workstation; subsequent fetches verify against
the captured checksum. Pin updates require Brain ratification per
dec_01KS2S22VV5P5SWWXNBXQDHMGX (LPPL discipline + provenance).

## Registry (YAML)

```yaml
# rka/skills/writer/references/template_registry.md
# Templates pinned by SHA-256. Replace TBD placeholders with actual checksums
# computed via: shasum -a 256 <file>
# Phase 1 (CHI/EMNLP) per dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D Q3.
# Phase 2 (IEEE-SP/NeurIPS/USENIX/OSDI/Nature + ieeetran/llncs/arxiv refresh)
# per dec_01KS2S22VV5P5SWWXNBXQDHMGX Option A.

acmart:
  venue_examples: [CHI, CSCW, UIST, IUI, SIGGRAPH, SOSP]
  source:
    type: CTAN
    package: acmart
    url: https://ctan.org/pkg/acmart
    dev_repo: https://github.com/borisveytsman/acmart
  license: LPPL 1.3c
  install_command: tlmgr install acmart
  pinned_version: TBD  # populated after first PI fetch (e.g., 2.07)
  archive_url: TBD  # CTAN package URL with pinned version
  sha256: TBD  # SHA-256 of acmart.cls + acmart.bst archive
  notes: |
    LPPL Component-1: modifying the class file requires renaming.
    Use a wrapper class (e.g., myproject-acmart.cls) for project-specific commands.
  options:
    - sigconf (proceedings two-column, default for CHI/UIST/CSCW)
    - sigplan (used by SOSP)
    - acmsmall (one-column, journal style)
    - manuscript (review submission)
  page_limits:
    CHI: 14 (main) + uncounted appendix + uncounted references
    CSCW: 25 + references
    UIST: 12 + references
    SOSP: 12 + references
  required_template_invocation: \documentclass[sigconf]{acmart}

acl-style-files:
  venue_examples: [ACL, EMNLP, NAACL, EACL]
  source:
    type: git
    repo: https://github.com/acl-org/acl-style-files
    pin_strategy: master_head_sha  # per Brain ratification 2026-05-20
  license: MIT (no modification by venue policy)
  install_command: git clone https://github.com/acl-org/acl-style-files && cd acl-style-files && git checkout <pinned_sha>
  pinned_version: 2353f3ea58  # commit date 2025-11-13; verified at Phase 2 T0
  sha256: TBD  # populated on first fetch (SHA-256 of acl.sty + acl_natbib.bst at pinned commit)
  notes: |
    Brain note 2026-05-20: original Phase 1 spec assumed year-branch convention
    (emnlp-2024-conference, acl-2025); empirical check showed master HEAD model
    with only frozen old year tags (2020-12, 2021-12). Switch to master_head_sha
    pinning per dec_01KS2S22VV5P5SWWXNBXQDHMGX. Pin update requires Brain
    ratification (LPPL discipline + provenance per repo policy that style files
    cannot be modified by venue policy).
  options:
    - default ACL/EMNLP style; no top-level toggles
  page_limits:
    ACL: 9 (long) / 5 (short) + uncounted references + uncounted Limitations + uncounted Ethics
    EMNLP: 8 (long) / 4 (short) + uncounted references + uncounted Limitations
  required_template_invocation: \documentclass[11pt]{article}\n\usepackage[review]{acl}
  files:
    - acl.sty
    - acl.bst
    - acl_natbib.sty

ieeetran:
  venue_examples: [IEEE-SP, IEEE-S&P, IEEE-INFOCOM, IEEE-TSE, IEEE-TPDS]
  source:
    type: CTAN
    package: ieeetran
    url: https://ctan.org/pkg/ieeetran
    dev_repo: https://michaelshell.org/tex/ieeetran/
  license: LPPL 1.3+
  install_command: tlmgr install IEEEtran
  pinned_version: TBD
  archive_url: TBD
  sha256: TBD
  notes: |
    LPPL 1.3+: modified files must be renamed. Use wrapper class for project
    additions; never edit IEEEtran.cls in place.
  options:
    - conference (default for IEEE-SP submission)
    - journal (for IEEE TSE, TPDS, journal flavor)
    - technote (short technical notes)
  page_limits:
    IEEE-SP: 13 + uncounted references
    IEEE-TSE: 14
    IEEE-ICSE: 11 + 2 reference pages = 13 total
  required_template_invocation: \documentclass[conference]{IEEEtran}

llncs:
  venue_examples: [LNCS (Springer; ESORICS, FSE, CHES, etc.)]
  source:
    type: CTAN
    package: llncs
    url: https://ctan.org/pkg/llncs
  license: LPPL
  install_command: tlmgr install llncs
  pinned_version: TBD
  archive_url: TBD
  sha256: TBD
  notes: |
    Springer LNCS family covers many security and crypto venues. LPPL
    discipline applies; do not modify llncs.cls in place.
  page_limits:
    LNCS-default: 14 (varies by series; verify per-venue)

usenix:
  venue_examples: [USENIX-Security, USENIX-ATC, USENIX-NSDI, USENIX-OSDI]
  source:
    type: venue_site
    url: https://www.usenix.org/conferences/author-resources/paper-templates
    cadence: yearly ZIP (e.g., usenix-2025-template.zip)
  license: USENIX-released (redistribute per venue terms)
  pinned_version: TBD  # populated after first PI fetch (e.g., usenix2019_v3.1.cls)
  archive_url: TBD  # yearly ZIP URL
  sha256: TBD  # SHA-256 of the yearly ZIP
  notes: |
    USENIX-family venues share one class file (usenix2019_v3.1.cls descended
    from the 2019 update). The ZIP carries the class + .bst + sample .tex.
    OSDI also pulls from this template per design.
  options:
    - default (single-column; verify against current year)
  page_limits:
    USENIX-Security: 13 + uncounted references
    USENIX-ATC: 12 + uncounted references
    USENIX-NSDI: 12 + uncounted references
    USENIX-OSDI: 12 + uncounted references
  required_template_invocation: \documentclass{usenix2019_v3.1}

neurips:
  venue_examples: [NeurIPS]
  source:
    type: conference_site
    url: https://neurips.cc/Conferences/2025/CallForPapers
    cadence: yearly bundle (neurips_<year>.sty)
  license: conference bundle (NeurIPS-released)
  pinned_version: TBD  # populated after first PI fetch (e.g., neurips_2025.sty)
  archive_url: TBD  # year-specific URL
  sha256: TBD
  notes: |
    NeurIPS releases a year-specific style file each season. Year rotation
    requires a pin update with Brain ratification. ICML and ICLR use similar
    conventions but their own style files; consider adding separate registry
    entries if needed in future phases.
  options:
    - default (anonymous review)
    - final (camera-ready; surfaces author block)
  page_limits:
    NeurIPS: 9 (main) + uncounted references + uncounted Paper Checklist + uncounted appendices
  required_template_invocation: \documentclass{article}\n\usepackage{neurips_2025}

arxiv:
  venue_examples: [arXiv preprints]
  source:
    type: git
    repo: https://github.com/kourgeorge/arxiv-style
  license: MIT
  pinned_version: TBD  # populated after first PI fetch (latest commit SHA)
  sha256: TBD
  notes: |
    Useful for arXiv-only preprints (no specific venue submission). Camera-ready
    submissions to specific venues should switch to the venue's style.

nature:
  venue_examples: [Nature, Nature Communications, Nature Methods, Nature Machine Intelligence]
  source:
    type: publisher_site
    url: https://www.overleaf.com/latex/templates/template-for-preparing-a-submission-to-nature/btysxqgkmkjf
    cadence: refreshed by publisher; verify annually
  license: Nature-released (publisher terms; redistribute restricted)
  pinned_version: TBD  # populated after first PI fetch
  archive_url: TBD
  sha256: TBD
  notes: |
    Nature-family submissions are higher-stakes editorial than the conference
    venues; PI ratification per-submission expected (lead-paragraph framing,
    specific Nature sibling target, reporting-standard compliance: CONSORT,
    STROBE, PRISMA per subfield).
    Per-journal sibling variation:
      Nature: 5000-word Article ceiling, narrative; Methods at end.
      Nature Communications: longer; less narrative emphasis.
      Nature Methods: methodology focus.
      Nature Machine Intelligence: CS / ML focus.
    Word count (not page count) is the binding constraint.
  page_limits:
    Nature-Article: 5000 words main + Extended Data (up to 10 figs + 10 tables) + SI
    Nature-Letter: 1500-2500 words main + 30 references
  required_template_invocation: \documentclass{nature}
```

## Fetching workflow (Phase 2; T5 full lifecycle)

1. PI selects a venue at the Venue checkpoint.
2. `scripts/fetch_template.py <venue>` reads the registry entry.
3. Script confirms `pinned_version`, `archive_url`, `sha256` are not `TBD`. If they are, downloads + computes SHA-256 + prompts PI to ratify the pin.
4. Script downloads `archive_url` to a temp directory.
5. Script computes SHA-256 of the downloaded archive and compares to the pinned value. On mismatch, refuses with `TemplateChecksumMismatchError` and exits with non-zero status.
6. On match, extracts the archive into `manuscripts/<project>/<venue>/styles/` and writes a `.sha256` sidecar file for cache invalidation.
7. `manuscripts/<project>/<venue>/.latexmkrc` carries `TEXINPUTS=./styles//:` (set by the workspace template).

## Updating pinned versions

When a venue releases a new template version (e.g., CHI updates `acmart` from 2.07 to 2.08, or NeurIPS bumps to a new conference-year style file), update the registry:

1. Fetch the new archive manually.
2. Verify the new template renders an empty `main.tex` cleanly: `\documentclass{...}\begin{document}\end{document}`.
3. Compute SHA-256: `shasum -a 256 <archive>`.
4. Update `pinned_version`, `archive_url`, and `sha256` in this file.
5. Commit with message `chore(writer): bump <venue> template pin to <version> with new SHA-256`.

Pin updates require Brain ratification (LPPL discipline + provenance).

## License compliance

The registry tracks each venue's license. Compliance rules:

- **LPPL components** (acmart, ieeetran, llncs, arxiv-style, nature): modified files must be renamed. Use a wrapper class for project-specific additions. Never edit the upstream class file in place.
- **MIT** (acl-style-files, arxiv kourgeorge): attribution required in the manuscript directory's `LICENSE-THIRDPARTY.md` if vendoring. Modification policy varies by upstream; ACL specifically forbids modification by venue policy.
- **USENIX-released, conference bundles**: redistribute per venue terms. Typically allow vendoring for submission-related work only.
- **Nature**: publisher-restricted redistribution; vendoring only for active submission preparation.

Phase 2 implements the full fetch + verify lifecycle. Per-manuscript LICENSE-THIRDPARTY entries are written automatically alongside vendored templates.

## Phase 2 deliverable status

- Registry expanded from 2 active (CHI/EMNLP) to 9 entries (CHI/CSCW/UIST/SOSP via acmart; ACL/EMNLP via acl-style-files; IEEE-SP family via ieeetran; LNCS family via llncs; USENIX-Security/ATC/NSDI/OSDI via usenix; NeurIPS; arXiv preprint; Nature family).
- `fetch_template.py` upgraded from Phase 1 lookup-only stub to full lifecycle (T5 deliverable).
- SHA-256 placeholders remain `TBD` until first PI fetch on a workstation; the fetch script captures + prompts for ratification.

## References

- LPPL specification: https://www.latex-project.org/lppl/lppl-1-3c/
- ACM acmart project: https://github.com/borisveytsman/acmart
- ACL style files: https://github.com/acl-org/acl-style-files (master HEAD pinned at 2353f3ea58 commit date 2025-11-13)
- USENIX templates: https://www.usenix.org/conferences/author-resources/paper-templates
- NeurIPS CFP: https://neurips.cc/Conferences/2025/CallForPapers
- Nature submission: https://www.nature.com/nature/for-authors/initial-submission
- Per-venue policy survey: `jrn_01KS0AVZRDA0KPXK61MN9PV5DE` section "LaTeX templates (authoritative sources, 2026)".
- Phase 2 ACL pin ratification: Brain decision 2026-05-20 per `dec_01KS2S22VV5P5SWWXNBXQDHMGX` (master_head_sha strategy).
