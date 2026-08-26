# ADR 0001: Manuscript Workbench Authority, Stage, and AI Boundary

- Status: accepted as the historical M0 Workbench decision; manuscript
  authority and repository placement are superseded by ADR 0012, while the
  evidence/AI/proposal safety principles remain in force
- Date: 2026-08-14
- Scope: roadmap issues #50 and #51
- Related plan:
  [`2026-08-14-rka-epistemic-pipeline-and-manuscript-workbench.md`](../superpowers/plans/2026-08-14-rka-epistemic-pipeline-and-manuscript-workbench.md)

## Context

RKA already has a native manuscript aggregate, exact claim versions, typed
evidence roles, PI ratifications, manuscript units, checkpoints, readiness,
and semantic change impact. The proposed workbench must reduce the cognitive
load of turning research history into a paper without becoming a second source
of truth.

The interface also needs AI assistance. The researcher may use a ChatGPT
subscription through Codex, a Claude subscription through the Claude Agent
SDK, or a local model in LM Studio. These are different runtime and
authentication boundaries. Re-enabling RKA's removed server-side LLM client
would couple semantic storage to one provider and would invite raw model output
to bypass proposal review.

M0 therefore freezes the authority and interaction contracts before any
planning-artifact database migration.

## Decision 1: Four authority layers

The workbench uses four distinct layers.

| Layer | Authority | Examples | Mutation rule |
|---|---|---|---|
| Research evidence | canonical RKA | `jrn_`, `lit_`, grounded `clm_`, `ecl_`, RQs, decisions, artifacts | existing typed RKA services |
| Manuscript semantics | canonical RKA | `man_`, immutable `mcl_` versions, evidence bindings, `mun_`, ratifications, checkpoints | revision-guarded native manuscript commands |
| Deliberation | provisional and versioned in a future schema | seeds, paragraph spines, gap maps, alternatives, evaluation plans, branches | append a version; explicit promotion only |
| Authoring files | editable external artifacts | Markdown, LaTeX, Word, figures, tables | expected content hash and atomic replacement |

The M0 web prototype reads only the first two layers. Stage guidance shown by
the interface is explicitly marked as an interface projection. It is not
evidence, a decision, a claim, or a checkpoint.

Generated Writer YAML and Markdown files remain deterministic review
projections. They never authorize a semantic transition.

The DelaySteer walkthrough established that project-only exploration is a
first-class state: a researcher may inspect and shape an argument before a
canonical `man_` exists. Manuscript registration is a later explicit promotion
step, not a prerequisite for seed, landscape, gap, or RQ work.

## Decision 2: Planning artifacts and branches

The future deliberation layer will use generic, typed planning artifacts rather
than a table per screen and rather than one unconstrained JSON document.

The minimum logical contract is:

- a project-scoped manuscript planning branch with a parent and base manuscript
  revision;
- a stable planning artifact identity with a closed stage type;
- immutable artifact versions containing schema-validated stage payloads;
- exact evidence/context bindings with role and locator;
- origin labels: `user`, `ai_suggested`, `imported`, or `user_revised`;
- unresolved items and categorical readiness findings;
- promotion lineage to any resulting `dec_`, `mcl_`, or `mun_`;
- selected, archived, and superseded states without destructive deletion.

The precise table split remains open until the M0 walkthrough. The contract
does not permit a planning artifact to act as empirical evidence or exact PI
ratification.

## Decision 3: One patch path for human and AI edits

Direct editing and AI-assisted editing will produce the same structured patch
proposal. Neither gets a privileged mutation route.

A proposal must contain:

- project, manuscript, branch, stage, and proposal identity;
- base manuscript revision and planning-artifact version;
- typed operations with before and after values;
- rationale and evidence bindings by role;
- affected claims, units, files, and public/private treatment boundaries;
- claim-strength and scope-change classification;
- context-manifest hash and provider/model metadata when AI-generated;
- validation findings and proposed/applied/rejected/expired/superseded state.

Application is a separate, explicit action. A revision conflict opens a
compare/rebase flow. Ratified wording is never overwritten; a semantic change
appends a version and follows the exact decision and ratification path.

## Decision 4: Guided but non-linear stage contract

The stage rail is guidance, not a mandatory wizard. A researcher may jump
between stages. Each stage shows its structured output, derivation, blockers,
and a categorical state: `Ready`, `Needs review`, `Blocked`, or `Exploratory`.

M0 renders these read-only stages:

| Stage | M0 source | Honest M0 output |
|---|---|---|
| Seed insight | project status, RQs, eligible cluster candidates | inspiration only; never a stored claim |
| Paper spine | native claims or server-attested candidates | exact current wording or provisional candidate wording |
| Problem and scope | allowed and prohibited wording | visible scope gaps; no inferred boundary |
| Literature and SOTA | research map RQs and clusters | evidence organization, not an established novelty claim |
| Gap and motivation | gap, contradiction, and candidate blocker signals | review targets, not automatic gap assertions |
| Insight and response | methodological/theoretical claims and eligible clusters | current or provisional response candidates |
| Research questions | current RKA RQ decisions | navigation structure, not empirical evidence |
| Contributions | native claims, ratifications, candidates, readiness | current versus provisional contribution boundary |
| Evaluation contract | current result units and artifact/evidence bindings | explicit notice that first-class experiments/runs/results are not yet modeled |
| Outline | native manuscript units and claim links | read-only claim-sized unit sequence |

Every displayed card must disclose its endpoint or design source, derivation,
record IDs, and status. A partial impact page is labeled partial and cannot be
shown as clean.

