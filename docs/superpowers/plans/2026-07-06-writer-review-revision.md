# Writer "Review & Revision" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an advisory, reviewer-lens pre-submission review and an old-vs-new revision-check to the RKA writer skill, plus a WARN-only overclaim linter, without gating on LLM judgment.

**Architecture:** Two new reference checklists (`manuscript_review.md`, `revision_check.md`), one new WARN-only script (`overclaim_lint.py`) mirroring `ai_tic_lint.py`, and SKILL.md wiring (new "Pre-Submission Review" section + revision-check subsection + `writer-review` mission path). Source of truth is `rka/skills/writer/`; mirrored to `plugin/skills/writer/`.

**Tech Stack:** Python 3.11 stdlib (argparse, re, json, dataclasses), pytest (module-loaded via conftest `_load_module`), Markdown.

## Global Constraints

- Skill files live under `rka/skills/writer/` ONLY (+ `tests/skills/writer/`) — bookkeeper invariant; never add RKA orchestration elsewhere.
- **Advisory-only:** the review never BLOCKs compile/submit. `overclaim_lint.py` emits WARN, never BLOCK; exit code is 0 (no hits) or 1 (WARN), never 2.
- No LLM-reviewer score, no accept/reject verdict, no numeric quality gate.
- **Dogfood:** no em-dash (U+2014) or en-dash (U+2013) in any SKILL.md or reference `.md` prose. `test_skill_loads.py::test_em_dash_absolute_ban_dogfooded` enforces it for SKILL.md.
- SKILL.md must stay within 200-700 lines (`test_skill_md_within_line_budget`).
- Every `references/*.md` named in SKILL.md must exist (`test_supplementary_references_all_discoverable`).
- Skill frontmatter version bumps `2.4.0 -> 2.5.0` (content version, local to the skill; distinct from the RKA release version).
- After edits: mirror to `plugin/skills/writer/` and keep `tests/test_skills_packaging.py` (parity + package-data coverage) green.
- Entity-id shape for tests: `(jrn|dec|lit|mis|clm|ecl)_` + 26 chars of `[0-9A-Z]` (per `verify_provenance.py` `_ID_RE`). Use `jrn_01KS0AVZRDA0KPXK61MN9PV5DE`.

---

### Task 1: `overclaim_lint.py` — lexical detector + report + CLI

**Files:**
- Create: `rka/skills/writer/scripts/overclaim_lint.py`
- Modify: `tests/skills/writer/conftest.py` (add `overclaim_lint` fixture)
- Test: `tests/skills/writer/test_overclaim_lint.py`

**Interfaces:**
- Produces: `lint_file(path, *, resolver=None, config=None) -> OverclaimReport`; `main(argv=None) -> int`; dataclasses `OverclaimHit(term, category, file, line, sentence, severity="WARN", priority="normal", backing_entity=None, backing_confidence=None)` and `OverclaimReport(hits: list, verdict: str)`. `resolver` is consumed by Task 2.

- [ ] **Step 1: Add the conftest fixture**

Add to `tests/skills/writer/conftest.py` after the `verify_citations` fixture (around line 68):

```python
@pytest.fixture
def overclaim_lint():
    return _load_module("overclaim_lint")
```

- [ ] **Step 2: Write the failing tests**

Create `tests/skills/writer/test_overclaim_lint.py`:

