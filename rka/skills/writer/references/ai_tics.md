# Anti-AI-tic Enforcement

Load-bearing per `dec_01KS12H9KT1T03DHX2Q6FKTXHH` (PATCH 2 disposition; no third-party content vendored in Phase 1). All banned terms trace to primary published research or PI direction, cited directly with DOI where applicable.

## The empirical anchor

Pure lexical blacklists over-flag legitimate academic prose (Matsui 2025). The Writer's enforcement layer therefore combines a tiered lexical list with structural detectors and a per-project override mechanism. The lexical layer catches the obvious LLM tells; the structural layer catches the rhythmic and bridging patterns that survive lexical sanitization; the override layer respects venue-specific or PI-specific legitimate usage.

Empirical floor for the rules: across six published studies covering 732 LLM-generated citations, cross-study average is 51 percent fabrication (Walters and Wilder 2023, Wagner and Ertl-Wagner 2023, Mugaanyi 2024, Spennemann 2025). Linter discipline is one half of the defense; the other half is the reference validation pipeline (`reference_pipeline.md`). Both must be active.

## Tier 1: CRITICAL (compile-blocking on any hit)

ChatGPT output artifacts and prompt-refusal stems that betray either uncleaned model output or pasted refusal language. Any single hit blocks compile until the line is rewritten.

| Pattern | Origin | Example to avoid |
|---|---|---|
| `turn0search0` (and similar `turn\d+search\d+`) | ChatGPT browsing-tool token | "see results in turn0search0" |
| `oaicite` | OpenAI citation marker | `\textbf{oaicite}` fragments |
| `contentReference` | OpenAI internal reference | `[contentReference]` blocks |
| `attribution` JSON fragments | OpenAI grounding metadata | `{"attribution":...}` in prose |
| "As an AI language model" | refusal stem | "As an AI language model, I cannot..." |
| "I cannot help with that" | refusal stem | inline copy of a model refusal |
| "As of my last knowledge update" | knowledge-cutoff disclaimer | "As of my last knowledge update in..." |

These represent zero false-positive risk in academic prose. There is no per-project override; CRITICAL hits always block.

## Tier 2: HIGH (block by default; override via `ai_tic_config.yaml`)

Lexical patterns with strong frequency-distinguishability between LLM-assisted and pre-2023 academic prose. Three sources contribute:

### Source A: PI verbatim list (`dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D` Q4)

`facilitate`, `delves`, `leverage`, `comprehensive`, `furthermore`, `moreover`, `additionally`, `importantly`, `in conclusion`, `it is important to note`.

PI-authored as part of the Q4 ratification. These are blocked by default across all projects; override is per-project via `ai_tic_config.yaml`.

### Source B: Kobak et al. 2025 (Science Advances 11(27):eadt3813)

Citation: Kobak, D., Gonzalez-Marquez, R., Horvat, E.-A., Lause, J. (2025). "Delving into LLM-assisted writing in biomedical publications through excess vocabulary." *Science Advances* 11(27):eadt3813. doi:10.1126/sciadv.adt3813. Open-access CC-BY.

Methodology: word frequency analysis across 14.4 million PubMed abstracts spanning 2010 through 2024. The paper reports words with the highest frequency ratio between 2024 and pre-2023 baselines (`r >> 1`). The 22 highest-ratio focal words drawn from the published lists:

`delving`, `underscore`, `underscores`, `underscoring`, `showcasing`, `showcase`, `showcases`, `pivotal`, `intricate`, `intricately`, `meticulous`, `meticulously`, `realm`, `aligns`, `aligning`, `underpins`, `garnered`, `bolstering`, `notably`, `surpass`, `intricacies`, `unwavering`.

Reading: at least 13.5 percent of 2024 PubMed abstracts show LLM fingerprints; the proportion reaches 40 percent in some subcorpora. These frequencies are empirical findings, not creative content; citing them as factual signal does not require licensing the source.

### Source C: Matsui 2025 (Perspectives on Medical Education 14(1):882-890)

Citation: Matsui, K. (2025). "Word-frequency surveillance of AI-assisted prose: 103 candidate markers in medical education writing." *Perspectives on Medical Education* 14(1):882-890.

Methodology: 135 candidate terms tested for `Z > 3.5` in 2024 corpus vs pre-2023 baseline. 103 crossed the threshold. The published list contains many terms also flagged by Kobak; the seven terms specific to Matsui's medical-education corpus added to the HIGH tier:

`enhance`, `elevate`, `utilize`, `boast`, `commendable`, `tapestry`, `unlocking`.

Cautionary note from Matsui: stable academic phrases (`further research`, `aim to`) also crossed the `Z>3.5` threshold. This is the empirical anchor for the per-project override mechanism. Domain-specific legitimate usage requires disabling specific blocks via `ai_tic_config.yaml`.

## Tier 3: MEDIUM (warn; do not block)

Structural and stylistic patterns associated with LLM-assisted drafting but with non-trivial overlap with legitimate academic style. Warned, not blocked.

- `However` adjacent to `Nevertheless` in the same paragraph.
- Rule-of-three triplets: `X, Y, and Z` form used three or more times in a single paragraph.
- Elegant variation: same referent named via three different synonyms within five sentences.
- Bolded full sentences (LLM emphasis pattern).
- `Importantly,` as a sentence starter.
- `It should be noted that` as a sentence starter.
- `In summary,` as a paragraph closer.

## Absolute bans (no per-project override)

These are dogfood-level discipline rules and apply project-wide without exception:

- Em-dash characters U+2014 and U+2013 in prose. Use spaces, colons, semicolons, or periods. (LaTeX `---` and `--` ligatures in source are equally banned in Writer output.)
- Bullet density: at most two bulleted lists per section; each list at most five items, at least three.
- Bolded full sentences: forbidden everywhere; bold only for terms or section labels.

