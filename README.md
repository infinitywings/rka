# RKA — Research Knowledge Agent

[![pytest](https://github.com/infinitywings/rka/actions/workflows/pytest.yml/badge.svg?branch=main)](https://github.com/infinitywings/rka/actions/workflows/pytest.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**A local-first research operating system for turning day-to-day research activity into auditable knowledge and publication-ready arguments.**

AI-assisted research produces valuable observations, experiments, decisions, and failures, but that reasoning is often scattered across conversations, repositories, notes, and terminal logs. RKA maintains a persistent, provenance-aware research record and helps researchers progressively transform it into claims, evidence clusters, research questions, and defensible publication structures.

With RKA, researchers can:

- resume long-running projects without reconstructing prior reasoning;
- preserve why decisions were made and what evidence supports them;
- separate tentative observations from reviewed claims;
- supervise AI collaborators through explicit missions and decision gates;
- connect manuscript arguments to auditable research records; and
- prepare multiple research outputs from the same knowledge substrate.

RKA is built for research workflows in computer science, AI, cybersecurity, IoT, and cyber-physical systems. The core is usable today; the interactive manuscript workbench and Agent-Native Research Artifact interoperability described below are active roadmap directions.

![RKA architecture and operational mechanism](docs/paper/architecture-overview.png)

## Why RKA exists

Research is not a sequence of isolated prompts. It is a long-running process of forming questions, trying approaches, collecting evidence, revising assumptions, and deciding what the evidence supports.

Most AI tools preserve only fragments of that process. Conversation history remembers what was said but not necessarily what remains valid. Vector databases retrieve similar passages but do not explain why a decision was made. Task agents execute work but often discard the reasoning, alternatives, and failed branches that make results interpretable.

RKA treats the research record itself as durable infrastructure.

```mermaid
flowchart LR
    Inputs["Research activity<br/>notes · conversations · files · repositories · experiments"]
    Record["Longitudinal record<br/>observations · decisions · failures · provenance"]
    Knowledge["Reviewed knowledge<br/>claims · evidence · clusters · research questions"]
    Spine["Publication reasoning<br/>insight · gap · spine · contributions · evaluation"]
    Outputs["Research outputs<br/>paper · proposal · ARA · grounded dialogue"]

    Inputs --> Record --> Knowledge --> Spine --> Outputs

    style Record fill:#E6F1FB,stroke:#185FA5,color:#042C53
    style Knowledge fill:#EEEDFE,stroke:#534AB7,color:#26215C
    style Spine fill:#FAEEDA,stroke:#854F0B,color:#412402
    style Outputs fill:#E1F5EE,stroke:#0F6E56,color:#04342C
```

The early stages of this pipeline are operational in RKA today. Manuscript development is supported through the Writer skill, while the visual drafting workbench and ARA materialization layer remain under active design and implementation.

## How it works

RKA coordinates three roles around one shared, typed knowledge base:

- **Researcher** — frames the problem, contributes domain knowledge, ratifies consequential decisions, and retains final authority.
- **Brain** — retrieves context, synthesizes evidence, maintains claims and research questions, proposes options, and keeps interpretations current.
- **Executor** — performs bounded implementation or experimental missions, records findings, and raises checkpoints when assumptions or scope require review.
- **RKA** — stores the shared record, provenance graph, lifecycle state, and auditable handoffs between them.

The roles are architectural responsibilities, not requirements to use one particular model. RKA exposes its capabilities through MCP and REST. The reference workflows are currently tested most extensively with Claude Desktop and Claude Code; ChatGPT can connect through the authenticated HTTP MCP path.

### Progressive crystallization

RKA does not require every raw note to become a formal conclusion immediately. Knowledge matures in stages:

```mermaid
flowchart LR
    Journal["Journal<br/>observations · procedures · directives"]
    Candidates["Interpretation candidates<br/>source locator · uncertainty · falsifier"]
    Claims["Claims<br/>typed assertions with source spans"]
    Scope["Claim scope versions<br/>conditions · extension policy · falsifier"]
    Clusters["Evidence clusters<br/>related claims + synthesis"]
    Questions["Research map<br/>questions · gaps · contradictions"]
    Writing["Claim spine<br/>argument · contribution · evaluation"]

    Journal --> Candidates --> Claims --> Scope --> Clusters --> Questions --> Writing
```

Raw records remain available even when later interpretations change. Candidate
interpretations must be reviewed explicitly before promotion; they can be
deferred, rejected, merged, or classified without silently becoming scientific
claims. Derived claims and clusters can be reviewed, superseded, or rebuilt
without rewriting history.

Each canonical claim has a separate, immutable applicability contract. Scope
reviews record typed conditions, uncertainty, allowed and prohibited
extensions, and falsifiers. Missing or stale scope stays visible rather than
being inferred, and manuscript admission also continues to check grounding,
scientific evidence status, contradictions, and freshness independently.

### Provenance by construction

RKA connects literature, decisions, missions, findings, claims, and later decisions through typed relationships. A researcher can ask not only “What do we currently believe?” but also:

- Which observations support this claim?
- Which decision caused this experiment to be run?
- What changed after an assumption was invalidated?
- Which manuscript contribution still lacks sufficient evidence?
- What did the project believe at an earlier point in time?

### Researcher-controlled agency

AI collaborators may propose interpretations and execute approved work, but consequential commitments remain visible. Confirmation briefs, checkpoints, decision records, validation gates, and reversible supersession keep the researcher in control without forcing them to reconstruct every agent action.

## What RKA is—and is not

RKA is not a replacement for a reference manager, a generic retrieval database, or a paper generator layered directly on top of chat history.

It combines four concerns that are usually separated:

| Concern | RKA's role |
|---|---|
| **Continuity** | Preserve research activity across sessions, tools, and collaborators. |
| **Epistemic structure** | Distinguish observations, assumptions, hypotheses, results, and reviewed claims. |
| **Control** | Record decisions, delegate bounded missions, and escalate uncertainty. |
| **Publication grounding** | Build arguments from traceable claims and evidence rather than reconstructing provenance after writing. |

Zotero, repositories, notebooks, and experimental platforms remain important sources. RKA links and interprets their outputs rather than attempting to replace them.

## What is available today

- **Persistent, multi-project research records** for journals, literature, decisions, missions, reports, checkpoints, and artifacts.
- **Interpretation staging** with exact source locators, uncertainty, falsifiers, immutable review history, and explicit promotion or revocation.
- **Canonical claim-scope contracts** with immutable revisions, typed applicability conditions, extension policy, falsifiers, and fail-closed manuscript readiness.
- **Claims and evidence clusters** with source-span provenance, confidence states, contradictions, and review workflows.
- **Research maps** connecting research questions to clusters and individual claims.
- **Decision and freshness lifecycles** with supersession, staleness propagation, assumption tracking, and historical belief queries.
- **Brain–Executor workflows** with scoped missions, acceptance criteria, backbriefs, checkpoints, and reports.
- **Hybrid retrieval and graph navigation** using FTS5, optional vector embeddings, typed links, and multi-hop context assembly.
- **Researcher-facing dashboard** for browsing projects, journals, decisions, missions, research maps, provenance, and audit history.
- **Role-specific skills** for strategic research management, execution, PI supervision, and manuscript writing.
- **MCP, REST, CLI, and knowledge-pack interfaces** for local and connected workflows.

Detailed feature and workflow documentation lives in the [User Manual](docs/USER_MANUAL.md) and [Usage Guide](USAGE_GUIDE.md).

## From one research record to papers and ARA

RKA's publication direction is based on a simple principle: researchers should not have to reconstruct their scientific reasoning separately for every output.

The planned manuscript workbench will guide a researcher from an initial insight through problem scoping, related-work positioning, gap analysis, challenges, innovations, research questions, contributions, evaluation design, claim spine, outline, and full draft. Throughout that process, proposed text remains linked to RKA claims, evidence, decisions, and source records.

This creates a natural interoperability point with the [Agent-Native Research Artifact](https://github.com/ARA-Labs/Agent-Native-Research-Artifact) project:

- **RKA** provides the longitudinal capture, reasoning, review, and authoring environment.
- **ARA** provides a portable agent-native research package spanning scientific logic, executable assets, exploration history, and evidence.
- **Traditional papers and ARA packages** can become two grounded views of the same research effort instead of two separately maintained records.

The intended integration is an explicit, testable crosswalk—not a lossy text export. Stable RKA entities should map to ARA objects with preserved provenance, lifecycle status, and claim–evidence bindings. This interoperability is planned work and is not yet part of the released core.

## Quick start

### 1. Start RKA

Prerequisite: [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
git clone https://github.com/infinitywings/rka.git
cd rka
docker compose up -d
```

Open [http://localhost:9712](http://localhost:9712). The interactive REST documentation is available at [http://localhost:9712/docs](http://localhost:9712/docs).

### 2. Install the MCP client

Install the small local RKA binary so an MCP-compatible AI client can reach the running service:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv tool install --force .
```

The binary is installed at `~/.local/bin/rka`. Client-specific configuration, verification, upgrades, and troubleshooting are documented in [INSTALL.md](INSTALL.md).

### 3. Begin a project

After connecting a client, ask it to list or create an RKA project and state the selected project at the beginning of the session. Every project-scoped operation uses an explicit project ID so work cannot silently land in the wrong project.

For a complete first-project walkthrough, see [USAGE_GUIDE.md](USAGE_GUIDE.md).

## Interfaces

| Interface | Best for | Documentation |
|---|---|---|
| **Web dashboard** | Browsing, reviewing, navigating, and direct editing | [User Manual](docs/USER_MANUAL.md) |
| **MCP** | AI-assisted research, writing, and execution workflows | [Installation](INSTALL.md), [Technical Reference](docs/TECHNICAL_REFERENCE.md) |
| **CLI** | Starting services, status, backup, credentials, and workspace bootstrap | [Technical Reference](docs/TECHNICAL_REFERENCE.md) |
| **REST API** | Custom integrations and application development | [Technical Reference](docs/TECHNICAL_REFERENCE.md), live `/docs` |
| **ChatGPT connector** | Authenticated access from ChatGPT to a local RKA instance | [Connector Guide](docs/CHATGPT_CONNECTOR.md) |
| **Writer skill** | Evidence-grounded manuscript framing, drafting, review, and revision | [`rka/skills/writer/`](rka/skills/writer/) |

## Architecture

The core distribution runs a FastAPI service and React dashboard, a background indexing worker, and an MCP adapter over a shared service layer. SQLite, FTS5, and sqlite-vec provide local persistence and retrieval. Server-side research interpretation is intentionally separated from storage: the connected Brain performs synthesis while RKA preserves, validates, and serves the structured record.

See [Architecture](docs/ARCHITECTURE.md) for the runtime model, data layers, provenance graph, MCP dispatch surface, search design, and extension boundaries.

## Roadmap

The next product milestones concentrate on reducing the cognitive load between doing research and communicating it:

1. **Knowledge smoothing and readiness** — improve the path from noisy journal entries to reviewed claims, clusters, research questions, and scoped publication arguments.
2. **Manuscript drafting workbench** — provide an interactive surface for discussing, navigating, editing, and auditing the paper spine and evolving draft.
3. **ARA interoperability** — define a semantic crosswalk and deterministic materialization path from RKA projects to standards-conforming agent-native artifacts.
4. **Dual-output evaluation** — test whether one longitudinal workflow can reduce authoring effort while improving paper traceability and ARA completeness.

The dependency-ordered plan lives in the repository [Roadmap](ROADMAP.md), with
active work tracked through [GitHub milestones](https://github.com/infinitywings/rka/milestones).
Roadmap items describe direction and should not be interpreted as released
features.

## Research

The working paper [*Framing Is Human: Researcher–Brain–Executor Architecture for AI-Assisted Research*](docs/paper/RKA-paper.pdf) describes RKA's architectural argument, design principles, and evaluation.

RKA is being developed for research workflows at UNC Charlotte. Feedback, comparative evaluations, interoperability experiments, and research collaborations are welcome.

## Documentation

| Document | Purpose |
|---|---|
| [Installation](INSTALL.md) | Complete local, MCP-client, Writer, and connector setup |
| [Usage Guide](USAGE_GUIDE.md) | End-to-end Brain, Executor, PI, and research workflows |
| [User Manual](docs/USER_MANUAL.md) | Concepts, dashboard operation, and researcher-facing reference |
| [Architecture](docs/ARCHITECTURE.md) | Design rationale, components, data model, and knowledge lifecycle |
| [Technical Reference](docs/TECHNICAL_REFERENCE.md) | CLI, MCP, REST, configuration, and development entry points |
| [Roadmap](ROADMAP.md) | Dependency-ordered milestones for the epistemic pipeline, workbench, and ARA interoperability |
| [Embedding Backends](docs/embedding_backends.md) | Local and OpenAI-compatible embedding configuration |
| [Credential Vault](docs/CRED_VAULT.md) | Secure credential storage and propagation |
| [ChatGPT Connector](docs/CHATGPT_CONNECTOR.md) | Authenticated remote MCP access |
| [Changelog](CHANGELOG.md) | Release history and compatibility notes |

## Development

RKA is a Python, FastAPI, SQLite, and React project. The repository's authoritative contributor instructions are in [CLAUDE.md](CLAUDE.md) and apply to any coding agent or human contributor.

Run the test suite through Docker:

```bash
docker compose exec rka pytest
```

Please preserve explicit project scoping, provenance links, actor attribution, service-layer boundaries, and the distinction between raw research records and revisable interpretations.

## License

RKA is available under the [MIT License](LICENSE).
