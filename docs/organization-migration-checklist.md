# RKA Project organization migration checklist

This checklist moves the active RKA ecosystem from the personal
`infinitywings` namespace to the `rka-project` GitHub organization without
losing repository state or local work.

## 1. Establish the organization

- [ ] Create the free `rka-project` organization with display name **RKA Project**.
- [ ] Set the public description, website, contact email, and organization avatar.
- [ ] Set base repository permission to `None`.
- [ ] Restrict repository deletion and transfer to owners.
- [ ] Require two-factor authentication.
- [ ] Add a second trusted owner before release automation depends on the organization.
- [ ] Create `core-maintainers`, `writer-maintainers`, and `site-maintainers` teams when a second contributor needs access.

## 2. Create shared project surfaces

- [ ] Create `.github` and publish `profile/README.md` plus shared brand masters.
- [ ] Create `rka-project.github.io` and publish the reviewed project homepage.
- [ ] Create the organization-level **RKA Ecosystem Roadmap**.
- [ ] Use Product, Horizon, Status, and Release gate fields.
- [ ] Add Core Reliability, Writer Platform, Distribution, Website & Community, Releases, and Shelved views only as they become useful.

## 3. Protect and transfer Writer

- [ ] Preserve the local `codex/integrate-academic-reviewers` work in reviewable commits and push it before transfer.
- [ ] Record Writer's default branch, branch rules, Actions settings, secrets, environments, issues, releases, and deploy keys.
- [ ] Transfer `infinitywings/rka-writer` to `rka-project/rka-writer`.
- [ ] Update local remotes and every Core/Writer cross-reference.
- [ ] Verify clone, tests, CI, issues, releases, redirects, and permissions.

## 4. Transfer and rename Core

- [ ] Record Core's default branch, branch rules, Actions settings, secrets, environments, issues, releases, packages, webhooks, and deploy keys.
- [ ] Transfer and rename `infinitywings/rka` to `rka-project/rka-core`.
- [ ] Do not recreate `infinitywings/rka`.
- [ ] Update local remotes and hard-coded `infinitywings/rka` references.
- [ ] Update plugin manifests, badges, documentation, source links, and install instructions.
- [ ] Run the complete Core test gate and startup smoke test from the new remote state.
- [ ] Verify old repository URLs redirect and the new clone URL works.

## 5. Release and package follow-up

- [ ] Rebind future PyPI trusted publishing to `rka-project/rka-core` before the first public package release.
- [ ] Use `ghcr.io/rka-project/rka-core` for future container publication.
- [ ] Reassociate GitHub Packages with the transferred repository if needed.
- [ ] Verify any OIDC subject, environment, or repository-owner conditions after transfer.
- [ ] Keep repository secrets scoped narrowly until an organization-wide secret is demonstrably needed.

## 6. Close-out

- [ ] Confirm both local checkouts are clean and point to the new remotes.
- [ ] Confirm the organization profile and website link only to existing or explicitly marked in-development products.
- [ ] Confirm the roadmap represents Agentic as shelved rather than active.
- [ ] Record the final organization, repository, website, and roadmap URLs in the RKA development project.
- [ ] Close or update migration issues only after the corresponding live state is read back and verified.
