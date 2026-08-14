# RKA Claim Spine

The claim spine connects the contribution promised by a manuscript to the
research records, scope conditions, PI decisions, and writing units that make
that promise defensible.

RKA core is authoritative. In a native workspace,
`.planning/RKA_CLAIM_SPINE.yaml` is a deterministic projection produced by
`rka writer sync`. It is not an independently editable knowledge base.

## Non-negotiable invariants

1. **RKA is canonical.** A planning-file value is not evidence or workflow
   state.
2. **Ratification is not proof.** A PI `dec_` authorizes exact wording. It does
   not supply empirical support.
3. **Grounding is not scientific validation.** Legacy `verified=true` means
   extraction fidelity only.
4. **Synthesis is not terminal evidence.** Follow an `ecl_` to eligible
   `clm_` records and their current sources.
5. **Evidence roles stay distinct.** Support, qualifier, and counterevidence
   cannot be silently exchanged or omitted.
6. **The PI owns claim strength.** Material wording changes require a new
   immutable version and a new exact PI ratification.
7. **Results coverage is bidirectional.** Every active empirical claim needs a
   result unit; every result unit needs a claim and evidence.
8. **Generated views are read-only.** Synchronize from RKA after a semantic
   update.
9. **Failure is fail-closed.** `BLOCK` and `ERROR` stop the affected gate.
10. **No paper score.** Findings remain categorical and evidence linked.

## Native v2 projection

The normal projection uses `rka-claim-spine/v2`:

```yaml
schema_version: rka-claim-spine/v2
authoritative_source: rka
project_id: prj_01...
manuscript_id: man_01...
manuscript_revision: 7
changelog_cursor: 1284

claims:
  - claim_id: C1
    rka_manuscript_claim_id: mcl_01...
    version: 2
    claim_type: empirical
    status: active
    text: Under T1 and T2, the method reduced malicious update acceptance.
    allowed_wording: The method reduced malicious update acceptance under T1 and T2.
    prohibited_wording:
      - The method eliminates all attacks.
    ratified_by: dec_01...
    evidence_ids:
      - clm_01...
    qualifier_ids:
      - clm_01...
    counterevidence_ids: []
    manuscript_units:
      - U-ABSTRACT-1
      - U-RESULTS-1

units:
  - unit_id: U-RESULTS-1
    rka_manuscript_unit_id: mun_01...
    kind: result
    status: planned
    location: sections/04-results.tex#t1-t2
    artifact_ref: figures/detection-rate.pdf
    allowed_interpretation: The measured reduction holds on the tested systems.
    prohibited_interpretation: The method is universally attack-proof.
    evidence_ids:
      - clm_01...
    claim_ids:
      - C1
```

`manuscript_revision` is the optimistic-concurrency revision of the aggregate.
`changelog_cursor` is the conservative synchronization watermark. Neither
field proves that a file remains current; use `impact` and server readiness.

## Claim fields

- `claim_id` is the stable manuscript-local key.
- `rka_manuscript_claim_id` is the stable native `mcl_` identity.
- `version` identifies one immutable wording version.
- `claim_type` is one of `empirical`, `methodological`, `theoretical`,
  `survey`, or `position`.
- `status` mirrors native `candidate`, `active`, or `retired`.
- `text` is the exact wording in the current version.
- `allowed_wording` is the strongest licensed wording.
- `prohibited_wording` records tempting extensions that the evidence does not
  license.
- `ratified_by` appears only when an active same-project PI decision exactly
  ratifies this version.
- `evidence_ids`, `qualifier_ids`, and `counterevidence_ids` name underlying
  RKA evidence claims by role.
- `manuscript_units` lists stable local unit keys affected by the claim.

For positive support, each `clm_` must be grounding-verified, scientifically
`supported` or `partially_supported`, explicitly uncontested, current,
same-project, and backed by a current non-manuscript source. Qualifiers and
counterevidence remain visible even when they narrow or challenge the desired
contribution.

## Unit fields

- `unit_id` and `rka_manuscript_unit_id` are the local and native stable
  identities.
- `kind` describes the communicative role: abstract, introduction,
  related-work, background, method, result, discussion, limitation,
  conclusion, caption, appendix, or other.
- `location` is a portable relative file anchor.
- `status` is planned, drafted, reviewed, final, or removed.
- `claim_ids` and `evidence_ids` establish bidirectional traceability.
- `artifact_ref` identifies a figure, table, dataset, or other result artifact.
- result units require explicit allowed and prohibited interpretations.

Prefer claim-sized or paragraph-sized units over one row per section. The
purpose is targeted invalidation: a changed source should identify the exact
writing and artifact scope requiring review.

## Normal lifecycle

### 1. Bootstrap

Run:

```bash
rka writer init \
  --project-id prj_... \
  --venue USENIX \
  --title "..."
```

Initialization creates or verifies a native manuscript, stores the canonical
`man_` id, and atomically publishes the workspace. An empty spine does not
authorize drafting.