## Structural detectors

Lexical rules alone over-flag. The structural layer catches the rhythmic patterns LLMs produce regardless of vocabulary:

1. **Sentence-length variance.** Compute the standard deviation of sentence lengths (in words) per paragraph. Flag any paragraph where the standard deviation drops below 5. Natural human prose has high variance; uniform sentence rhythm is the strongest non-lexical LLM signal.

2. **Transition-word ratio.** Count occurrences of `however`, `nevertheless`, `furthermore`, `moreover`, `additionally`, `consequently`, `thus`, `therefore`, `hence`, `accordingly` across a section. Compare to total word count. Flag if the ratio exceeds 0.5 percent.

3. **Parallel-triplet density.** Detect `X, Y, and Z` constructions. Flag if density exceeds 1 occurrence per 500 words across a section.

4. **Bridge repetition.** `scripts/bridge_repetition_check.py` uses `difflib.SequenceMatcher` at ratio threshold 0.7 to detect near-duplicate sentences across section boundaries (a common LLM failure where the closing thesis of one section is restated as the opening of the next).

## Replacement table

PI-authored replacements for the highest-frequency offenders:

| Banned | Tier | Replacement |
|---|---|---|
| `facilitate`, `facilitates` | HIGH | `supports`, `helps`, or describe the specific mechanism |
| `delves into` | HIGH | `examines`, `analyzes`, `studies` |
| `leverage` | HIGH | `use`, `apply`, or name the specific lever |
| `comprehensive` | HIGH | (delete; be specific about scope) |
| `furthermore`, `moreover` | HIGH | (delete; start a new sentence with the content) |
| `additionally` | HIGH | (delete; the next sentence carries the addition) |
| `importantly` | HIGH | (delete; state the fact directly without claiming its importance) |
| `in conclusion` | HIGH | (delete; end with a concrete claim) |
| `it is important to note` | HIGH | (delete; state the noted fact directly) |
| `stands as a testament to` | HIGH | `shows`, `demonstrates` |
| `plays a pivotal role in` | HIGH | (name the specific effect) |
| `enhance` | HIGH | (be specific about the change: `increases`, `improves accuracy`, `reduces latency`) |
| `utilize` | HIGH | `use` |
| `delving`, `delves` | HIGH | `examining`, `examines` |
| `underscores`, `underpinning` | HIGH | `shows`, `supports` |

## Style score

Per section:

```
critical_hits = count of CRITICAL pattern matches
high_hits     = count of HIGH pattern matches
medium_hits   = count of MEDIUM pattern matches
total_sentences = number of sentences in the section

score = 1 - (critical_hits * 3 + high_hits + 0.3 * medium_hits) / total_sentences
```

Threshold: sections with `score < 0.85` trigger auto-revise via the Revision Loop (Class R2). The auto-revise loop caps at three iterations before escalating to a PI Style checkpoint with three resolution options (continue revising, accept the section as is via PI override, or restructure the section).

The score is one signal among several. PI editorial judgment overrides the score via `ai_tic_config.yaml`. The score is **not** the sole gate. Treating it as such is anti-pattern 10 in `SKILL.md`.

## Per-project override mechanism

Each `manuscripts/<project>/<venue>/ai_tic_config.yaml` maps each banned term to one of three verdicts plus a free-text rationale:

```yaml
# Manuscript-specific anti-AI-tic overrides.
# Default behavior at top: HIGH-tier blocks by default; this file overrides per-term.

facilitate:
  verdict: disable
  rationale: "Used in the medical sense (catheter facilitates drainage); domain-legitimate."

elevate:
  verdict: downgrade  # downgrade to MEDIUM (warn instead of block)
  rationale: "Used technically (signal elevation); not promotional."

enhance:
  verdict: enable  # default behavior; redundant but explicit
  rationale: ""

# Project-specific additions (terms PI wants flagged beyond the default list):
custom_blocks:
  - term: "robust"
    tier: HIGH
    rationale: "PI dislikes generic claims of robustness; require specific quantification."
```

The linter loads the project's `ai_tic_config.yaml` if present, applies overrides, and records the active override set in `ai_tic_report.json` for traceability. Override decisions should be PI-ratified; for systematic project-wide overrides, the rationale field is appended to a `lit_` or `jrn_` for record.

## Phase 1 implementation status

The linter `scripts/ai_tic_lint.py` implements all Tier 1 + Tier 2 + Tier 3 lexical patterns, the four structural detectors (sentence-length variance, transition-word ratio, parallel-triplet density, bridge-repetition delegation to `bridge_repetition_check.py`), absolute bans, the style score formula, and the per-project override mechanism. Output is `ai_tic_report.json` with per-rule hit counts and per-hit line numbers, plus the computed style score.

Phase 2 additions (not in scope for Phase 1):

- LLM-assisted rewrite suggestions for flagged passages.
- Cross-manuscript trend tracking (is the project drifting toward AI-tic patterns over revisions).
- Author-style fingerprinting baseline (calibrate the linter against the PI's pre-2023 publications).

## References

- Kobak et al. 2025: https://doi.org/10.1126/sciadv.adt3813
- Matsui 2025: Perspectives on Medical Education 14(1):882-890.
- Walters and Wilder 2023: Scientific Reports doi:10.1038/s41598-023-41032-5.
- PI verbatim list: `dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D` Q4 ratification.
- Anti-AI-tic sourcing decision: `dec_01KS12H9KT1T03DHX2Q6FKTXHH`.
- Deep research synthesis (skills survey, empirical anchors): `jrn_01KS0AVZRDA0KPXK61MN9PV5DE`.
