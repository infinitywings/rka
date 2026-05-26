# Worked Examples

Two end-to-end examples illustrating the Writer's most distinctive decisions: an outline ratification via the strip-then-re-inject UX, and an AI-tic catch via the linter plus structural detector layer.

## Example 1: Outline ratification

### Scenario

Project: a hypothetical RKA project on contextual integrity in LLM agent permission systems. Six clusters in the research map. CHI is the chosen venue (Venue checkpoint already ratified).

### Step 1: read research map

```python
rka_get_research_map(project_id="prj_01KQ...")
```

Returns six clusters:

- `ecl_01KQA`: contextual-integrity theory roots (Nissenbaum 2004, 2010, etc.).
- `ecl_01KQB`: agent permission-system empirical surveys (12 deployments studied).
- `ecl_01KQC`: user-study findings on permission fatigue.
- `ecl_01KQD`: technical architecture proposals from prior work.
- `ecl_01KQE`: the project's own pilot study findings (mixed methods, n=24).
- `ecl_01KQF`: design implications and an enumerated framework.

### Step 2: generate three framings (PI preference stripped)

**Results-led**: lead with the pilot study finding ("permission fatigue scales with agent capability"); use Related Work to position; Discussion ties to broader theory.

- Sections: Intro, Related Work (CI theory + prior empirical), Method (pilot study design), Findings (the empirical claim plus supporting evidence), Discussion + Implications, Conclusion.
- Strength: novelty foregrounded; readers grasp the contribution by page 2.
- Weakness: a CHI audience may need more theoretical scaffolding before the empirical finding lands; risks reading as a single-study paper without enough framework.

**Method-led**: lead with the methodological contribution (a new diary-study protocol for measuring permission fatigue across agent classes).

- Sections: Intro, Related Work, Methodological Contribution (the diary protocol), Pilot Application (study), Findings, Discussion, Conclusion.
- Strength: methods-focused readers (and PC members with methodological taste) find the contribution immediately.
- Weakness: empirical findings come later; reader patience required; risks reading as a methods-only paper.

**Motivation-led**: lead with the broader problem (LLM agent permission systems are at scale without empirical grounding); position the work as the first empirical study.

- Sections: Intro (problem framing + scale), Background (CI theory + agent landscape), Pilot Study (method + findings combined), Framework (the enumerated implications), Discussion, Conclusion.
- Strength: positions the work for impact; CHI reviewers like clear problem framing.
- Weakness: contribution claims must be sharp in the Intro or the reader loses the through-line.

### Step 3: prune via Pareto non-dominance

