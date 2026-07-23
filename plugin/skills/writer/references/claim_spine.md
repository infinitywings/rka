# RKA Claim Spine

The claim spine is the Writer's structured projection of a manuscript argument
onto the live RKA research record. It connects the contribution promised by the
paper to the observations, limitations, PI decisions, and manuscript locations
that make the promise defensible.

The spine does not create a second knowledge base. RKA remains canonical for
research facts, entity status, decision history, and provenance. The YAML file
in the manuscript workspace records how the current manuscript uses those
records. Its Markdown views are generated, read-only explanations of that YAML.

## Non-negotiable invariants

1. **RKA is canonical.** Text in a planning file is not evidence. Every entity
   identifier is resolved against the explicitly selected `project_id`.
2. **Ratification is not proof.** A `dec_` records the PI's chosen wording and
   scope. It cannot serve as empirical evidence for that wording.
3. **Synthesis is not terminal evidence.** An `ecl_` helps discover evidence,
   but an empirical claim must resolve through a grounding-verified,
   scientifically supported `clm_` to its current source record. Legacy
   `verified` records extraction fidelity only; it is never scientific support.
4. **The PI owns claim strength.** The Writer may propose bounded alternatives,
   but only an active PI decision ratifies the exact text. Editing ratified text
   requires a new decision that supersedes the old one.
5. **Currency is checked recursively.** A current-looking `clm_` does not pass
   when its `source_entry_id` is missing, stale, superseded, retracted, outside
   its temporal validity window, or backed by a synthesis awaiting reprocessing.
6. **Results coverage is bidirectional.** Every empirical contribution has a
   result unit, and every major result unit names the contribution it serves.
7. **Generated views are read-only.** Regenerate them from
   `RKA_CLAIM_SPINE.yaml`; never repair a rendered Markdown file by hand.
8. **No paper score or acceptance prediction.** Reports use categorical
   findings and workflow verdicts, not an aggregate quality score, probability
   of acceptance, or accept/reject recommendation.
9. **Failure is fail-closed.** Resolver, parse, or snapshot failures are
   `ERROR`. `ERROR` is never converted to `PASS` and never advances a gate.

## Entity roles

The same entity may be useful during retrieval without being suitable as the
last evidentiary link in a manuscript claim.

| Entity | Claim-spine role | May it prove an empirical manuscript claim? |
|---|---|---|
| `prj_` | Project isolation boundary. Every resolved entity must belong to it. | No |
| manuscript `jrn_` | Journal tagged `manuscript`; manifest for the paper and its checkpoint lineage. | No; neither the manifest nor any manuscript-tagged journal is terminal empirical evidence. |
| research `jrn_` | Terminal record of an experiment, observation, limitation, or scope condition, without the `manuscript` tag. | Yes, through an eligible `clm_` whose `source_entry_id` points to it. |
| `clm_` | Claim-level evidence or qualifier extracted from a source record. | Yes, when grounding-verified, `evidence_status` is `supported` or `partially_supported`, explicitly uncontested, current, in-project, and backed by a current research source. |
| `lit_` | Prior-work fact, comparison, or limitation used in related-work and positioning prose. | It supports literature statements, not a new result produced by this project. |
| `ecl_` | Discovery and synthesis view over claims. | No. Follow it to constituent claims and their sources. |
| `dec_` | PI ratification of exact contribution wording, scope, and manuscript choices. | No. It licenses the wording; it does not establish the result. |
| `mis_` | Mission to obtain missing evidence or revise a manuscript unit. | No. An assigned task is not a completed result. |

For v1 empirical contributions, `evidence_ids`, `qualifier_ids`, and
`counterevidence_ids` name `clm_` records. Each record is checked recursively
through `source_entry_id`. The Writer may use `ecl_` to find those claims, and
the final prose may cite the terminal `jrn_` or an appropriate `lit_`, but the
spine never treats the synthesis label itself as proof.

## V1 schema

The canonical Writer-side file is:

```text
.planning/RKA_CLAIM_SPINE.yaml
```

It uses schema version `rka-claim-spine/v1`:

