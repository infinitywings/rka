# TraceGuard Core lifecycle and story-retrieval report

Date: 2026-08-26

RKA project: `prj_01M100GW2EVPA8T6Q4CSZ5GPFA`

Decoy project: `prj_01M100J7RFTH7KZ5BVJ3497SMA`

Source branch: `codex/story-retrieval-benchmark`

Formal-run commit: `815dddd50766b596468a4a8f19c9ca05ef6c7cdc`

## Verdict

RKA preserved and mechanically recovered the complete TraceGuard research
story across a realistic non-writing lifecycle, two service restarts, five
query styles, and a separate decoy project. The frozen mechanical benchmark
passed all five variants with complete role, edge, fact, and currentness
coverage and no foreign-project leakage.

Human-agent use is not yet equally reliable. A cold PI and a session-reset
Executor reconstructed the current bounded conclusion and caveat, while a cold
Brain reconstructed the scientific rationale and results but missed the two
newest current journal records. This is an agent retrieval-path gap, not a
demonstration that the records are absent: the same records were returned by
the mechanical pipeline and by the other roles. No broad search-ranking change
is justified by this single miss.

## Scope

This pilot intentionally excludes manuscript writing. It exercises:

1. PI framing and safety boundaries;
2. literature investigation and ingestion;
3. research-question and design decisions;
4. experiment planning, execution, observations, and evidence locators;
5. a PI checkpoint and a superseding metric decision;
6. cold/session-reset retrieval of a complete causal story;
7. project isolation and persistence across container restarts.

The assumed project is a synthetic comparison of event-only and
sequence-aware detectors for delayed injection-like behavior. It contains no
operational payloads, credentials, personal data, victims, or external service
access.

## Research lifecycle exercised

| Stage | RKA evidence | What was preserved |
|---|---|---|
| PI boundary | `jrn_01M100H532YAQG7EMNAR89D3BV` | Synthetic-only evaluation; delayed recall and benign FPR kept separate; no real services, credentials, or victims. |
| Research question | `dec_01M100SFKDYJ90JKFBJGQ0Q5G2` | Bounded sequence-aware versus event-only comparison. |
| Literature investigation | `mis_01M100W48HGBKZFZAG4W31T94C`, eight `lit_*` records, `jrn_01M101HHBB0DCFPFWNV7RXQ7W9` | Metadata/abstract-grounded motivation and the explicit absence of matched causal proof. |
| Design | `jrn_01M1023YJ9Q4TS5S9MNWYMFMH7`, `dec_01M1024N98M884Y6NN6WSZT5BG` | Same fixed-seed ordered inputs for both detector conditions. |
| Provisional metric | `dec_01M10257XN60E16CNWMCAERQ1X` | Accuracy was a smoke summary with a predeclared masking gate. |
| Smoke execution | `mis_01M102BJ82EQ3Z3EPKSHX1F940`, `run_01M10329MPS836S7JW9Z57V6JN`, `jrn_01M103546A4A5233R6VBSV6RSQ` | Event-only accuracy 52/64, delayed recall 0/8, benign FPR 4/48; sequence-aware 64/64, 8/8, 0/48. |
| PI gate | `chk_01M1035MXNJS325AV8H92B5T5J`, `jrn_01M1042MFY06N5AV6ZQRTRRCZ0` | The masking checkpoint was resolved without deleting plan-v1 evidence. |
| Current metric | `dec_01M1043H523XXD2Z27REEEHPN5` | Delayed recall and benign FPR became co-primary; accuracy became secondary; the provisional decision is superseded. |
| Formal execution | `mis_01M10493P45V18EHRNQTCWYMS0`, `run_01M1055HAEVSSW87GJT1RS4EGC`, `jrn_01M105CAQ6CCAPKGBTAB05DFQ7` | A 256-episode matched run, unchanged detectors, eight passing tests, and two byte-identical same-environment executions. |
| Current interpretation | `jrn_01M105Y4B392K97RR0CG2JW6XY`, `jrn_01M105YKBWHZM1T4ME59AZBWJV` | The result is limited to the fixed synthetic harness; no causal, deployment, real-world, or general superiority claim is authorized. |

## Formal experiment result

Plan v2 used 256 episodes: 128 ordinary benign, 64 benign sensitive,
32 immediate injection-like, and 32 delayed injection-like episodes. The two
detectors received matched ordered inputs and retained their plan-v1
definitions.

| Detector | Delayed recall (co-primary) | Benign FPR (co-primary) | Accuracy (secondary) |
|---|---:|---:|---:|
| Event-only | 0/32 | 16/192 (0.083333) | 208/256 (0.8125) |
| Sequence-aware | 32/32 | 0/192 | 256/256 |

The corpus, prediction, and metric artifacts were byte-identical across two
executions in the same environment. The independently repeated core artifacts
also matched from another checkout. Environment and whole-manifest hashes can
differ with the Python interpreter, so the supported claim is deterministic
core artifacts under the frozen plan, not cross-environment identity of every
metadata file. Plan-v1 files remained byte-identical.

## Persistence and isolation