Axes: scope coverage (does the structure represent the full research arc?), novelty positioning (does the structure communicate the contribution?), venue fit (does it match CHI's expectations?).

- Results-led: high novelty positioning, moderate scope coverage (theoretical scaffold thinner), moderate venue fit.
- Method-led: high venue fit (CHI likes methods contributions), moderate novelty positioning, high scope coverage.
- Motivation-led: high scope coverage, high venue fit, moderate novelty positioning.

None dominated; all three survive pruning.

### Step 4: rank with opposing-critique

PI preference re-injected as a critic: the PI is a methods-oriented researcher who has emphasized in past sessions that "CHI welcomes empirical methodological contributions." Use this as opposing-critique:

- Method-led ranked first: directly aligns with PI's methodological emphasis.
- Motivation-led ranked second: also fits CHI; broader framing.
- Results-led ranked third: novelty-foregrounded but may feel single-study at CHI.

Mark Method-led as `is_recommended`.

### Step 5: PI selects

```python
rka_add_decision(
    project_id="prj_01KQ...",
    question="Which outline framing for the CHI manuscript?",
    options=[
        {"label": "Method-led", "is_recommended": True, "description": "Lead with diary protocol contribution.", ...},
        {"label": "Motivation-led", "description": "Lead with permission-system problem framing.", ...},
        {"label": "Results-led", "description": "Lead with permission-fatigue empirical finding.", ...},
    ],
    rationale="Methodological contribution emphasis aligns with PI's prior CHI guidance (jrn_01KQ...) and venue fit.",
    related_journal=["jrn_01KQ..."],
    decided_by="pi",
    status="active",
)

# PI selects (assume Method-led):
rka_record_pi_selection(
    decision_id="dec_<the new one>",
    pi_selected_option_id="Method-led",
    pi_override_rationale=None,
)
```

### Step 6: write OUTLINE.md

```markdown
# OUTLINE: CHI Manuscript (Method-led framing)

Ratified 2026-05-19 via dec_01KQ... (PI selected Method-led).

## §1 Introduction
- Problem: LLM agent permission systems at scale; empirical methods limited.
- Contribution claim: a diary-study protocol that surfaces permission fatigue across agent classes.
- Result preview: protocol applied; key findings.

## §2 Related Work
- Contextual integrity theory (Nissenbaum 2004, 2010, extensions).
- Prior permission-system empirical work.
- Prior diary-study protocols in HCI.

## §3 Methodological Contribution
- The diary protocol: design rationale, instrument, sampling.
- What it measures; why prior methods underdetermined it.

## §4 Pilot Application
- Participants (n=24, mixed-methods sample).
- Procedure.
- Analysis approach.

## §5 Findings
- Quantitative findings from the diary instrument.
- Qualitative themes from open-ended responses.
- Triangulation across the two streams.

## §6 Discussion
- Implications for permission-system design.
- Methodological reflections (what worked, what did not).

## §7 Limitations (top-level, per CHI 2024+ convention)
- Sample size and composition.
- Diary-study attrition.
- Reflexivity and positionality.

## §8 Conclusion
- Restate contribution.
- Future work pointers.
```

This OUTLINE.md becomes the input to the Table-Figure-Chart Plan checkpoint, and subsequently to per-section drafting.

## Example 2: AI-tic catch

### Scenario

A draft section was just produced by the Section Drafter sub-procedure. Before the Draft section PI checkpoint surfaces, `scripts/ai_tic_lint.py` runs as a self-audit.

### The draft (excerpt)

```latex
% sections/03-method.tex (excerpt)

Our methodology delves into the intricate dynamics of permission-fatigue, leveraging a comprehensive diary-study protocol that facilitates participant self-reporting. We propose a novel instrument that meticulously captures both frequency and intensity of permission grants. Furthermore, the protocol underpins a robust analytical framework that aligns with prior HCI scholarship.

It is important to note that our approach showcases significant methodological innovation. Importantly, the diary instrument plays a pivotal role in surfacing latent user perceptions that traditional survey methods cannot adequately capture.
```

### Linter output (`ai_tic_report.json`)

```json
{
  "section": "sections/03-method.tex",
  "lines": 7,
  "total_sentences": 5,
  "hits": {
    "critical": [],
    "high": [
      {"term": "delves into", "line": 4, "tier": "HIGH", "source": "PI verbatim list"},
      {"term": "intricate", "line": 4, "tier": "HIGH", "source": "Kobak 2025"},
      {"term": "leveraging", "line": 4, "tier": "HIGH", "source": "PI verbatim list"},
      {"term": "comprehensive", "line": 4, "tier": "HIGH", "source": "PI verbatim list"},
      {"term": "facilitates", "line": 4, "tier": "HIGH", "source": "PI verbatim list"},
      {"term": "meticulously", "line": 4, "tier": "HIGH", "source": "Kobak 2025"},
      {"term": "Furthermore", "line": 4, "tier": "HIGH", "source": "PI verbatim list"},
      {"term": "underpins", "line": 4, "tier": "HIGH", "source": "Kobak 2025"},
      {"term": "aligns", "line": 4, "tier": "HIGH", "source": "Kobak 2025"},
      {"term": "it is important to note", "line": 6, "tier": "HIGH", "source": "PI verbatim list"},
      {"term": "showcases", "line": 6, "tier": "HIGH", "source": "Kobak 2025"},
      {"term": "Importantly", "line": 6, "tier": "HIGH", "source": "PI verbatim list"},
      {"term": "pivotal", "line": 6, "tier": "HIGH", "source": "Kobak 2025"}
    ],
    "medium": [
      {"pattern": "rule-of-three triplet", "line": 4, "tier": "MEDIUM", "description": "X, Y, and Z constructions detected three times in paragraph 1"}
    ],
    "absolute_bans": []
  },
  "structural": {
    "sentence_length_variance": {"paragraph_1_std": 4.2, "verdict": "BLOCK", "threshold": 5.0},
    "transition_word_ratio": {"value": 0.012, "verdict": "WARN", "threshold": 0.005},
    "parallel_triplet_density": {"value": 1.5, "verdict": "WARN", "threshold": 1.0},
    "bridge_repetition": {"max_ratio": 0.34, "verdict": "PASS", "threshold": 0.7}
  },
  "style_score": 1 - (0 * 3 + 13 + 0.3 * 1) / 5,
  "actual_score": -1.66,
  "verdict": "BLOCK"
}
```

The style score is deeply negative (the formula clips at 0 in practice; this output shows the raw value to emphasize how many HIGH hits cluster in a short passage). The verdict is `BLOCK` from multiple paths: HIGH-tier hits, sentence-length variance under 5, transition-word ratio over 0.5 percent, and parallel-triplet density over 1.

### Auto-revise iteration

The Section Drafter sub-procedure picks up the linter report and rewrites the section. Iteration 1 result:

```latex
Our method uses a diary protocol to measure permission fatigue. The instrument records both frequency and intensity of permission grants from participants. The analytical framework draws on prior HCI scholarship on user-system interactions.

The diary instrument surfaces user perceptions that survey methods do not capture. Specifically, it records the temporal patterns of permission decisions and the cognitive context in which each decision occurs.
```

### Iteration 1 linter output

```json
{
  "section": "sections/03-method.tex",
  "hits": {
    "critical": [],
    "high": [],
    "medium": [],
    "absolute_bans": []
  },
  "structural": {
    "sentence_length_variance": {"paragraph_1_std": 7.4, "verdict": "PASS", "threshold": 5.0},
    "transition_word_ratio": {"value": 0.0, "verdict": "PASS", "threshold": 0.005},
    "parallel_triplet_density": {"value": 0.0, "verdict": "PASS", "threshold": 1.0},
    "bridge_repetition": {"max_ratio": 0.18, "verdict": "PASS", "threshold": 0.7}
  },
  "style_score": 1.0,
  "verdict": "PASS"
}
```

The revised section passes all gates. Style score 1.0 (no hits). The provenance comments (omitted from the excerpt above) remain attached to evidence-bearing claims.

### What this example shows

The auto-revise loop's first iteration was sufficient. The original draft was heavily HIGH-tier; rewriting from scratch with the linter's hit list as a checklist produces clean prose. If iteration 1 had still failed (e.g., the rewriter substituted equivalent HIGH-tier terms), iteration 2 would have engaged. The three-iteration cap exists because some sections may surface domain-specific legitimate usage that requires `ai_tic_config.yaml` overrides rather than rewriting.

The structural detectors caught the rhythmic problem (uniform sentence length, parallel-triplet density). Pure lexical checks alone would not have surfaced this even after the lexical issues were cleaned.

### Surfacing to PI

If iteration 1 had passed (as it did here), the section advances to the Draft section PI checkpoint. The PI sees a clean draft plus a one-line `ai_tic_report` summary ("0 HIGH, 0 MEDIUM, all structural checks PASS, style score 1.0"). The PI ratifies via accept / revise / escalate per the checkpoint UX.