```yaml
schema_version: rka-claim-spine/v1
project_id: prj_01...
manuscript_id: jrn_01...
generated_at: "2026-07-22T14:00:00Z"
changelog_cursor: evt_01...

claims:
  - claim_id: C1
    text: Under threat models T1 and T2, the method reduces malicious update acceptance.
    claim_type: empirical
    status: ratified
    ratified_by: dec_01...
    evidence_ids:
      - clm_01...
    qualifier_ids:
      - clm_01...
    counterevidence_ids: []
    allowed_wording: The method reduced malicious update acceptance under T1 and T2.
    prohibited_wording:
      - The method eliminates all attacks on every platform.
    manuscript_units:
      - U-ABSTRACT-1
      - U-RESULTS-1

units:
  - unit_id: U-ABSTRACT-1
    kind: abstract
    location: sections/00-abstract.tex
    claim_ids:
      - C1
    evidence_ids:
      - clm_01...

  - unit_id: U-RESULTS-1
    kind: result
    location: sections/04-results.tex#result-t1-t2
    claim_ids:
      - C1
    evidence_ids:
      - clm_01...
    artifact: figures/detection-rate.pdf
    allowed_interpretation: The measured reduction holds for T1 and T2 on the tested platforms.
    prohibited_interpretation: The method is universally attack-proof.

rka_snapshot: null
```

### Top-level fields

| Field | Meaning |
|---|---|
| `schema_version` | Exact parser contract. Unknown versions block rather than being guessed. |
| `project_id` | RKA project boundary used for every resolution. |
| `manuscript_id` | Existing in-project `jrn_` carrying the exact `manuscript` tag. No other entity type or ordinary journal is valid. |
| `generated_at` | UTC time at which the Writer assembled or refreshed the spine. It is not evidence currency by itself. |
| `changelog_cursor` | Last RKA change cursor considered by the Writer. |
| `claims` | Stable manuscript claim identifiers and their evidence, boundaries, and ratification. |
| `units` | Claim-sized manuscript locations, including result and non-result units. |
| `rka_snapshot` | Deterministic dependency snapshot created after validation. It is generated, not hand-edited. |

### Claim fields

- `claim_id` is a stable manuscript-local identifier such as `C1`. It is not an
  RKA entity identifier and must be unique within the spine.
- `text` is the exact wording selected by the PI. For `status: ratified`, it
  must match the active `dec_` selection.
- `claim_type: empirical` identifies a result-backed contribution and is the
  only contribution type supported by schema v1. Every other value blocks.
  Relabeling a claim must never bypass empirical checks.
- `status` is `candidate` while being assembled and `ratified` only after PI
  selection. Only a current ratified claim may advance to substantive drafting.
- `ratified_by` is an active, current, in-project PI `dec_` whose `chosen`
  exactly matches `text` and whose `related_journal` explicitly includes this
  spine's `manuscript_id`. It governs wording and scope but is not included in
  `evidence_ids`.
- `evidence_ids` identifies positive, source-backed support.
- `qualifier_ids` identifies scope conditions, limitations, and negative
  observations that control how the claim is phrased.
- `counterevidence_ids` identifies evidence that challenges the claim. It may
  not be silently omitted or treated as support.
- Every `clm_` in `evidence_ids`, `qualifier_ids`, or `counterevidence_ids`
  independently requires grounding fidelity (`grounding_verified: true`, or
  legacy `verified: true`), `evidence_status: supported|partially_supported`,
  explicit `contradicted: false`, current status, and a current non-manuscript
  terminal research journal. A legacy `verified: true` without an eligible
  `evidence_status` remains grounded but scientifically unassessed and blocks.
- `allowed_wording` is the strongest wording currently licensed by the resolved
  evidence and its conditions. The PI ratifies any material strengthening.
- `prohibited_wording` records tempting extensions that the current evidence
  does not license. It must be explicit for every contribution.
- `manuscript_units` is the dependency list used for targeted invalidation.

### Unit fields

- `unit_id` is stable and unique. Use claim-sized units rather than forcing one
  row per section.
