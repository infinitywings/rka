# RKA Ecosystem Active Roadmap Plan

- Status: active
- Date: 2026-09-03
- Decision owner: Chenglong Fu
- Governing RKA decision: `dec_01M1MZZXK74SNS0ZNMHE47QJPB`
- Replaces as execution source:
  `2026-08-25-rka-ecosystem-repository-separation.md`

## Objective

Align current execution with the completed Core separation, the local-first
access decision, and the RKA Writer re-baseline without losing validated
history or compatibility assets.

## Product boundaries

### RKA Core

Owns durable research knowledge and its public contracts. Core completes its
3.0 release and then continues correctness, retrieval, provenance, integrity,
recovery, and compatibility maintenance.

### RKA App

Owns Foundation 0, agent-guided installation, lifecycle supervision, and
optional deployment adapters. The Hugging Face path is a fixed-sample public
Core demo followed by a data-free, user-owned template. It is not a hosted RKA
service operated by RKA Project.

### RKA Writer

Owns authoring state, convergence, bounded realization, manuscript source
mapping, and researcher-facing authoring interaction. It consumes Core only
through public project-scoped interfaces. The existing repository is
re-baselined rather than replaced.

### Reviewers

Academic reviewers remain explicit, isolated, and advisory. Their distribution
is separated from the active Writer product so reviewer policy and release
weight do not define the authoring runtime.

### Agentic

Shelved. Historical code and decisions remain discoverable. Reactivation
requires a new PI decision.

## Ordered work

1. **Core 3.0 release gate**
   - release immutable Core artifacts;
   - verify public-contract, upgrade, recovery, and legacy-export gates;
   - record the supported compatibility range.
2. **RKA App Foundation 0**
   - merge the isolated supervisor/runtime candidate;
   - pin the released Core image by digest;
   - create repository-local A0-A3 tracking.
3. **Writer repository re-baseline**
   - freeze the current 0.2 Writer skill as the legacy evaluation baseline;
   - retain legacy Core import as compatibility infrastructure;
   - separate Reviewer distribution;
   - replace the plugin-first repository surface with RFC, ADR, architecture,
     evaluation, and roadmap documents.
4. **Writer W0**
   - accept the Authoring IR RFC;
   - accept focused ADRs for authority/storage, dependencies/staleness,
     researcher admission, and Core integration;
   - add schemas and sanitized fixtures only after those decisions stabilize.
5. **Writer W1**
   - implement one central-question-to-paragraph path;
   - prove exact upstream invalidation and no silent rewrite;
   - compare against the pinned Writer 0.2 baseline before broadening scope.
6. **Access A0-A2**
   - validate agent-guided local installation;
   - publish the fixed-sample Core demo;
   - validate duplication into a user-owned instance with explicit persistence
     and privacy trade-offs.
7. **Integration E6**
   - publish a Core/App/Writer compatibility matrix;
   - add reproducible Core-only, Core+App, and Core+Writer smoke tests;
   - keep release cadences independent.

App and Writer work may proceed in parallel once the required Core artifact
and contract versions are pinned. Hugging Face is not a prerequisite for
Writer W0 or W1.

## Validation gates

- No active documentation presents Agentic extraction as planned work.
- No active documentation calls RKA App a future repository.
- The public demo accepts no private research or durable visitor records.
- Writer implementation does not begin before W0 decisions and fixtures are
  reviewable.
- Accepted Writer artifacts never change without an explicit semantic patch or
  researcher decision.
- Legacy import and historical design remain recoverable throughout the
  compatibility window.
- No repository or remote tracking change is treated as published until its
  branch, pull request, checks, and resulting default branch are read back.

## Rollback and history

The previous separation plan remains preserved as a superseded historical
record. Core databases and legacy Writer tables are not dropped. The Writer
0.2 tag remains a reproducible baseline, and the new Writer design proceeds
through ordinary commits rather than a history rewrite.
