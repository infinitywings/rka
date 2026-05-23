# LaTeX Layout Audit

`scripts/layout_audit.py` runs after a successful latexmk render and emits `audit.json` over twelve fields. Each field returns `PASS`, `WARN`, or `BLOCK`. Any `BLOCK` halts progress until resolved; `WARN` verdicts are surfaced for the Final Layout PI checkpoint.

## The twelve fields

### 1. `pages_over_limit` (BLOCK any non-zero)

Compare the rendered PDF page count to the venue page limit (carried in `references/venue/<venue>.md`, field "Page-limit class"). Page count from `pdfinfo main.pdf | grep Pages`.

Verdict:
- `PASS` if `pages <= limit`.
- `WARN` if `pages == limit` (no margin for revision).
- `BLOCK` if `pages > limit`.

Regex for log: not applicable; uses pdfinfo. Implementation: `subprocess.run(['pdfinfo', pdf_path])` and parse the `Pages:` line.

### 2. `undefined_citations` (BLOCK any)

Search `.log` for `LaTeX Warning: Citation .* undefined`. Each match indicates a `\cite{...}` referencing a key not in the `.bib` file.

Verdict:
- `PASS` if zero matches.
- `BLOCK` if at least one match.

Regex: `^LaTeX Warning: Citation `(.*?)' .* undefined`.

### 3. `undefined_refs` (BLOCK any)

Search `.log` for `LaTeX Warning: Reference .* undefined`. Each match indicates a `\ref{...}` or `\eqref{...}` targeting a label that does not exist.

Verdict:
- `PASS` if zero matches.
- `BLOCK` if at least one match.

Regex: `^LaTeX Warning: Reference `(.*?)' on page .* undefined`.

### 4. `missing_bib_keys` (BLOCK any)

Search `.blg` (BibTeX log) for `Warning--I didn't find a database entry for`. Each match indicates a citation key that BibTeX could not resolve from any input `.bib` file.

Verdict:
- `PASS` if zero matches.
- `BLOCK` if at least one match.

Regex: `^Warning--I didn't find a database entry for "(.*?)"`.

### 5. `question_mark_citations` (BLOCK any)

