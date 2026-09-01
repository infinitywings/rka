# Core container image publication

RKA Core's canonical container name is:

```text
ghcr.io/rka-project/rka-core
```

The image becomes an installation input only after a successful stable GitHub
Release workflow and the read-back checks below. A source checkout or an image
tag by itself is not proof that a public release image exists.

## Publication contract

The `publish-container` workflow runs only for a published, non-prerelease
GitHub Release. It fails unless:

- the release commit is contained in `main`;
- the tag is exactly `v<project.version>` and the version is stable SemVer;
- an isolated preflight container becomes healthy without publishing a host
  port or using persistent host storage;
- the pushed OCI index contains both `linux/amd64` and `linux/arm64`;
- the published digest starts successfully under the same isolated smoke; and
- the GitHub provenance attestation can be verified.

The workflow publishes version, major/minor, major, and `latest` tags for human
navigation. Those tags are mutable references. Deployment records and RKA App
release configuration must use the immutable manifest reference emitted in the
workflow summary:

```text
ghcr.io/rka-project/rka-core@sha256:<manifest-digest>
```

BuildKit also publishes SBOM and provenance material. GitHub records a separate
artifact attestation bound to the same manifest digest.

## First-publication read-back gate

GitHub Container Registry package visibility can depend on organization and
repository package settings. After the first successful workflow:

1. Read the digest from the completed workflow, not from a local tag.
2. Confirm the package is linked to `rka-project/rka-core` and is public.
3. From a logged-out environment, pull the exact digest without credentials.
4. Inspect the index and confirm `linux/amd64` and `linux/arm64` are present.
5. Verify the attestation against the Core repository.
6. Only then update RKA App's release configuration to pin that digest.

Example read-only checks:

```bash
docker pull ghcr.io/rka-project/rka-core@sha256:<manifest-digest>
docker buildx imagetools inspect \
  ghcr.io/rka-project/rka-core@sha256:<manifest-digest>
gh attestation verify \
  oci://ghcr.io/rka-project/rka-core@sha256:<manifest-digest> \
  --repo rka-project/rka-core
```

Do not change package visibility as part of an automated retry. Making a GHCR
package public is an explicit operator decision and cannot be reversed to
private under GitHub's current visibility model.

## Local validation

Core CI builds the production Dockerfile and invokes:

```bash
python scripts/container_image_smoke.py \
  --image rka-core:ci \
  --expected-version 3.0.0
```

The smoke test creates one uniquely named, labelled container, publishes no
host ports, overlays `/data` with tmpfs, verifies `/api/health`, and removes
only the container whose ownership label it created. It does not use the stock
Compose project, the live `rka-server` or `rka-worker` names, port 9712, or the
`rka_rka-data` volume.
