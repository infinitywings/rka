# Framing and Spine Elicitation

Use this workflow before the Outline checkpoint when the manuscript framing is
new, disputed, weakly specified, or materially affected by new research. Its
purpose is to help the author and researcher discover a defensible paper spine
without asking them to compose that spine from a blank page.

The Writer proposes bounded choices from current RKA evidence. The people make
the selections. The interaction is deliberative, but the resulting session
artifact is advisory until the PI ratifies exact claim wording and the Outline
checkpoint.

## Authority boundary

- RKA remains authoritative for research records, manuscript claims, evidence
  roles, decisions, ratifications, units, and checkpoints.
- `.planning/FRAMING_SESSION.yaml` is resumable working state. It is not
  evidence, a PI decision, or a substitute for the native claim spine.
- A user selection expresses preference or intent. It does not verify an
  empirical claim or resolve a contradiction.
- Only an explicit final PI selection may be recorded as a decision. Exact
  contribution wording still requires claim-scope ratification.
- Keep author intent and researcher evidence judgment distinct even when the
  same person supplies both.

## Choice-first interaction contract

Default to structured choices for framing and spine work.

1. Ask one decision per turn.
2. Offer two to four evidence-bounded options. Use fewer than three when the
   evidence does not support three genuine alternatives.
3. State whether the decision is `single-select` or `multi-select`. For a
   multi-select question, state the maximum number of selections when a limit
   is useful.
4. Give every option a short ID and label, followed by:
   - what the option means;
   - concrete pros;
   - concrete cons or tradeoffs;
   - the strongest supporting RKA evidence;
   - missing evidence or material risk;
   - how the option changes the claim, audience, or outline.
5. Mark one option `Recommended` when the evidence supports a recommendation.
   Explain why. Do not manufacture a recommendation when the alternatives are
   genuinely tied.
6. Include `Revise or combine these options` whenever a hybrid is coherent.
   Include `Defer and gather evidence` when the evidence boundary is the real
   blocker.
7. Use the host's structured choice UI when available. Otherwise present
   numbered or lettered options and ask the user to reply with IDs.
8. After a selection, restate the chosen interpretation in one sentence and
   update the session artifact before asking the next decision.

Do not present a false menu. Options must differ on a material decision axis,
not merely wording. Do not hide a required disclosure, unsupported extension,
or contradiction in an option's fine print.

### Free-text exceptions

Use a focused free-text question only when:

- the user wants an option that the Writer cannot infer;
- exact title, abstract, author order, or claim wording needs correction;
- relevant evidence or context is absent from RKA;
- the author and researcher disagree in a way the proposed reconciliation
  choices do not cover; or
- the user explicitly asks to discuss an issue without a menu.

After receiving free text, summarize it and return to choices. New empirical
information must enter RKA and pass the normal evidence checks before it
supports a manuscript claim.

## Option card

Use this compact shape. Keep each option scannable.

```text
Decision F4 - Primary novelty axis [single-select]

A. Mechanism-first [Recommended]
Meaning: The paper leads with the new control mechanism.
Pros: Clearest technical novelty; strongest match to the verified ablation.
Cons: Requires a concise explanation of the deployment assumptions.
Evidence: clm_... supported by jrn_...
Risk: Cross-platform evidence is currently narrow.
Effect: Method-led claim and outline.

B. Outcome-first
Meaning: The paper leads with the measured operational improvement.
Pros: Fastest reader payoff; strongest headline result.
Cons: Novelty may look incremental without the mechanism explanation.
Evidence: clm_... supported by jrn_...
Risk: Baseline comparability needs a visible defense.
Effect: Results-led claim and outline.

Select A or B, or choose "Revise or combine."
```

For multi-select rounds, give each option independent consequences and ask for
IDs such as `C1, C3`. Never use multi-select when the choices are mutually
exclusive.

## Participant handling

At the first round, identify who is answering:

- `Author voice`: intended audience, desired takeaway, narrative emphasis, and
  terminology.
- `Researcher judgment`: scientific novelty, evidence strength, conditions,
  counterevidence, and defensible scope.
- `PI authority`: final scope, exact claim wording, and checkpoint decisions.

One person may hold all three roles. When different people participate, attach
each selection to its role. If their selections conflict, do not silently
average them. Present two to four reconciliation choices with pros, cons, and
the effect on the paper. Escalate unresolved authority conflicts to the PI.

## Elicitation rounds

Run only the rounds needed for the current manuscript. Resume from the first
unresolved round in `.planning/FRAMING_SESSION.yaml`.

### F0. Session posture

Confirm the participants and the task:

- frame a new paper;
- repair an existing but weak spine;
- reframe for a different venue or audience; or
- revisit a spine after material evidence changed.

This may be a multi-select when more than one purpose applies.

### F1. Reader and outcome

Propose two to four target-reader outcomes, such as:

- understand a new mechanism;
- trust a new empirical finding;
- adopt a practical system or method;
- revise an assumption or threat model.

Mode: usually single-select. Capture secondary audiences separately rather than
merging incompatible primary outcomes.

### F2. Central problem or gap

Propose bounded problem statements based on current literature, research
questions, decisions, and verified claims. For each option show:

