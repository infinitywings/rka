# ADR 0013: Shelve Agentic and focus the active ecosystem on Core and Writer

- Status: accepted
- Date: 2026-08-27
- Decision owner: Chenglong Fu
- Supersedes: the Agentic repository and active-extraction portions of
  [ADR 0012](0012-rka-ecosystem-repository-boundaries.md)

## Context

RKA's immediate value is the reliability of its durable research record:
journals, decisions, claims, evidence, provenance, experiments, and retrieval.
The manuscript experience has a distinct product boundary and already has a
separate repository, `infinitywings/rka-writer`. A third active Agentic product
would add packaging, runtime, credential, release, and support obligations
without helping the current Core reliability priority.

The prior Agentic branch and its design documents still contain useful
historical work. Shelving that work should preserve provenance without making
it an active dependency or directing new users to install an unsupported
runtime.

## Decision

1. The active RKA ecosystem consists of RKA Core and RKA Writer.
2. No `infinitywings/rka-agentic` repository will be created or maintained as
   part of the current roadmap.
3. The historical Agentic branch, commits, and design records are preserved as
   archival material. They are not merged into Core, advertised as supported,
   or used as a prerequisite for Core or Writer.
4. Core may retain small Brain, Executor, and PI usage guides for human-driven
   research workflows. These guides use Core's public REST/MCP contracts and
   do not imply an autonomous orchestrator runtime.
5. Existing Agentic-specific installation and deployment text is historical
   only. Active documentation must clearly say that the runtime is shelved and
   unsupported.
6. Reactivating Agentic requires a new explicit PI decision and a fresh design
   review against the then-current Core contract. ADR 0012 alone is not
   authorization to resume it.

## Consequences

- Core reliability and retrieval receive the development and testing focus.
- Writer can evolve independently without a third release dependency.
- Historical Agentic work remains auditable and recoverable.
- Compatibility code or documentation that still mentions Agentic should be
  removed or marked historical incrementally; no destructive database or
  history rewrite is required.

## Relationship to ADR 0012

ADR 0012 remains authoritative for Core ownership, Writer ownership, public
contract isolation, and non-destructive Writer-state migration. Its decisions
to create an Agentic repository, ship an Agentic plugin/runtime, and require an
Agentic compatibility suite are superseded by this ADR.
