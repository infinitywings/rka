# ADR 0015: Establish the RKA Project GitHub organization

- **Status:** Accepted
- **Date:** 2026-08-28
- **Decision owner:** Chenglong Fu
- **Supersedes:** the account-placement and organization deferral in
  [ADR 0012](0012-rka-ecosystem-repository-boundaries.md)
- **Execution checklist:**
  [`../organization-migration-checklist.md`](../organization-migration-checklist.md)

## Context

RKA Core and RKA Writer now have distinct product boundaries and release
cadences. The active ecosystem also needs a stable public identity, shared
roadmap, project website, and future home for an install-friendly application.
Keeping those repositories under a personal namespace makes the project harder
to present as a coherent open-source effort and leaves ecosystem assets tied to
one product repository.

ADR 0012 intentionally deferred a GitHub organization while the product
boundaries were unsettled. Those boundaries are now clear: Core owns durable
research knowledge and retrieval; Writer is a separate downstream authoring
product; the future App owns installation and machine integration; Agentic is
shelved under ADR 0013.

## Decision

1. Create a GitHub organization with handle **`rka-project`** and display name
   **RKA Project**.
2. The active repository structure is:

   | Repository | Responsibility |
   |---|---|
   | `.github` | Organization profile and shared brand masters |
   | `rka-core` | Durable research records, provenance, retrieval, integrity, REST, MCP, CLI, and the maintenance UI |
   | `rka-writer` | Researcher-in-the-loop manuscript workbench and academic-writing workflows |
   | `rka-project.github.io` | Public project website |
   | `rka-app` | Future installer, service lifecycle, upgrades, rollback, and AI-client configuration |

3. Transfer the existing Writer repository first as a migration rehearsal.
   Protect its current uncommitted development work before transfer. Then
   transfer and rename the current Core repository from `infinitywings/rka` to
   `rka-project/rka-core`.
4. Do not create an umbrella `rka` repository. The organization profile,
   website, and organization-level roadmap provide the ecosystem entry points.
5. Do not create an Agentic repository. Historical Agentic branches and design
   records remain preserved but are not presented as an active product.
6. Move ecosystem brand masters to the organization `.github` repository.
   Individual products may retain versioned copies required by their packages
   and interfaces.
7. Create an organization-level **RKA Ecosystem Roadmap** covering Core,
   Writer, App, Site, and shelved work. Repository issue trackers remain the
   authority for implementation details.
8. Initially use the GitHub Free plan. Keep base repository permission at
   `None`, restrict repository transfer and deletion to owners, require 2FA,
   and add a second trusted owner before the project depends on organization
   infrastructure for releases.

## Migration rules

- Preserve Git history, issues, pull requests, releases, stars, and redirects
  by using GitHub repository transfer rather than creating replacement repos.
- Never recreate `infinitywings/rka` after transfer; doing so would break the
  old repository redirect.
- Update local remotes and hard-coded namespace references immediately after
  each transfer.
- Reverify branch rules, required checks, Actions permissions, environments,
  secrets, deploy keys, Pages, packages, and release identities after transfer.
- Treat the website and `.github` repositories as independent products with
  their own reviewable changes. They do not become Core runtime dependencies.
- Do not advertise unreleased installation paths or Writer behavior as current
  Core capability.

## Consequences

### Positive

- RKA has a durable project identity independent of one repository name.
- Core, Writer, the website, and the future App can evolve independently while
  sharing a coherent public roadmap and visual language.
- Repository names now communicate product boundaries directly.
- Community, security, and contribution material can be maintained once at the
  organization level where appropriate.

### Costs and risks

- Repository URLs, badges, manifests, installation instructions, OIDC trust,
  package links, and local remotes require coordinated updates.
- GitHub Pages URLs do not inherit repository-transfer redirects.
- A single-owner organization is an availability risk until a second trusted
  owner is added.
- Transfer sequencing must protect Writer's current uncommitted work and avoid
  interrupting Core users.

## Relationship to earlier decisions

ADR 0012 remains authoritative for Core and Writer ownership, authority
boundaries, public-contract isolation, and non-destructive state migration.
ADR 0013 continues to shelve Agentic. ADR 0014 continues to place end-user
installation and machine integration in the future `rka-app` product.