- what prior limitation it asserts;
- what evidence supports that characterization;
- what it does not claim about prior work; and
- which venue audience would care.

Mode: single-select, with a hybrid allowed only when the combined gap remains
coherent.

### F3. Contribution portfolio

Propose candidate contributions after `rka writer assist` and evidence
triage. Each candidate must identify:

- contribution type;
- exact provisional wording;
- positive evidence;
- qualifiers and counterevidence;
- tested conditions;
- allowed and prohibited extension;
- likely manuscript unit.

Mode: multi-select. Recommend the smallest coherent set, normally two to four
contributions. Mark decorative, redundant, or unsupported candidates for
defer/remove rather than inflating the list.

### F4. Primary novelty axis

Propose the strongest defensible novelty thesis, for example:

- mechanism or method novelty;
- empirical discovery;
- system integration or operational capability;
- theory, model, or conceptual reframing;
- dataset, benchmark, or measurement contribution.

Mode: single-select. A secondary novelty axis may be selected only when it has
independent evidence and a distinct role.

### F5. Evidence anchor and result priority

Propose which verified results should carry the quick-reader path. Compare
effect size or qualitative importance, evidence quality, baseline fairness,
scope, uncertainty, and venue relevance.

Mode: multi-select, normally one primary result and up to two supporting
results. Do not select a result solely because it is visually impressive.

### F6. Claim calibration

For each candidate contribution, propose bounded wording levels such as:

- strongest wording supported by current evidence;
- narrower wording with lower reviewer risk;
- defer pending an evidence mission.

Mode: single-select per claim. State the tested conditions and prohibited
interpretation for every option. A preference for stronger language cannot
override current evidence.

### F7. Narrative architecture

Generate two to four whole-paper spines. Results-led, method-led, and
motivation-led are defaults, not mandatory labels. Add a hybrid only when it
has a distinct and coherent reading path.

For each candidate spine show:

- one-sentence paper thesis;
- ordered contribution claims;
- primary evidence path;
- five to eight section purposes;
- main reviewer advantage;
- main reviewer risk;
- venue fit;
- what is intentionally not central.

Mode: single-select. Mark one recommendation after opposing-critique review.

### F8. Boundaries and reviewer defense

Use the materiality policy in `persuasive_framing.md`. Propose treatments for
the material assumptions, mixed results, counterevidence, and likely reviewer
attacks:

- lead with an evidence-backed defense;
- state a neutral scope boundary;
- disclose a material limitation;
- repair before submission;
- commission an evidence mission;
- keep internal only when truly M4 or speculative.

Mode: multi-select across independent concerns, then single-select for the
treatment of each concern. An M1/M2 issue cannot be assigned `internal only`.

### F9. Final spine selection

Present the surviving candidate spines side by side. Every candidate must
include exact provisional claims, pros, cons, evidence coverage, missing
evidence, public boundaries, outline effect, and venue fit.

Mode: single-select:

- select one candidate;
- combine named parts of two candidates;
- revise the options;
- defer and gather evidence.

After selection, show the complete proposed contribution contract and outline.
Ask for one explicit final confirmation before dry-running the native spine
import and recording any RKA decision.

## Triage rules

- **Duplicate choices:** merge them and explain the lost distinction.
- **Dominated choices:** prune when another option is at least as strong on
  evidence coverage, scope accuracy, venue fit, and narrative clarity without
  a material disadvantage.
- **Unsupported but interesting choices:** label them hypotheses or evidence
  missions, not contribution claims.
- **Contradicted choices:** present the contradiction and resolution paths.
  Do not recommend strong wording while the contradiction is unresolved.
- **Author/researcher conflict:** present reconciliation options and attach the
  final selection to PI authority.
- **Too many contributions:** propose a coherent core, an optional secondary
  set, and a defer-to-future-work set.
- **No credible spine:** say so and offer evidence-gathering, scope reduction,
  or a different paper objective. Do not fill the menu with weak alternatives.

## Session artifact

`.planning/FRAMING_SESSION.yaml` records:

- session status, purpose, participants, and roles;
- each choice round, mode, options, recommendation, selection, and rationale;
- RKA evidence IDs and unresolved evidence needs;
- author/researcher disagreements and their resolution status;
- candidate spines and the final provisional selection;
- links to resulting PI decisions after ratification.

Append a new round revision instead of silently replacing a prior selection.
The artifact may summarize pros and cons, but it must not contain secrets or
credentials. Synchronizing the native claim spine does not overwrite it.

## Completion criteria

The elicitation stage is complete only when:

1. the primary reader outcome and central problem are selected;
2. the contribution portfolio and novelty axis are selected;
3. every contribution has evidence, conditions, allowed wording, and
   prohibited wording, or is explicitly deferred;
4. the primary results and reviewer-sensitive boundaries are triaged;
5. one coherent candidate spine and outline is provisionally selected;
6. author/researcher disagreements are resolved or escalated;
7. the PI explicitly confirms the complete proposal; and
8. no micro-selection has been misrepresented as evidence or ratification.

Then dry-run `rka writer import-spine`, present the authoritative diff, apply
with an expected revision only after approval, ratify exact claim wording, and
resolve the existing Outline checkpoint.
