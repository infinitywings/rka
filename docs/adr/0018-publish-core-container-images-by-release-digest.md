# ADR 0018: Publish Core container images by release digest

- **Status:** Accepted
- **Date:** 2026-09-01

## Context

RKA App needs a released Core image without copying Core source or depending on
Core internals. A mutable image tag alone is not a sufficient dependency: it
does not identify one build, and a failed or unreviewed branch build must not
become an installation input.

The Core Dockerfile is already part of the independent Core CI gate. What is
missing is a release-only publication path with explicit source, architecture,
runtime, and provenance checks.

## Decision

1. Core publishes `ghcr.io/rka-project/rka-core` only from a non-prerelease
   GitHub Release whose tag is contained in `main`.
2. The release tag must be exactly `v<project.version>`. The first workflow
   accepts stable SemVer only; prerelease container publication requires a
   separate reviewed extension.
3. The workflow builds Linux `amd64` and `arm64` images. It first builds and
   starts an isolated `amd64` preflight image with no host port and tmpfs data,
   then publishes the multi-architecture index and starts the published digest
   once more.
4. GitHub Actions dependencies are pinned to immutable commit SHAs. Published
   images carry OCI source, license, version, and revision metadata, a BuildKit
   SBOM/provenance record, and a GitHub artifact attestation.
5. Version, major/minor, major, and `latest` tags are navigation conveniences.
   Downstream release configuration, including RKA App, must use the manifest
   digest returned by the successful workflow.
6. The first publication is not complete until package visibility and an
   anonymous digest pull are read back. Changing a package to public is a
   separate, irreversible operator action and is never inferred from a
   successful push.

## Consequences

- Core owns and can audit the image containing its code and dependencies.
- RKA App can consume a precise external artifact while retaining a separate
  repository and release cadence.
- A GitHub Release may take longer because it includes an `arm64` build,
  isolated runtime probes, manifest validation, SBOM generation, and
  attestation verification.
- The Dockerfile pins upstream multi-architecture base manifests, verifies the
  downloaded sqlite-vec source archive, and installs Python dependencies from
  the reviewed lock. Moving upstream tags cannot silently change those inputs.
- System package repositories remain time-varying, so the workflow provides
  substantially stronger input integrity without claiming bit-for-bit
  reproducible rebuilding.