The RKA API and worker were restarted twice after records were written. After
the second restart, readback recovered both experiment plans, both successful
runs, all six formal observations, one evidence locator per observation, the
superseded/current decision state, the current conclusion and caveat, and a
62-node/135-edge project graph.

The decoy project contains the same distinctive phrase in
`jrn_01M100KGH1EG8V2X8TVB2261XZ` and
`dec_01M100KWBJJ7WWN2PCJBQNPT3T`. Exact-phrase retrieval scoped to the main
project returned neither decoy ID.

## Frozen mechanical retrieval benchmark

The corpus at
`eval-harness/v3/tracing/scenarios.traceguard-core.jsonl` freezes one
project-attested story with exact, paraphrase, colloquial, underspecified, and
status-aware variants. It requires 12 semantic roles, verified edges, facts,
current-versus-superseded state, a minimum precision of 0.25, and explicit
foreign-project exclusions.

| Metric | Result |
|---|---:|
| Variants | 5 |
| Story success | 1.0000 |
| Required role coverage | 1.0000 |
| Required edge coverage | 1.0000 |
| Fact coverage | 1.0000 |
| Currentness accuracy | 1.0000 |
| Precision, mean | 0.4747 |
| Anchor MRR | 0.9000 |
| Anchor hit rate | 1.0000 |
| Hard failures | 0 |
| Divergences | 0 |

Per-style precision was 0.5000 exact, 0.4800 paraphrase, 0.4138 colloquial,
0.4898 underspecified, and 0.4898 status-aware. The colloquial variant had the
lowest anchor rank but still recovered the complete required story.

## Three-role retrieval audit

All roles answered the same question with a 12-query ceiling:

> Why did we change the metric after the smoke run, and did the bigger run
> confirm anything?

### Cold PI: pass

The PI began without TraceGuard context and used only personal RKA reads. It
recovered the original boundary, RQ, literature qualification, design,
provisional metric, smoke checkpoint, active metric decision, formal result,
latest bounded conclusion, and latest caveat. The answer correctly separated
the reproduced synthetic pattern from unsupported general claims.

### Cold Brain: partial

The Brain began without TraceGuard context and recovered the scientific
rationale, smoke masking failure, superseding decision, exact formal metrics,
and the no-causality/no-deployment boundary. It did not cite or mark current the
two latest records `jrn_01M105Y4B392K97RR0CG2JW6XY` and
`jrn_01M105YKBWHZM1T4ME59AZBWJV`. Its prose independently reconstructed most
of their content from the active decision and formal report, but the omission
is a currentness/provenance failure for strict story retrieval.

### Session-reset Executor: pass with control limitation

The Executor started a new turn and reread RKA without repository or memory
evidence. It recovered the full current story, including the two latest
records, in exactly 12 read calls. This is a session-reset persistence control,
not a genuinely blind independent role: the same Executor had produced the
formal run earlier. That limitation is retained rather than presenting the
result as a third fully cold audit.

The free-form role outputs were not passed through the strict response scorer.
The PI and Brain emitted preview-subsystem IDs and structured causal-chain
objects outside the scorer's unified-graph-only response schema. Normalizing
those outputs after seeing the answer would hide a real collection/schema
issue. The mechanical benchmark is the quantitative result; the three role
audits are reported as raw behavioral evidence.

## Defects and design observations

1. **Agent retrieval policy is not yet stable.** Mechanical retrieval and two
   roles found the newest boundary records, while the cold Brain did not. A
   bounded session-start/story-retrieval recipe should be evaluated before any
   further global ranking changes.
2. **Experiment preview entities are outside the unified graph/resolver.** The
   graph-backed bridge journals make the story retrievable, but experiment,
   plan, run, observation, and evidence-locator records require separate
   preview operations. This split complicates complete provenance scoring.
3. **Observation schema discovery omitted a constraint.** Supplying both
   `value_real` and `value_text` was rejected as mutually exclusive even though
   `rka_describe` did not disclose the constraint. Each rejected call occurred
   before creation and was retried once with `value_real`; no duplicates were
   created.
4. **Mission task rows can lag mission state.** The formal mission is complete
   with a submitted report, but individual task rows still display `pending`.
5. **Generic provenance can disagree with resolved entities.** Direct entity
   and decision-tree fields expose links that generic provenance sometimes
   reports as absent.
6. **Global integrity debt predates this pilot.** The live database reported
   548 existing issues: 213 orphan vectors, 300 orphan FTS rows, and 35 journals
   missing a project. The isolated pilot did not create these rows.
7. **One optional test is environment-gated.** The full eval-harness/v3 suite
   produced 85 passes and one failure because the isolated environment lacked
   optional `litellm`; the focused tracing suite passed 57/57 and the pilot
   experiment suite passed 8/8.

## Recommended next step

Keep the server changes minimal. Before changing ranking again, define and test
one bounded story-retrieval routine for cold agents: obtain scoped context and
status, search with two or three complementary anchors, resolve the graph
entities, read current/superseded state, then read experiment/report previews
when the story crosses that subsystem. Add a strict collector that preserves
raw calls but emits scorer-compatible unified-graph citations. Re-run the three
roles with fresh agents and require all of them to cite the latest conclusion
and caveat before declaring agent-level story retrieval reliable.