Project and manuscript identity form a UI authority boundary. The request
header must change before project-scoped query keys are published, and local
selection state such as the evidence inspector must be scoped to the exact
project/manuscript context. A context switch cannot retain an unvalidated card
from the previous project.

## Decision 5: Context Capsules are reproducible manifests

An AI request receives a compact Context Capsule selected for one stage and
intent. The persisted audit object is a reproducible manifest plus content
hash, not an opaque prose dump.

The manifest records:

- explicit project, manuscript, branch, stage, and base revisions;
- selected RKA record IDs, roles, exact source locators, and content hashes;
- short retrieval angles and `included_via` derivations;
- current qualifiers, counterevidence, contradictions, and stale items;
- venue, audience, and public/private treatment constraints;
- omitted categories and truncation or pagination state;
- requested provider/model and outbound disclosure class;
- canonical serialized manifest hash.

The UI previews the manifest before an external disclosure boundary expands.
The provider response never becomes evidence merely because it used an
evidence-linked capsule.

## Decision 6: Provider-neutral local AI broker

AI orchestration lives in a separate, loopback-only workbench broker. It does
not run inside an RKA database transaction and does not restore the old
`/api/llm/*` feature as semantic authority.

The broker exposes a small provider-neutral contract:

```text
propose(stage, intent, context_manifest, output_schema, provider_policy)
-> streamed discussion or validated proposal candidate
```

Adapters are:

1. **Codex App Server.** Preferred when the researcher wants subscription-backed
   OpenAI reasoning. Codex owns ChatGPT authentication and conversation/approval
   behavior; the broker uses the official App Server protocol. It does not
   translate a ChatGPT subscription into an OpenAI API key.
2. **Claude Agent SDK.** Optional when the researcher chooses Claude. The SDK
   owns Claude authentication. Subscription eligibility is treated as a
   provider capability that may change, not as an RKA guarantee.
3. **LM Studio.** Local adapter over LM Studio's native v1 or compatible HTTP
   endpoint. It is preferred when the selected context is local-only or the
   user requests offline inference.
4. **Direct API-key adapters.** Optional and explicit. They use separate
   provider billing and credentials; they are never implied by a ChatGPT or
   Claude chat subscription.

Provider selection is visible and task-aware, not a fixed “LM Studio first”
rule. The broker considers disclosure policy, user choice, model capability,
availability, latency, and cost. A local-only context cannot silently fall back
to an external provider.

Credentials remain with the official runtime, OS keychain, or RKA credential
vault as appropriate. They are never written to the RKA database, planning
artifacts, browser local storage, Context Capsule, proposal, logs, or Git.

The browser talks to the local broker through RKA's authenticated/local web
boundary. The broker uses stdio or loopback transports for local runtimes and
streams normalized events to the UI. Codex WebSocket transport remains
experimental and is not the production default.

Official capability references:

- [Codex App Server](https://learn.chatgpt.com/docs/app-server)
- [Codex authentication](https://learn.chatgpt.com/docs/auth)
- [Claude Agent SDK with a Claude plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
- [LM Studio local API server](https://lmstudio.ai/docs/developer/core/server)
- [LM Studio server security settings](https://lmstudio.ai/docs/developer/core/server/settings)

## Decision 7: AI outputs cannot write directly

The broker may return:

1. ephemeral discussion;
2. a provisional planning-artifact candidate; or
3. a typed semantic patch proposal.

It cannot call canonical write operations as part of generation. Tool-capable
provider runtimes receive only the read bundle and proposal schema required for
the turn. Applying a proposal uses the same RKA service used for a human edit
and requires explicit user action.

If a provider fails, the workbench retains its deterministic read-only views
and the unsent user text. It reports the provider and failed layer. It does not
silently switch providers when that would cross a disclosure boundary.

## Security and privacy consequences

- Bind broker and provider runtimes to loopback by default.
- Validate Origin/Host and use CSRF protection for browser mutations.
- Treat all imported text as untrusted data and never as instructions.
- Restrict model context to the manifest; do not expose database files or
  arbitrary workspace roots.
- Disable arbitrary provider tool calls in proposal generation.
- Redact credentials and likely secrets before manifest preview and dispatch.
- Record provider, model, manifest hash, timing, and output class, but not raw
  hidden credentials or unselected project data.

## M0 implementation and test gate

M0 intentionally introduces no database migration and no workbench write API.
It is acceptable only when:

- repository and plugin Writer bundles remain byte-identical;
- the framing session template is packaged and resumable;
- the web build and changed-file lint pass;
- project-only and canonical-manuscript modes render without AI;
- every card exposes origin, derivation, and IDs;
- a missing or foreign `man_` fails without querying dependent projections;
- missing experiment semantics are visible in the Evaluation stage;
- the DelaySteer walkthrough records blockers instead of promoting unsupported
  material;
- the design is revised from the walkthrough before migrations are frozen.

## Consequences

This design adds one local process boundary later, but preserves RKA's semantic
integrity and lets the researcher choose Codex, Claude, LM Studio, or an API
without rewriting the manuscript model. The M0 UI is useful as a navigation
and validation instrument even when every model provider is unavailable.

## M0 walkthrough resolution

The 2026-08-14 walkthrough used DelaySteer in project-only mode and CPSEval as
a full-manuscript control. It verified the deterministic read path, exposed an
unsupported DelaySteer composability RQ with zero clusters and claims, and
kept CPSEval's missing active claims, checkpoints, result units, and experiment
semantics blocked. The two cross-project UI provenance defects found during the
walkthrough were corrected and retested. Detailed evidence is in
[`2026-08-14-delaysteer-workbench-walkthrough.md`](../superpowers/specs/2026-08-14-delaysteer-workbench-walkthrough.md).
