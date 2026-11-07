# Verify the image

Every image published by the project's workflow has two signed attestations,
made with GitHub's artifact attestations (Sigstore):

- **build provenance** (SLSA), on the multi-platform image: which workflow,
  commit and repository built it;
- **SBOM** (SPDX), on each platform's image: every package it contains.

Verify them with the GitHub CLI before you deploy:

```sh
# Provenance: built by this repository's workflow, from this repository.
gh attestation verify oci://ghcr.io/housecairn/housecairn:X.Y.Z \
  --repo HouseCairn/housecairn \
  --signer-workflow HouseCairn/housecairn/.github/workflows/image.yml

# SBOM of the linux/amd64 image (use its digest, shown by the first command
# below), and its list of packages.
docker buildx imagetools inspect ghcr.io/housecairn/housecairn:X.Y.Z
gh attestation verify oci://ghcr.io/housecairn/housecairn@sha256:<amd64 digest> \
  --repo HouseCairn/housecairn --predicate-type https://spdx.dev/Document/v2.3
```

Write the repository as `HouseCairn/housecairn`, the exact name recorded in
the signing certificate. A successful verification ends with
`✓ Verification succeeded!`. The
attestations are also stored in the registry next to the image.

How the image is built and signed is in
[ADR 0015](../adr/0015-container-image-and-publication.md).