### 2. Assemble candidates

Use multi-angle RKA retrieval and the choice-first session in
[`framing_elicitation.md`](framing_elicitation.md). The Writer proposes
evidence-bounded alternatives with pros and cons; the author supplies narrative
intent; the researcher supplies scientific scope judgment. Record provisional
selections in `.planning/FRAMING_SESSION.yaml`. They do not modify the native
manuscript aggregate and do not count as evidence or ratification.

For each candidate identify:

1. the prior limitation or open problem;
2. the project's response;
3. current positive evidence;
4. qualifiers, failed branches, and counterevidence;
5. the tested conditions;
6. allowed and prohibited wording;
7. the result and non-result units that will carry the claim.

`rka writer assist` may accelerate discovery but returns unratified candidates
only. Present contribution inclusion as a multi-select choice, claim
calibration as a single-select choice per contribution, and the final whole
paper spine as a single-select choice. Offer revise/combine and defer/gather
evidence paths where appropriate.

### 3. Dry-run and apply

Prepare a proposal file, then:

```bash
rka writer import-spine \
  --project-id prj_... \
  --manuscript-id man_... \
  --input proposal.yaml
```

Dry-run is the default. Review the proposed counts and diff. Apply only with:

```bash
rka writer import-spine \
  --project-id prj_... \
  --manuscript-id man_... \
  --input proposal.yaml \
  --expected-revision 7 \
  --apply
```

The update may create or modify claim identities, immutable wording versions,
evidence roles, units, and bindings. It never imports `ratified_by`, guesses a
decision, or creates PI authority.

### 4. Ratify exact wording

Present the surviving alternatives with concrete pros, cons, evidence coverage,
missing evidence, scope boundaries, and outline consequences during the
existing Outline checkpoint. Obtain one explicit final PI confirmation after
the advisory framing session. For each selected contribution:

1. record an active PI decision whose `chosen` text exactly matches the claim
   version;
2. call `ratify_manuscript_claim` with the exact claim and version;
3. resolve the Outline checkpoint explicitly.

If wording later changes materially, append a version and obtain a superseding
PI decision. Never carry the old ratification forward by implication.

### 5. Synchronize and gate

```bash
rka writer sync \
  --project-id prj_... \
  --manuscript-id man_... \
  --output .planning/RKA_CLAIM_SPINE.yaml \
  --render-dir .planning

rka writer readiness \
  --project-id prj_... \
  --manuscript-id man_... \
  --target-phase drafting
```

The generated contribution contract, argument spine, and results trace are PI
review aids. Server readiness is the mechanical authority.

### 6. Re-enter after research changes

```bash
rka writer impact \
  --project-id prj_... \
  --manuscript-id man_... \
  --claim-spine .planning/RKA_CLAIM_SPINE.yaml
```

Review the affected claims, units, file locations, artifacts, and source
records. A partial response requires pagination or full resynchronization.
After repair or confirmation, synchronize and run readiness again.

## Readiness failure classes

Hard failures include:

- missing or wrong-project manuscript;
- inactive manuscript or missing required venue;
- no active claims;
- active claim without a wording version;
- missing or stale exact PI ratification;
- support that is unverified, scientifically unassessed, contradicted, stale,
  retracted, superseded, or terminally ungrounded;
- active empirical claim without a result unit;
- result unit without evidence, claim coverage, artifact, or interpretation
  boundaries;
- required unresolved checkpoint;
- unknown response schema, malformed authority metadata, or unavailable
  resolver.

When evidence is missing or challenged, the PI-facing choices are to narrow the
claim, commission an evidence mission, or defer/remove the claim. Writer does
not invent an identifier, choose one side of a contradiction, or strengthen
wording automatically.

## Legacy v1 migration

`rka-claim-spine/v1` is supported as an explicit migration input. Its
`jrn_` manuscript, local `ratified_by`, and packet snapshot are not native
authority.

Migration rules:

- retain the legacy journal and resolve its linked `man_` id;
- dry-run before applying;
- import structural claim/unit content only;
- never synthesize or import ratifications;
- never reinterpret legacy `verified=true` as scientific validation;
- surface ambiguous or wrong-project records rather than choosing one;
- synchronize a fresh v2 projection after any successful import.

The Python `claim_spine.py` loader and renderer remain compatible with v1 so an
old workspace can be inspected. Packet validation and `rka_snapshot` are
compatibility aids, not the normal native currency mechanism.

## Design lineage

The contribution contract, unit-level argument plan, and bidirectional
result-to-claim mapping were informed conceptually by
[PaperSpine](https://github.com/WUBING2023/PaperSpine), reviewed at commit
`d4529208cda72aa075767611b0265b95b709b550`. This is an independent
RKA-native implementation. No PaperSpine code, updater, templates, reviewer
scoring, detector-evasion workflow, or independent orchestration state is
included.

Any future reuse of PaperSpine code or substantial text must preserve its MIT
license notice.