- `kind` describes the unit's manuscript function, for example `abstract`,
  `introduction`, `method`, `result`, `discussion`, `caption`, or `limitation`.
- `location` is the source file and, when useful, a heading or anchor.
- `claim_ids` lists the contribution claims advanced, tested, or bounded by the
  unit.
- `evidence_ids` lists the evidence actually used by that unit.
- A `result` unit additionally records an `artifact`,
  `allowed_interpretation`, and `prohibited_interpretation`.

### Dependency snapshot

`rka_snapshot` is a normalized, deterministic record of the RKA entities on
which the spine depends, including terminal sources reached through a `clm_`.
Its purpose is change detection, not offline proof. The live resolver remains
authoritative.

The snapshot builder must not mutate the spine and refuses to create a baseline
unless live validation is exactly `PASS`; neither `WARN`, `BLOCK`, nor `ERROR`
can be laundered into a snapshot. The `snapshot` CLI enforces the same gate.
Currency checking re-runs live validation in addition to comparing the saved
dependencies with fresh resolver results, and reports:

- which entities changed;
- which claim IDs depend on them; and
- which manuscript unit IDs need revalidation.

A content change does not rewrite `allowed_wording`. It marks affected claims
for review. A stronger result may justify a new proposal, but it never silently
upgrades PI-ratified text.