```python
"""Tests for overclaim_lint.py (advisory calibration/overclaim linter).

WARN-only: this linter never BLOCKs. It surfaces absolute/overclaim wording
for the pre-submission review, and (Task 2) ranks a hit higher when the
backing RKA evidence is weak-confidence.
"""

from __future__ import annotations

import json
from pathlib import Path


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


class TestLexicalDetection:
    def test_flags_guarantee_word(self, overclaim_lint, tmp_path: Path) -> None:
        f = _write(tmp_path, "s.tex", "Our system guarantees no data leakage.")
        rep = overclaim_lint.lint_file(f)
        assert any(h.term.lower() == "guarantees" for h in rep.hits)
        assert rep.verdict == "WARN"

    def test_flags_multiple_categories(self, overclaim_lint, tmp_path: Path) -> None:
        f = _write(tmp_path, "s.tex", "It eliminates the attack and is model-agnostic.")
        rep = overclaim_lint.lint_file(f)
        cats = {h.category for h in rep.hits}
        assert "elimination" in cats and "generality" in cats

    def test_clean_prose_passes(self, overclaim_lint, tmp_path: Path) -> None:
        f = _write(
            tmp_path, "s.tex",
            "We observe a 12 percent reduction on the controlled benchmark. "
            "The external benchmark shows a smaller, mixed effect."
        )
        rep = overclaim_lint.lint_file(f)
        assert rep.verdict == "PASS"
        assert not rep.hits


class TestNeverBlocks:
    def test_never_blocks_even_on_many_hits(self, overclaim_lint, tmp_path: Path) -> None:
        f = _write(
            tmp_path, "s.tex",
            "verified guaranteed eliminates model-agnostic dominant fundamental"
        )
        rep = overclaim_lint.lint_file(f)
        assert rep.verdict == "WARN"
        assert rep.verdict != "BLOCK"


class TestPerProjectOverride:
    def test_config_disable_drops_term(self, overclaim_lint, tmp_path: Path) -> None:
        f = _write(tmp_path, "s.tex", "The evaluation is complete.")
        cfg = {"complete": {"verdict": "disable"}}
        assert any("complete" in h.term.lower() for h in overclaim_lint.lint_file(f).hits)
        assert not overclaim_lint.lint_file(f, config=cfg).hits


class TestEntryPoint:
    def test_main_writes_report_and_returns_warn_code(self, overclaim_lint, tmp_path: Path) -> None:
        f = _write(tmp_path, "s.tex", "Our approach eliminates the attack surface.")
        out = tmp_path / "r.json"
        rc = overclaim_lint.main([str(f), "--output", str(out)])
        assert rc == 1
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["verdict"] == "WARN"

    def test_main_returns_zero_on_clean_file(self, overclaim_lint, tmp_path: Path) -> None:
        f = _write(tmp_path, "s.tex", "We report a partial improvement on one benchmark.")
        rc = overclaim_lint.main([str(f), "--output", str(tmp_path / "r.json")])
        assert rc == 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `RKA_DATA_DIR=/private/tmp/rka-test-data .venv/bin/python -m pytest tests/skills/writer/test_overclaim_lint.py -q`
Expected: FAIL (module `overclaim_lint` not found by the fixture loader).

- [ ] **Step 4: Write the implementation**

Create `rka/skills/writer/scripts/overclaim_lint.py`:

```python
#!/usr/bin/env python3
"""overclaim_lint.py: advisory calibration/overclaim detector for the Writer skill.

Advisory-only (WARN, never BLOCK) per the 2026-07-06 Review and Revision design.
Flags absolute/overclaim wording ("verified", "guaranteed", "eliminates",
"model-agnostic", ...) so the pre-submission review
(references/manuscript_review.md) can surface claim-calibration gaps. Mirrors
ai_tic_lint.py's CLI and report shape.

RKA-confidence ranking (Task 2): when a `% provenance:` comment precedes the
overclaiming line, an injected `resolver(entity_id) -> dict|None` is consulted;
a claim backed by hypothesis/tested (not verified) evidence is ranked
priority="high". No live RKA call is made when no resolver is given.

CLI:
    python overclaim_lint.py <files>...
    python overclaim_lint.py --config /path/to/overclaim_config.yaml <files>...
    python overclaim_lint.py --output report.json <files>...

Exit codes:
    0: no hits (PASS)
    1: WARN hits present
Never returns 2. This linter does not BLOCK.

See references/manuscript_review.md for how the review consumes this report.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Optional

# Calibration / overclaim terms -> category. Authored from the PI manuscript
# revision prompt template (2026-07-06); extensible per-project via a config
# mapping {term: {"verdict": "disable"}} (mirrors ai_tic_config.yaml).
OVERCLAIM_PATTERNS: dict[str, str] = {
    r"\bverified\b": "guarantee",
    r"\bguarantees?\b": "guarantee",
    r"\bguaranteed\b": "guarantee",
    r"\bprovably\b": "guarantee",
    r"\bcompletely\b": "completeness",
    r"\beliminates?\b": "elimination",
    r"\beliminated\b": "elimination",
    r"\bmodel-agnostic\b": "generality",
    r"\bfully general\b": "generality",
    r"\bgeneralizes?\b": "generality",
    r"\bdominant\b": "superiority",
    r"\bdominates?\b": "superiority",
    r"\bfundamentally\b": "superiority",
    r"\brobust to adaptive\b": "robustness",
    r"\bfull recall\b": "metric-absolute",
    r"\bno false positives?\b": "metric-absolute",
    r"\bzero false positives?\b": "metric-absolute",
    r"\bnever fails?\b": "absolute",
}

_PROV_RE = re.compile(r"^\s*%\s*provenance:\s*(.+)$", re.IGNORECASE)
_ID_RE = re.compile(r"(jrn|dec|lit|mis|clm|ecl)_[0-9A-Z]{26}")
# Backing confidences that make an absolute claim a high-priority gap.
_WEAK_CONFIDENCE = {"hypothesis", "tested"}
_PROV_WINDOW = 4  # lines to look back for a governing provenance comment

Resolver = Callable[[str], Optional[dict]]


@dataclass
class OverclaimHit:
    term: str
    category: str
    file: str
    line: int
    sentence: str
    severity: str = "WARN"
    priority: str = "normal"
    backing_entity: Optional[str] = None
    backing_confidence: Optional[str] = None


@dataclass
class OverclaimReport:
    hits: list = field(default_factory=list)
    verdict: str = "PASS"

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "hits": [asdict(h) for h in self.hits]}


def _nearest_provenance(lines: list, idx: int, resolver: Resolver):
    """Return (entity_id, confidence) for the nearest `% provenance:` comment
    within _PROV_WINDOW lines above `idx`, or (None, None)."""
    lo = max(-1, idx - _PROV_WINDOW - 1)
    for j in range(idx, lo, -1):
        m = _PROV_RE.match(lines[j])
        if m:
            id_match = _ID_RE.search(m.group(1))
            if not id_match:
                return None, None
            ent = id_match.group(0)
            resolved = resolver(ent)
            conf = (resolved or {}).get("confidence")
            return ent, (conf.lower() if isinstance(conf, str) else None)
    return None, None


def lint_file(path, *, resolver: Optional[Resolver] = None,
              config: Optional[dict] = None) -> OverclaimReport:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    disabled = set()
    if config:
        for term, spec in config.items():
            if isinstance(spec, dict) and spec.get("verdict") == "disable":
                disabled.add(term.lower())
    report = OverclaimReport()
    for i, line in enumerate(lines):
        for pat, category in OVERCLAIM_PATTERNS.items():
            for m in re.finditer(pat, line, re.IGNORECASE):
                term = m.group(0)
                if term.lower() in disabled:
                    continue
                hit = OverclaimHit(
                    term=term, category=category, file=str(path),
                    line=i + 1, sentence=line.strip(),
                )
                if resolver is not None:
                    ent, conf = _nearest_provenance(lines, i, resolver)
                    if ent is not None:
                        hit.backing_entity = ent
                        hit.backing_confidence = conf
                        if conf in _WEAK_CONFIDENCE:
                            hit.priority = "high"
                report.hits.append(hit)
    report.verdict = "WARN" if report.hits else "PASS"
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Advisory overclaim/calibration linter (WARN-only)."
    )
    ap.add_argument("files", nargs="+")
    ap.add_argument("--output", help="write JSON report to this path")
    ap.add_argument("--config", help="per-project overclaim_config.yaml")
    args = ap.parse_args(argv)

    config = None
    if args.config:
        import yaml  # optional; only needed with --config
        config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))

    all_hits = []
    verdict = "PASS"
    for f in args.files:
        rep = lint_file(f, config=config)
        all_hits.extend(rep.hits)
        if rep.verdict == "WARN":
            verdict = "WARN"

    out = {"verdict": verdict, "hits": [asdict(h) for h in all_hits]}
    if args.output:
        Path(args.output).write_text(json.dumps(out, indent=2), encoding="utf-8")
    else:
        print(json.dumps(out, indent=2))
    return 1 if verdict == "WARN" else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `RKA_DATA_DIR=/private/tmp/rka-test-data .venv/bin/python -m pytest tests/skills/writer/test_overclaim_lint.py -q`
Expected: PASS (all tests in `TestLexicalDetection`, `TestNeverBlocks`, `TestPerProjectOverride`, `TestEntryPoint`).

- [ ] **Step 6: Make the script executable and commit**

```bash
chmod +x rka/skills/writer/scripts/overclaim_lint.py
git add rka/skills/writer/scripts/overclaim_lint.py tests/skills/writer/conftest.py tests/skills/writer/test_overclaim_lint.py
git commit -m "feat(writer): overclaim_lint.py — advisory calibration linter (WARN-only)"
```

---

### Task 2: `overclaim_lint.py` — RKA-confidence priority ranking

**Files:**
- Modify: `tests/skills/writer/test_overclaim_lint.py` (add `TestConfidenceRanking`)
- Test: same file

**Interfaces:**
- Consumes: `lint_file(path, *, resolver, config)` and `OverclaimHit.priority/backing_entity/backing_confidence` from Task 1. The ranking logic (`_nearest_provenance`, `_WEAK_CONFIDENCE`) already shipped in Task 1's implementation; this task proves it with the resolver-injection tests.

- [ ] **Step 1: Write the failing tests**

Append to `tests/skills/writer/test_overclaim_lint.py`:

```python
_EID = "jrn_01KS0AVZRDA0KPXK61MN9PV5DE"


class TestConfidenceRanking:
    def test_weak_confidence_backing_ranks_high(self, overclaim_lint, tmp_path: Path) -> None:
        content = (
            f"% provenance: {_EID} supports paragraph below\n"
            "Our method guarantees correctness.\n"
        )
        f = _write(tmp_path, "s.tex", content)
        rep = overclaim_lint.lint_file(f, resolver=lambda eid: {"confidence": "tested"})
        hit = next(h for h in rep.hits if h.term.lower() == "guarantees")
        assert hit.priority == "high"
        assert hit.backing_entity == _EID
        assert hit.backing_confidence == "tested"

    def test_verified_confidence_backing_stays_normal(self, overclaim_lint, tmp_path: Path) -> None:
        content = (
            f"% provenance: {_EID} supports paragraph below\n"
            "Our method guarantees correctness.\n"
        )
        f = _write(tmp_path, "s.tex", content)
        rep = overclaim_lint.lint_file(f, resolver=lambda eid: {"confidence": "verified"})
        hit = next(h for h in rep.hits if h.term.lower() == "guarantees")
        assert hit.priority == "normal"

    def test_no_provenance_comment_skips_resolver(self, overclaim_lint, tmp_path: Path) -> None:
        f = _write(tmp_path, "s.tex", "Our method guarantees correctness.")
        called = []

        def resolver(eid):
            called.append(eid)
            return {"confidence": "tested"}

        rep = overclaim_lint.lint_file(f, resolver=resolver)
        hit = next(h for h in rep.hits if h.term.lower() == "guarantees")
        assert hit.priority == "normal"
        assert called == []
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `RKA_DATA_DIR=/private/tmp/rka-test-data .venv/bin/python -m pytest tests/skills/writer/test_overclaim_lint.py::TestConfidenceRanking -q`
Expected: PASS (the ranking logic from Task 1 satisfies these; if any fail, fix `_nearest_provenance`/`lint_file` in the script, not the tests).

- [ ] **Step 3: Commit**

```bash
git add tests/skills/writer/test_overclaim_lint.py
git commit -m "test(writer): overclaim_lint RKA-confidence priority ranking"
```

---

### Task 3: `references/manuscript_review.md` (Prompt 1 reviewer checklist)

**Files:**
- Create: `rka/skills/writer/references/manuscript_review.md`

**Interfaces:**
- Produces: a reference file SKILL.md will link (Task 5). No code contract.

- [ ] **Step 1: Write the reference doc**

Create `rka/skills/writer/references/manuscript_review.md` with this exact structure. It is a PI-facing checklist, not an autograder; open with that framing, then the 15 dimensions. Use no em/en dashes. Required concrete elements per section:

- Title `# Pre-Submission Manuscript Review (advisory)` and a first paragraph stating: this is a PI-facing gap surfacer, it never gates compile or submit, and the only blocking gates remain `verify_provenance.py` / `verify_citations.py` / `layout_audit.py` and the reference-validation statuses. Cross-link `quality_review.md` as the complementary RKA-evidence rubric.
- `## 0. Source, venue, and evidence discipline` — state assumptions (venue family from `venue/<venue>.md`, paper type, strongest evidence, most fragile evidence); the strict evidence rule (a claim is not safe because it sounds plausible; check manuscript support); point to exact sections/figures/tables.
- `## 1. Overall assessment and top reviewer-facing risks` — central-story clarity, title/abstract/intro/contribution/results alignment, submission-vs-tech-report read, calibration, strongest-evidence placement, top 3 to 5 reviewer risks.
- `## 2. Claim-calibration table` — a Markdown table `| Claim | Problem | Safer wording |`; then the calibration word list (verified, guaranteed, complete, eliminates, model-agnostic, dominant, fundamental, robust to adaptive adversaries, generalizes across benchmarks, full recall, no false positives); state the RKA-confidence hook and that `scripts/overclaim_lint.py` surfaces these mechanically (WARN-only, priority=high when backing is hypothesis/tested).
- `## 3. Abstract review` — first-sentence problem, motivation specificity, arithmetic/ratio correctness, strongest-evidence centrality, honest mixed/preliminary framing, no cherry-picking; ends with "provide remaining problems + a revised abstract draft."
- `## 4. Introduction review` — motivation, gap statement fair to prior work, key-insight clarity, results paragraph matches evaluation, contribution list is not a second abstract.
- `## 5. Structure and organization` — logical order; background / threat model / design / implementation / evaluation / discussion / related work / limitations separated; limitations early enough; roadmap clarity; movement suggestions.
- `## 6. Evaluation-presentation credibility` — denominators explained, arithmetic checked, controlled-vs-external-vs-model-specific-vs-ablation-vs-preliminary separated, trial counts verifiable, outcome categories separated from defense mechanisms, statistics not overstating independence, per-benchmark limitations stated; the hook that every number should trace to a `mis_` report or `jrn_`/`clm_` result.
- `## 7. Figures, tables, and layout` — caption/denominator clarity, two-column readability, no hidden mixed results, appendix candidates; note this complements (does not duplicate) `layout_audit.py`.
- `## 8. Terminology normalization` — table `| Current variants | Recommended term | Notes |` across system name, threat-model terms, metric/model/benchmark names, section/figure/table references.
- `## 9. Writing style` — defer to `ai_tic_lint.py` + `bridge_repetition_check.py`; add only the reviewer-perception framing, no second lexical list.
- `## 10. Reference and citation integrity` — credibility lens; defer mechanical checks to `verify_provenance.py` / `verify_citations.py` and the reference pipeline; never invent citations, name the source kind needed.
- `## 11. Venue fit` — read `venue/<venue>.md` (tone, required sections, forbidden constructions).
- `## 12. Reviewer-risk analysis` — table `| Criticism | Why raised | Severity | How to preempt | Suggested wording |`.
- `## 13. Concrete rewrite package` — revised title options, abstract, key-insight paragraph, contribution list, limitation paragraph, evaluation-roadmap paragraph, related-work positioning.
- `## 14. Systems, security, and AI-agent add-on (venue-conditional)` — threat-model vs attack-taxonomy consistency, direct vs indirect attack separation, design-guarantee vs implementation-heuristic distinction, conditional formal properties, baseline fairness (policy-only / filtering-only / taint-only / full-system), CIA + usability claims each backed by the right evidence.
- `## Output` — write `.planning/REVIEW.md`: one table per dimension plus an explicit Gaps list drawn from the mechanical inputs and RKA evidence. State plainly: no numeric score, no accept/reject verdict.
- `## Fast pass` — the top-10-issues mode runs sections 1, 2, 6, 7, 8, 12 only.
- `## Anti-patterns` — DON'T compute an accept/reject or numeric quality score; DON'T treat this as a gate; DON'T assert a review claim without pointing at the manuscript location or RKA evidence.

- [ ] **Step 2: Verify no em/en dashes**

Run: `python3 -c "t=open('rka/skills/writer/references/manuscript_review.md',encoding='utf-8').read(); assert chr(0x2014) not in t and chr(0x2013) not in t, 'dash found'; print('clean')"`
Expected: `clean`

- [ ] **Step 3: Commit**

```bash
git add rka/skills/writer/references/manuscript_review.md
git commit -m "docs(writer): manuscript_review.md — advisory pre-submission review checklist"
```

---

### Task 4: `references/revision_check.md` (Prompt 2 old-vs-new)

**Files:**
- Create: `rka/skills/writer/references/revision_check.md`

**Interfaces:**
- Produces: a reference file SKILL.md will link (Task 5).

- [ ] **Step 1: Write the reference doc**

Create `rka/skills/writer/references/revision_check.md`. No em/en dashes. Structure:

- Title `# Revision Check (old vs new, advisory)` and a first paragraph: this compares a revised draft against prior review comments and is advisory input to the Revision Loop, not a gate.
- `## 0. Comparison setup` — identify old vs new draft; the prior-comments baseline source (the spawning `writer-review`/`writer-revision` mission `context`, the prior `.planning/REVIEW.md`, or PI-supplied comments); classify the run as full / new-only-guided-by-prior / limited.
- `## 1. Executive revision diagnosis` — better / somewhat better / unchanged / worse; most successful revisions; remaining problems; regressions; an advisory readiness judgment (minor-edit / focused-revision / major-restructure / not-ready), explicitly framed as advice not a gate.
- `## 2. Revision-status tracker` — table `| Prior issue | Status | Evidence in new draft | Remaining problem | Recommended next edit |`; status vocabulary exactly: Fixed, Mostly fixed, Partially fixed, Not fixed, Regressed, New issue, Cannot verify. Track the same dimensions as `manuscript_review.md`.
- `## 3. Per-dimension re-checks` — abstract, title/contribution alignment, claim calibration (re-run `overclaim_lint.py` and diff), intro story, evaluation, figures/tables, terminology, style (diff `ai_tic_lint.py`), citations; each compared against the prior issue.
- `## 4. Revision-comment classification` — map each remaining issue to R1-R4 (`handle_factual_r1`, `handle_style_r2`, `handle_inconsistency_r3`, `handle_logical_r4` in `scripts/revision_handler.py`) so the existing Revision Loop applies; note `bridge_repetition_check.py` for cross-section diffs and the `REVIEW_STATE.md` iteration cap of 3.
- `## 5. Remaining reviewer risks and action plan` — must-fix vs optional lists; exact wording to add/soften/move.
- `## Output` — write `.planning/REVISION_CHECK.md` (the tracker). No numeric score.
- `## Anti-patterns` — DON'T re-litigate a Fixed item; DON'T gate on the diagnosis; DON'T mark Cannot-verify items as Fixed.

- [ ] **Step 2: Verify no em/en dashes**

Run: `python3 -c "t=open('rka/skills/writer/references/revision_check.md',encoding='utf-8').read(); assert chr(0x2014) not in t and chr(0x2013) not in t; print('clean')"`
Expected: `clean`

- [ ] **Step 3: Commit**

```bash
git add rka/skills/writer/references/revision_check.md
git commit -m "docs(writer): revision_check.md — old-vs-new revision tracker"
```

---

### Task 5: SKILL.md wiring + `test_skill_loads.py` update

**Files:**
- Modify: `rka/skills/writer/SKILL.md`
- Modify: `tests/skills/writer/test_skill_loads.py`

**Interfaces:**
- Consumes: `references/manuscript_review.md` (Task 3), `references/revision_check.md` (Task 4), `scripts/overclaim_lint.py` (Task 1).

- [ ] **Step 1: Update the section-list + version test FIRST (failing)**

In `tests/skills/writer/test_skill_loads.py`: bump the version assertion and insert the new section into `EXPECTED_SECTIONS`.

Change line 43 from:
```python
    assert re.search(r"^version:\s*2\.4\.0\s*$", fm, re.MULTILINE)
```
to:
```python
    assert re.search(r"^version:\s*2\.5\.0\s*$", fm, re.MULTILINE)
```

In `EXPECTED_SECTIONS`, insert `"## Pre-Submission Review"` immediately before `"## Revision Loop"` (the review pass is advisory input that precedes revision), so the list reads `..., "## Local Rendering", "## Pre-Submission Review", "## Revision Loop", "## Anti-Patterns", "## Related"`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `RKA_DATA_DIR=/private/tmp/rka-test-data .venv/bin/python -m pytest tests/skills/writer/test_skill_loads.py -q`
Expected: FAIL (SKILL.md still `2.4.0`; `## Pre-Submission Review` section missing).

- [ ] **Step 3: Edit SKILL.md**

Make these edits to `rka/skills/writer/SKILL.md`:

1. Frontmatter: `version: 2.4.0` -> `version: 2.5.0`.

2. In `## Supplementary references (load on demand)`, add two bullets:
```markdown
- [`references/manuscript_review.md`](references/manuscript_review.md): advisory pre-submission reviewer checklist (claim calibration, reviewer-risk, evaluation credibility, terminology, venue fit, systems/security add-on). PI-facing gap surfacer, never a gate.
- [`references/revision_check.md`](references/revision_check.md): old-vs-new revision-status tracker (Fixed / Partial / Not fixed / Regressed), feeding the R1-R4 handlers.
```

3. In the `## Tool Surface` Scripts list, add:
```markdown
`overclaim_lint.py` scans drafts for calibration/overclaim wording ("verified", "guaranteed", "eliminates", "model-agnostic", ...) and emits `overclaim_report.json`. WARN-only, never BLOCK; ranks a hit higher when its backing `jrn_`/`clm_` is at `hypothesis`/`tested` confidence. Advisory input to the pre-submission review.
```

4. Add a new section `## Pre-Submission Review` immediately before `## Revision Loop`:
```markdown
## Pre-Submission Review

Before the Final Layout checkpoint (or on demand), run an advisory reviewer-lens
pass over the draft. It is a PI-facing gap surfacer, not a gate and not a score:
it never blocks compile or submit. Only the mechanical gates block
(`verify_provenance.py`, `verify_citations.py`, `layout_audit.py`, the
reference-validation statuses).

Two entry modes (mirroring the fresh-start vs. midpoint pattern):

- **Fresh review**: run the full checklist in [`references/manuscript_review.md`](references/manuscript_review.md) and write `.planning/REVIEW.md`.
- **Midpoint re-entry**: resume from an existing `.planning/REVIEW.md`, re-checking only the dimensions whose sections changed.

Mechanical inputs the review aggregates (no new LLM judgment): the
`verify_provenance.py` / `verify_citations.py` / `layout_audit.py` reports,
`ai_tic_report.json`, and `overclaim_report.json` (calibration words, ranked by
backing RKA confidence). The claim-calibration and evaluation-credibility
dimensions hook into the same provenance and currency the Iron Law already
enforces.

**Mission-spawned review (Phase 3).** The Brain may commission a review with
`rka_execute(args={"operation": "create_mission", "project_id": "prj_...", "objective": "...", "motivated_by_decision": "dec_...", "tags": ["writer-review", "manuscript:<jrn_id>"]})`.
A fresh subagent runs the checklist and reports via
`rka_execute(args={"operation": "submit_report", ...})`. This parallels the
existing `writer-revision` path (see Session Start path b).

This complements [`references/quality_review.md`](references/quality_review.md):
that reports RKA evidence per rubric dimension; this adds the reviewer-facing
presentation and claim-calibration checks. Neither assigns a score.
```

5. At the end of `## Revision Loop`, add a subsection:
```markdown
### Revision-check (old vs new)

When a revised draft is available, compare it against the prior review comments
(the spawning mission `context`, a prior `.planning/REVIEW.md`, or PI-supplied
comments) and produce a revision-status tracker via
[`references/revision_check.md`](references/revision_check.md). Output is
`.planning/REVISION_CHECK.md`; each remaining issue maps to an R1-R4 class and
routes through the handlers above, capped by `REVIEW_STATE.md` at three
iterations. Advisory only: the readiness diagnosis informs the PI, it does not
gate.
```

6. In `## Anti-Patterns`, add two numbered items (continue the numbering):
```markdown
16. **DON'T** gate on the pre-submission review or the revision-check. Both are advisory: they surface gaps to the PI, and only the mechanical gates (provenance, citations, layout, reference-validation) block.
17. **DON'T** compute or report an accept/reject or numeric quality score. `overclaim_lint.py` is WARN-only; the review writes a gaps list, not a grade (see `quality_review.md` for why LLM-reviewer scores are not gates).
```

7. In `## Related`, add:
```markdown
- Pre-submission reviewer checklist: [`references/manuscript_review.md`](references/manuscript_review.md).
- Revision-status tracker: [`references/revision_check.md`](references/revision_check.md).
```

- [ ] **Step 4: Verify no em/en dashes and run the section test**

Run: `RKA_DATA_DIR=/private/tmp/rka-test-data .venv/bin/python -m pytest tests/skills/writer/test_skill_loads.py -q`
Expected: PASS (frontmatter 2.5.0; new section present in order; all referenced files exist; no dashes; within line budget).

- [ ] **Step 5: Commit**

```bash
git add rka/skills/writer/SKILL.md tests/skills/writer/test_skill_loads.py
git commit -m "feat(writer): wire pre-submission review + revision-check into SKILL.md (v2.5.0)"
```

---

### Task 6: Mirror to plugin, full test, reinstall + refresh cache

**Files:**
- Modify: `plugin/skills/writer/**` (rsync mirror of `rka/skills/writer/`)

**Interfaces:**
- Consumes: everything from Tasks 1-5.

- [ ] **Step 1: Mirror rka/skills/writer -> plugin/skills/writer**

```bash
rsync -rc --exclude='._*' --exclude='__pycache__' --exclude='__init__.py' \
  rka/skills/writer/ plugin/skills/writer/
```

- [ ] **Step 2: Run the writer suite + packaging parity**

Run:
```bash
RKA_DATA_DIR=/private/tmp/rka-test-data .venv/bin/python -m pytest \
  tests/skills/writer/ tests/test_skills_packaging.py -q
```
Expected: PASS (writer suite green; `test_plugin_skills_match_packaged_skills` confirms parity; `test_all_packaged_skill_files_covered_by_package_data` confirms the new script + refs ship).

- [ ] **Step 3: Reinstall the wheel and refresh the plugin cache**

```bash
find . -name '._*' -not -path './.git/*' -delete
rsync -rc --exclude='._*' --exclude='__pycache__' rka/ /tmp/rka-build/rka/ >/dev/null
( cd /tmp/rka-build && find . -name '._*' -not -path './.git/*' -delete \
  && COPYFILE_DISABLE=1 UV_CACHE_DIR=/tmp/uv-cache uv tool install --force --no-cache . ) | tail -2
claude plugin uninstall rka@rka && claude plugin install rka@rka
```
Expected: wheel installs; plugin reinstalls. Confirm the new files ship:
```bash
SP=/Users/ceron/.local/share/uv/tools/rka/lib/python3.11/site-packages/rka/skills/writer
ls "$SP/references/manuscript_review.md" "$SP/references/revision_check.md" "$SP/scripts/overclaim_lint.py"
```
Expected: all three paths listed.

- [ ] **Step 4: Commit the plugin mirror + spec/plan docs**

```bash
git add plugin/skills/writer docs/superpowers/specs/2026-07-06-writer-review-revision-design.md docs/superpowers/plans/2026-07-06-writer-review-revision.md
git commit -m "chore(writer): mirror review/revision skill to plugin + add spec/plan"
```

- [ ] **Step 5: (PI-gated) push**

Do NOT push without explicit PI request (repo discipline). When authorized:
```bash
git push origin main
```

---

## Self-review notes

- **Spec coverage:** manuscript_review.md (Task 3) = spec §2.1; revision_check.md (Task 4) = §2.2; overclaim_lint.py (Tasks 1-2) = §2.3; SKILL.md wiring + edwinhu patterns + anti-patterns + version bump (Task 5) = §2.4; testing = §5 (Tasks 1-2, 6); consistency/rollout = §6 (Task 6). Non-goals (§3) enforced by Global Constraints. All spec sections map to a task.
- **Placeholder scan:** script + test code is complete; doc tasks specify exact headers, tables, and word lists (content is authored prose, structure is fully pinned).
- **Type consistency:** `OverclaimHit`/`OverclaimReport` fields and `lint_file`/`main`/`_nearest_provenance` signatures are identical across Tasks 1-2; `resolver` contract (`entity_id -> dict|None` with `"confidence"`) matches the test doubles and `verify_provenance.py`'s resolver shape.
