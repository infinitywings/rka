# LaTeX Template Registry

Pinned-by-checksum registry of venue templates. `scripts/fetch_template.py` (Phase 2) reads this registry, fetches the upstream archive, verifies SHA-256, and installs into `manuscripts/<project>/<venue>/styles/`. Mismatched checksums cause refusal.

Phase 1 ships the registry as a stub with placeholders; the PI provides actual SHA-256 values after the first fetch on a given workstation. Phase 2 wires the fetch automation.

## Registry (YAML)

```yaml
# rka/skills/writer/references/template_registry.md
# Templates pinned by SHA-256. Replace TBD placeholders with actual checksums
# computed via: shasum -a 256 <file>
# Per dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D Q3, Phase 1 ships ACL/EMNLP + ACM CHI.

acmart:
  venue_examples: [CHI, CSCW, UIST, IUI, SIGGRAPH]
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
    - acmsmall (one-column, journal style)
    - manuscript (review submission)
  page_limits:
    CHI: 14 (main) + uncounted appendix + uncounted references
    CSCW: 25 + references
    UIST: 12 + references
  required_template_invocation: \documentclass[sigconf]{acmart}

acl-style-files:
  venue_examples: [ACL, EMNLP, NAACL, EACL]
  source:
    type: git
    repo: https://github.com/acl-org/acl-style-files
    pinned_branch: 2025  # update per venue year
  license: MIT
  install_command: git clone --branch 2025 https://github.com/acl-org/acl-style-files
  pinned_version: TBD  # populated after first PI fetch (commit SHA at branch 2025)
  sha256: TBD  # SHA-256 of the .sty + .bst at the pinned commit
  notes: |
    Venue policy: no modification of style files permitted.
    No wrapper class needed; project additions go into preamble of main.tex.
  options:
    - default ACL/EMNLP style; no top-level toggles
  page_limits:
    ACL: 9 (long) / 5 (short) + uncounted references + uncounted Limitations + uncounted Ethics
    EMNLP: 8 (long) / 4 (short) + uncounted references + uncounted Limitations
  required_template_invocation: \documentclass[11pt]{article}\n\usepackage[review]{acl}

# Phase 2 entries (placeholders; not used in Phase 1):

ieeetran:
  venue_examples: [IEEE-SP, IEEE-S&P, IEEE-INFOCOM, IEEE-TSE]
  source:
    type: CTAN
    package: ieeetran
    url: https://ctan.org/pkg/ieeetran
  license: LPPL 1.3+
  install_command: tlmgr install IEEEtran
  pinned_version: TBD
  archive_url: TBD
  sha256: TBD
  phase_1_status: "Phase 2 only; not configured for use in Phase 1."

llncs:
  venue_examples: [LNCS (Springer)]
  source:
    type: CTAN
    package: llncs
    url: https://ctan.org/pkg/llncs
  license: LPPL
  install_command: tlmgr install llncs
  pinned_version: TBD
  archive_url: TBD
  sha256: TBD
  phase_1_status: "Phase 2 only."

usenix:
  venue_examples: [USENIX-Security, USENIX-OSDI, USENIX-NSDI]
  source:
    type: venue_site
    url: https://www.usenix.org/conferences/author-resources/paper-templates
    cadence: yearly ZIP (e.g., usenix-2025-template.zip)
  license: USENIX-released
  pinned_version: TBD
  archive_url: TBD
  sha256: TBD
  phase_1_status: "Phase 2 only."

neurips:
  venue_examples: [NeurIPS]
  source:
    type: conference_site
    url: https://neurips.cc/Conferences/2026/CallForPapers
    cadence: yearly bundle
  license: conference bundle
  pinned_version: TBD
  archive_url: TBD
  sha256: TBD
  phase_1_status: "Phase 2 only."

arxiv:
  venue_examples: [arXiv preprints]
  source:
    type: git
    repo: https://github.com/kourgeorge/arxiv-style
  license: MIT
  pinned_version: TBD
  sha256: TBD
  phase_1_status: "Phase 2 only."
```

## Fetching workflow (Phase 2)

1. PI selects a venue at the Venue checkpoint.
2. `scripts/fetch_template.py <venue>` reads the registry entry.
3. Script confirms `pinned_version`, `archive_url`, `sha256` are not `TBD`. If they are, prompt PI to fill them after the first fetch (and re-run).
4. Script downloads `archive_url` to a temp directory.
5. Script computes SHA-256 of the downloaded archive and compares to the pinned value. On mismatch, refuses and exits with error.
6. On match, extracts the archive into `manuscripts/<project>/<venue>/styles/`.
7. `manuscripts/<project>/<venue>/.latexmkrc` already carries `TEXINPUTS=./styles//:`.

Phase 1 status: `fetch_template.py` is a stub. It implements registry lookup only. Actual fetch logic + SHA-256 verification land in Phase 2. PI handles template installation manually in Phase 1.

## Updating pinned versions

When a venue releases a new template version (e.g., CHI updates `acmart` from 2.07 to 2.08, or ACL bumps `acl-style-files` to a new conference-year branch), update the registry:

1. Fetch the new archive manually.
2. Verify the new template renders an empty `main.tex` cleanly: `\documentclass{...}\begin{document}\end{document}`.
3. Compute SHA-256: `shasum -a 256 <archive>`.
4. Update `pinned_version`, `archive_url`, and `sha256` in this file.
5. Commit with message `chore(writer): bump <venue> template pin to <version> with new SHA-256`.

The pin update is itself a small PI ratification gate, since the template change may carry style implications.

## License compliance

The registry tracks each venue's license. Compliance rules:

- **LPPL components** (acmart, ieeetran, llncs, arxiv-style): modified files must be renamed. Use a wrapper class for project-specific additions. Never edit the upstream class file in place.
- **MIT** (acl-style-files, arxiv kourgeorge): attribution required in the manuscript directory's `LICENSE-THIRDPARTY.md` if vendoring (Phase 2 will create per-manuscript LICENSE-THIRDPARTY entries as templates are installed). Modification policy varies by upstream; ACL specifically forbids modification by venue policy.
- **USENIX-released, conference bundles**: redistribute per venue terms. Typically allow vendoring for submission-related work only.

Phase 1 ships the registry only; no templates are actually fetched or installed. Phase 2 implements the full lifecycle with license-banner injection into each vendored archive copy.

## Phase 1 limitations

- `pinned_version`, `archive_url`, `sha256` are all `TBD`. PI fills them in after the first manual fetch on a given workstation.
- `scripts/fetch_template.py` is registry-lookup-only. PI fetches templates manually using the `install_command` listed per entry.
- Wrapper class scaffolding for LPPL extensions is not generated; PI authors the wrapper manually if needed.

Phase 2 closes all three gaps.

## References

- LPPL specification: https://www.latex-project.org/lppl/lppl-1-3c/
- ACM acmart project: https://github.com/borisveytsman/acmart
- ACL style files: https://github.com/acl-org/acl-style-files
- Per-venue policy survey: `jrn_01KS0AVZRDA0KPXK61MN9PV5DE` section "LaTeX templates (authoritative sources, 2026)".