RKA 2.8 freshness metadata remains authoritative. `staleness: yellow` is a
soft review signal and therefore emits `WARN`; `staleness: red` emits `BLOCK`.
`valid_from` and `valid_until` (or a cluster's `synthesis_valid_until`) are
ground-truth temporal boundaries: not-yet-valid or expired records block. A
green record with a reviewed `historical`, `retired`, `superseded`, or
`retracted` disposition is not current manuscript support. `dismissed` means
the prior freshness concern was dismissed and is usable unless another hard
signal applies. Invalid or unknown freshness metadata is `ERROR`, never
silently interpreted. `needs_reprocessing: true` blocks use of that synthesis.

## Lifecycle

### 1. Bootstrap after venue selection

Copy the workspace template. Set `project_id` and `manuscript_id`, then confirm
both against RKA. The empty template is intentionally not ready for drafting.

### 2. Assemble candidate claims

Use several short retrieval angles over the research map and project records.
For each candidate, identify:

1. the prior limitation or open problem;
2. the project's response and the decision lineage behind it;
3. grounding-verified positive evidence with `evidence_status` of `supported`
   or `partially_supported`;
4. qualifiers, failed branches, and counterevidence;
5. the conditions under which the evidence holds; and
6. a claim that says no more than those records support.

At this stage `status` remains `candidate`. A structurally complete candidate
may still require ratification; that is expected and must not be reported as a
final `PASS`.

### 3. Present bounded alternatives to the PI

As the first part of the existing Outline checkpoint, present claim-and-outline
alternatives. Each alternative shows its evidence path, conditions, missing
evidence, and prohibited extension. Do not rank alternatives with a numeric
paper-quality score.

The PI may retain the bounded claim, narrow it, or commission an evidence-gap
mission. Within the same Outline checkpoint, record each selected contribution
as a child claim-scope `dec_`: its `chosen` field is exactly one claim sentence,
its `decided_by` field is `pi`, and its provenance names the relevant RKA
records. Its `related_journal` must explicitly include the manuscript manifest,
not merely an unrelated project journal. This creates no extra checkpoint; it makes multi-claim ratification
unambiguous. Set `status: ratified` and `ratified_by` only after that decision
is active.

### 4. Plan the argument and results

Create units that connect each paper move to a ratified claim and source-backed
evidence. Every empirical claim needs at least one `result` unit. Every major
result unit needs at least one contribution claim. Exploratory material must be
labeled and cannot be promoted to a contribution without PI ratification.

### 5. Validate, snapshot, and render

Resolve the manuscript, decision, claim, qualifier, counterevidence, and
terminal-source records. When validation is `PASS`, build the
dependency snapshot and render the three generated views:

- `.planning/CONTRIBUTION_CONTRACT.md`
- `.planning/ARGUMENT_SPINE.md`
- `.planning/RESULTS_TRACE.md`

These files teach and audit the logic, but only
`.planning/RKA_CLAIM_SPINE.yaml` is edited by the Writer.

### 6. Draft from unit-specific evidence

The Section Drafter reads the relevant units, resolves their evidence again,
and drafts within `allowed_wording` and the recorded interpretations. Hidden
provenance comments in `.tex` remain the prose-level enforcement mechanism.

### 7. Refresh on every writing session

Use the RKA changelog and snapshot comparison before resuming. Revalidate only
the affected claims and units when possible. Missing or changed dependencies
remain visible until the PI resolves them.

### 8. Supersede rather than overwrite

When evidence or scope changes materially, create a new PI decision that
supersedes the former decision. Update claim wording, boundaries, units, and
snapshot together. The old decision stays in RKA as design history; it does not
remain current support.

## Research design lineage

The spine uses the RKA decision tree to explain why the reported design and
evaluation exist in their present form. During claim assembly, inspect the
active decision head plus relevant superseded decisions and mission outcomes:

- the research question or constraint that forced a choice;
- alternatives considered, including a failed or rejected branch;
- the observation available when the PI chose;
- the rationale and scope selected by the PI;
- any later decision that superseded it; and
- how that history narrows, motivates, or redirects the manuscript claim.

This history sharpens Methods and Discussion prose, but it does not become
empirical support merely because it explains the design. The Outline decision's
rationale should summarize the shared lineage; each child claim-scope decision
stores one exact selected sentence and links the underlying records. Its
supersession chain preserves later wording changes. The claim spine points to
the current claim-scope ratification while currency checking prevents an old
decision head from remaining silently active.

Failed branches may justify a limitation, motivate a design choice, or identify
an evidence gap. They do not establish that all alternatives fail. Likewise,
the absence of an RKA record is not evidence that an experiment, threat, or
prior method does not exist.

## Commands and callable surface

The command names are `validate`, `snapshot`, `check-currency`, and `render`.
First resolve `WRITER_SKILL_DIR` to the directory containing the currently
loaded `rka-writer` `SKILL.md`. This works from an installed Codex/Claude plugin
as well as a source checkout; do not assume the current directory is the RKA
repository.

```bash
WRITER_SKILL_DIR=<absolute-path-to-loaded-rka-writer-skill>
python "$WRITER_SKILL_DIR/scripts/claim_spine.py" validate <spine.yaml> \
  --entity-packet <fresh-rka-entities.json>
python "$WRITER_SKILL_DIR/scripts/claim_spine.py" snapshot <spine.yaml> \
  --entity-packet <fresh-rka-entities.json>
python "$WRITER_SKILL_DIR/scripts/claim_spine.py" check-currency <spine.yaml> \
  --entity-packet <fresh-rka-entities.json>
python "$WRITER_SKILL_DIR/scripts/claim_spine.py" render <spine.yaml> \
  --output-dir <directory>
```

In a source checkout, `WRITER_SKILL_DIR="$PWD/rka/skills/writer"` when invoked
from the repository root. An agent running the installed plugin must use the
skill path provided when the skill was loaded, not a hard-coded cache version.

For the plugin workflow, use `rka_query(operation="entity", ...)` with the
spine's explicit project id to collect every direct dependency, then follow
each `clm_.source_entry_id` to its source. Write the fresh results to a
session-local packet:

```json
{
  "project_id": "prj_01...",
  "collected_at": "2026-07-22T20:00:00Z",
  "entities": {
    "clm_01...": {"id": "clm_01...", "source_entry_id": "jrn_01..."},
    "jrn_01...": {"id": "jrn_01...", "status": "active"}
  }
}
```

The packet is a temporary transport from the authenticated, project-scoped RKA
MCP into the deterministic validator. It is not evidence or a second snapshot;
regenerate it in the current writing session and do not commit it. Its
`project_id` must exactly match the spine. A missing direct or terminal entity
still blocks validation.

If a trusted local RKA REST server is intentionally running, the same commands
accept `--rka-url http://127.0.0.1:9712` instead. REST resolution sends the
spine's project id in `X-RKA-Project`. Do not expose REST merely to use this
script. `validate` accepts `--project` as an additional consistency check. An
unavailable resolver reports `ERROR`; the script does not infer evidence from
YAML or a generated view. `snapshot` runs validation itself and writes no
snapshot unless the result is `PASS`.

The local renderer is resolver-free and can run offline:

```bash
python "$WRITER_SKILL_DIR/scripts/claim_spine.py" render \
  manuscripts/<project-id>/<venue>/.planning/RKA_CLAIM_SPINE.yaml \
  --output-dir manuscripts/<project-id>/<venue>/.planning
```

The Writer may instead inject an in-project resolver when calling the script as
a module. The script exposes these callable operations for that workflow and
for offline contract tests:

```python
data = load_spine(path)
validation = validate_spine(data, resolver=resolver, project_id=project_id)
snapshot = build_snapshot(data, resolver)
currency = check_currency(data, resolver)
views = render_views(data, output_dir)
```

Rendering alone does not validate an entity, refresh a snapshot, or assert that
the research record is current. A generated Markdown file is never evidence of
`PASS`.

## Verdicts and failure states

| Verdict | Meaning | Gate behavior |
|---|---|---|
| `PASS` | Required structure and currently resolved dependencies satisfy the v1 contract. | May continue, subject to PI checkpoints. It is not proof of scientific truth. |
| `WARN` | A bounded, surfaced issue needs PI attention but is not a known hard failure. | Show the finding and affected units; never silently discard it. |
| `BLOCK` | The manuscript would assert an unratified, unsupported, stale, or internally inconsistent claim. | Do not advance the Outline, Draft, or Final Layout gate. |
| `ERROR` | The input, resolver, RKA connection, or dependency snapshot is unavailable or unusable. | Stop validation. `ERROR` is never `PASS`. |

Required hard failures include:

- unknown schema version or malformed/non-mapping YAML;
- duplicate local claim or unit identifiers;
- no resolver when validation is requested;
- wrong-project or missing entities;
- red-stale, expired, not-yet-valid, inactive, superseded, retracted, or
  unverified evidence;
- a `clm_` whose terminal source is missing or stale;
- direct `jrn_`, decision, or evidence-cluster records used in place of the
  required `clm_`-to-`jrn_` empirical evidence chain;
- a non-`empirical` contribution in schema v1;
- a `manuscript_id` that is not an in-project manuscript-tagged `jrn_`, or a
  manuscript-tagged journal used as a terminal empirical source;
- a grounded `clm_` whose `evidence_status` is missing or is not `supported` or
  `partially_supported`, or whose contradiction state is not explicitly clear;
- a ratified claim whose text no longer matches the active PI decision;
- a ratification decision that is not explicitly scoped to this manuscript via
  `related_journal`;
- unresolved counterevidence hidden behind a strong claim;
- fluent wording with no source-backed evidence;
- an empirical claim without a result unit;
- a result unit with no contribution claim;
- missing allowed/prohibited claim boundaries; and
- missing or outdated currency snapshot when currency is asserted.

Currency checking also expands unit-only `clm_` dependencies through their
terminal sources, so a changed source invalidates the exact Results unit even
when that record is not repeated in a top-level contribution claim.

When evidence is missing or challenged, the PI-facing choices are: narrow the
claim, commission an evidence-gap mission, or remove/defer the claim. The Writer
does not fabricate a replacement identifier, choose one side of a conflict, or
upgrade wording on its own.

## Design lineage and boundary

The contribution contract, unit-level argument plan, and bidirectional
result-to-claim mapping were informed at a conceptual level by
[PaperSpine](https://github.com/WUBING2023/PaperSpine), reviewed at commit
`d4529208cda72aa075767611b0265b95b709b550`. This document
re-expresses those ideas in RKA-native graph, currency, and PI-decision terms.
No PaperSpine code, updater, templates, reviewer scoring, detector-evasion
workflow, or independent orchestration state is included.

Future reuse of PaperSpine code or substantial text must preserve its MIT
license notice. This v1 integration is an independent implementation and stays
inside the Writer bookkeeper boundary.