After render, scan the PDF text via `pdftotext main.pdf -` for occurrences of `[?]` (LaTeX's default for an unresolved citation). Even if undefined-citation warnings are absent (e.g., suppressed), `[?]` in the rendered output is a hard block.

Verdict:
- `PASS` if zero `[?]` in `pdftotext` output.
- `BLOCK` if at least one match.

Regex: `\[\?\]`.

### 6. `orphan_refs` (BLOCK any)

A `\ref{label}` or `\eqref{label}` exists in the source but the corresponding `\label{label}` is not in any rendered section (e.g., points to a section that was commented out). Detected by cross-referencing the `.aux` file label table against the `.tex` source `\ref` calls.

Verdict:
- `PASS` if every `\ref` resolves to a known label.
- `BLOCK` if at least one orphan.

Implementation: parse `.aux` for `\newlabel{...}` declarations; grep `.tex` files for `\ref{...}` and `\eqref{...}` calls; diff the sets.

### 7. `overfull_hboxes_over_10pt` (WARN)

Search `.log` for `Overfull \hbox` with overflow greater than 10 pt. Smaller overflows are usually invisible; larger ones produce visible black-bar artifacts in the rendered PDF.

Verdict:
- `PASS` if zero matches over 10 pt.
- `WARN` if at least one match over 10 pt.

Regex: `^Overfull \\hbox \((\d+(?:\.\d+)?)pt too wide\)`. Filter where group 1 > 10.0.

### 8. `overfull_vboxes` (WARN)

Search `.log` for `Overfull \vbox`. Any occurrence is a warning.

Verdict:
- `PASS` if zero.
- `WARN` if at least one.

Regex: `^Overfull \\vbox`.

### 9. `float_too_large` (WARN)

Search `.log` for `Float too large for page`. Indicates a `figure` or `table` environment that exceeds page-height and may be placed unexpectedly.

Verdict:
- `PASS` if zero.
- `WARN` if at least one.

Regex: `Float too large for page`.

### 10. `underfull_badness_over_5000` (WARN)

Search `.log` for `Underfull \hbox` with badness greater than 5000. Smaller badness values are tolerated by venue style files; larger ones indicate noticeable spacing irregularities.

Verdict:
- `PASS` if zero matches over badness 5000.
- `WARN` if at least one.

Regex: `^Underfull \\hbox \(badness (\d+)\)`. Filter where group 1 > 5000.

### 11. `chktex_warnings_over_10` (WARN)

Run `chktex -q main.tex` (or `chktex` on each `sections/*.tex`). chktex produces lint warnings for common LaTeX style issues (e.g., wrong dash kind, smart-quotes, math-mode in text, et cetera).

Verdict:
- `PASS` if total chktex warnings under or equal to 10.
- `WARN` if over 10.

Implementation: `subprocess.run(['chktex', '-q', tex_file])`, parse stdout for warning lines.

### 12. `pages_equals_limit` (WARN)

Already covered as a sub-case of field 1, but tracked separately so the Final Layout checkpoint sees this as an explicit signal (no revision margin).

Verdict:
- `PASS` if `pages < limit`.
- `WARN` if `pages == limit`.

## audit.json schema

```json
{
  "manuscript": "manuscripts/<project>/<venue>/main.tex",
  "rendered_at": "2026-05-19T17:45:00Z",
  "pdf_path": "main.pdf",
  "venue": "CHI",
  "page_limit": 14,
  "pages_rendered": 13,
  "fields": {
    "pages_over_limit": {"verdict": "PASS", "value": 13, "threshold": 14},
    "undefined_citations": {"verdict": "PASS", "value": 0, "matches": []},
    "undefined_refs": {"verdict": "PASS", "value": 0, "matches": []},
    "missing_bib_keys": {"verdict": "PASS", "value": 0, "matches": []},
    "question_mark_citations": {"verdict": "PASS", "value": 0},
    "orphan_refs": {"verdict": "PASS", "value": 0, "matches": []},
    "overfull_hboxes_over_10pt": {"verdict": "WARN", "value": 1, "matches": [{"line": 142, "overflow_pt": 12.3}]},
    "overfull_vboxes": {"verdict": "PASS", "value": 0},
    "float_too_large": {"verdict": "PASS", "value": 0},
    "underfull_badness_over_5000": {"verdict": "PASS", "value": 0},
    "chktex_warnings_over_10": {"verdict": "PASS", "value": 7},
    "pages_equals_limit": {"verdict": "PASS", "value": 13, "threshold": 14}
  },
  "summary": {
    "blocks": 0,
    "warns": 1,
    "passes": 11,
    "overall_verdict": "WARN"
  }
}
```

## Overall verdict

The `summary.overall_verdict` is computed by:

```python
if any(f["verdict"] == "BLOCK" for f in fields.values()):
    overall = "BLOCK"
elif any(f["verdict"] == "WARN" for f in fields.values()):
    overall = "WARN"
else:
    overall = "PASS"
```

Final Layout PI checkpoint cannot ratify `submit` if `overall_verdict == "BLOCK"`. `WARN` is acceptable for submit; the PI is the final arbiter.

## Engine-specific notes

Some venue templates produce engine-specific warnings:

- `acmart` with `pdflatex` produces "PDF inclusion: multiple pdfs with page group included in a single page" warnings under draft mode. These are non-fatal and tracked as a WARN if frequent (over 5).
- `acl-style-files` requires `pdflatex` (not lualatex); `xelatex` triggers font-loading failures for the default ACL fonts. The venue file at `references/venue/EMNLP.md` documents this.
- USENIX templates require specific font packages; missing fonts produce "Font ... not found" warnings that surface as orphan refs in some chains. The Phase 2 USENIX venue file will document the engine pinning.

## Phase 2 extensions (not in Phase 1 scope)

- Cross-render comparison: compare `pages_rendered` against last session's `audit.json` to surface scope drift.
- Figure-vs-text-area ratio (visual balance heuristic for HCI venues).
- Citation density per section (anti-pattern: dumping all citations in Related Work).
- Hyperref color audit (some venues block colored links; the venue files Phase 2 will encode this).

These extensions are tracked for Phase 2 design; not implemented in Phase 1.
