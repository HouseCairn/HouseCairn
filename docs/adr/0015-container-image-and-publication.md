# 0015. Container image and its publication

- Status: accepted
- Date: 2026-11-07

## Context

Housecairn is installed by people who run a home server, mostly with Docker
Compose, on x86 machines and on ARM boards. They expect one image that works
with SQLite out of the box and with PostgreSQL if they want it (ADR 0008, 0012),
and they will not read a hardening guide. The image must also be verifiable:
anyone should be able to check that a published image was built by this
repository's workflow from a given commit, and what it contains.

## Decision

### Base image

`python:3.12.<patch>-slim-trixie`, the official Python image on Debian 13
slim, pinned by digest with its tag on the same line; both stages use the same
digest so the virtual environment built in the first runs in the second.
Debian rather than Alpine: Debian's glibc takes the `manylinux` wheels, the
format every Python package with compiled code publishes first, for amd64 and
arm64. Today every locked runtime dependency with compiled code (`cffi`,
`cryptography`, `psycopg-binary`, `charset-normalizer`, `pyyaml`, `rpds-py`)
also publishes `musllinux` wheels for both, but that is not guaranteed for the
next dependency, and a missing wheel means a compiler and build headers in the
image build. musl also differs from glibc in ways that surface at run time
(DNS resolution, locales, thread stack size), which the tests on the runner,
a glibc system, would not see. A distroless base was not chosen:
the entry point needs a Python interpreter matching the one of the virtual
environment, and the slim image's small set of Debian packages is scanned
and patched by Debian.

### Build

Two stages:

1. **build**: uv (copied from its official image, same version as the CI)
   installs the locked dependencies with `uv sync --locked --no-dev --extra
   postgres --no-install-project` into `/app/.venv`, with bytecode compiled.
   The project is not installed as a package: its source is on `PYTHONPATH`
   (`/app/src`), so no unlocked build backend is downloaded. Then design
   tokens (`build_design_tokens`) and translations (`compilemessages`, GNU
   gettext installed in this stage only) are generated from their sources,
   and static files are collected with `CompressedManifestStaticFilesStorage`
   (hashed names, compressed copies).
2. **final**: the same base, without its `pip` (unused at run time, and the
   source of most scanner findings), a system user and group `housecairn`,
   UID/GID **10001**, and `/app` copied from the build stage, owned by root,
   hence read-only for the application.

`.dockerignore` excludes everything, then lets in only `pyproject.toml`,
`uv.lock`, `LICENSE`, `NOTICE`, `manage.py`, `design/` and `src/`: no `.git`,
no test, no local data or `.env` file can reach the image. The OCI labels
`source`, `licenses` (`AGPL-3.0-only`), `version` and `revision` are set from
build arguments.

### Runtime dependencies added

ADR 0001 is amended by this record:

| Package | Why |
| --- | --- |
| gunicorn | Production WSGI server, pure Python, MIT. Started with its control socket disabled (it would need a writable path) and its worker heartbeat files in `/dev/shm`. |
| whitenoise | Serves the collected static files from the application, with long-lived `immutable` cache headers for hashed names and precompressed copies. Keeps the image a single process tree, without a web server in front only for static files. MIT. |

### Run time

- **Single writable place.** Everything written at run time goes to `/data`:
  SQLite database, uploaded files (`/data/media`), the secret key, backups.
  The rest of the file system works mounted read-only (`--read-only`), with
  `/tmp` as a `tmpfs`. Python does not write bytecode at run time
  (`PYTHONDONTWRITEBYTECODE`; it is compiled at build time).
- **Entry point** `python -m housecairn.entrypoint` (`src/housecairn/entrypoint.py`,
  tested in `tests/test_entrypoint.py`):
  - creates `/data/media` and fails with an explanation if `/data` is not
    writable by the application user;
  - sets the process umask to `077`: files in `/data` are readable by the
    application user only;
  - uses `SECRET_KEY` from the environment if set, otherwise
    `/data/secret_key`, created on first start with 50 random bytes
    (`secrets.token_urlsafe`), mode 600, then reused;
  - applies the migrations (`migrate --noinput`), then starts gunicorn and the
    django-q2 worker (`qcluster`) and supervises them: if either stops, the
    other gets SIGTERM and the container exits with a non-zero status (128 +
    signal number if it was killed), so the container's restart policy applies;
    SIGTERM or SIGINT stops both, waits up to `HOUSECAIRN_STOP_TIMEOUT`
    seconds (20 by default) then kills what remains, and exits 0. As PID 1, it
    also collects orphaned processes. A tiny supervisor in the entry point was
    preferred to supervisord or s6: two processes, no configuration file, and
    behaviour covered by tests.
  - `healthcheck`, `backup` (SQLite online backup API into `/data/backups/`)
    and `manage <command>` subcommands.
- **No account is created.** The first administrator comes from the existing
  sign-in paths (ADR 0007): the first OpenID Connect sign-in, optionally pinned
  to `HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL`, or `manage createsuperuser`.
- **Health check.** `HEALTHCHECK` runs `entrypoint healthcheck`, which requests
  `/healthz` on the loopback with a host name taken from `ALLOWED_HOSTS`; the
  endpoint answers only `{"status": "ok"}` and needs no authentication
  (ADR 0012).
- **Proxy headers.** gunicorn passes `X-Forwarded-Proto` from any peer
  (`--forwarded-allow-ips=*`): the address of a reverse proxy in a container
  network is not known in advance. Whether that header is trusted is decided
  by Django only, with `HOUSECAIRN_BEHIND_TLS_PROXY` (ADR 0012).

### Workflow `image.yml`

| Job | Trigger | Permissions | What it does |
| --- | --- | --- | --- |
| `Container image` | pull request, push to `main`, tag `v*` | `contents: read` | Builds the image for amd64 and runs `.github/scripts/image-smoke.sh` on it, with SQLite then with PostgreSQL: started with `--read-only --cap-drop ALL --security-opt no-new-privileges`, `/tmp` in memory and an empty volume; healthy; `/`, the sign-in page and a hashed static file answer; user 10001; writes outside `/data` and `/tmp` refused; secret key mode 600; clean stop on SIGTERM; restart on the same volume keeps the database and the key and applies no migration; killing the task worker stops the container. Validates `compose.yaml`. Scans the image with Grype. |
| `Container image (code scanning)` | same, except pull requests from forks and Dependabot | `security-events: write` | Uploads the Grype SARIF of the previous job to code scanning. Runs no code of the pull request. |
| `Container image (multi-arch build)` | pull request | `contents: read` | Builds `linux/amd64` and `linux/arm64` with provenance and SBOM, as the publication does, without pushing. |
| `Publish image` | push to `main`, tag `v*`, after `Container image` passed | `contents: read`, `packages: write`, `id-token: write`, `attestations: write` | Builds and pushes both platforms to GHCR, then attests provenance and SBOMs. |

**Multi-architecture**: QEMU emulation on the amd64 runner (the
`tonistiigi/binfmt` image, pinned by digest, run with `docker run`) and a
`docker-container` BuildKit builder (`moby/buildkit`, pinned by digest). The
image only installs prebuilt wheels and runs Python, so emulation is fast
enough, and one `docker buildx build --platform linux/amd64,linux/arm64`
produces the multi-platform image and its attestations in one step. Native
arm64 runners were not chosen: they would need one job per architecture, an
artifact per digest and a merge job, for a build of a few minutes.

**Tags** (`scripts/image_tags.py`, tested): on `main`, `edge` and
`sha-<7 hex>`; on a tag `vX.Y.Z`, `X.Y.Z`, `X.Y`, `latest` and `sha-<7 hex>`;
on a pre-release tag `vX.Y.Z-<pre>`, `X.Y.Z-<pre>` and `sha-<7 hex>` only.
Nothing is published from a pull request or another branch.

**Provenance and SBOM.** BuildKit generates SLSA provenance
(`--provenance=mode=max`) and an SPDX SBOM per platform (`--attest
type=sbom`, with the `docker/buildkit-syft-scanner` image pinned by digest),
stored with the image. The workflow then signs them with GitHub artifact
attestations (Sigstore, keyless, through the job's OIDC token): build
provenance on the multi-platform index digest, and the SPDX SBOM of each
platform, extracted with `docker buildx imagetools inspect`, on that
platform's digest. Attestations are also pushed to the registry. They are
checked with `gh attestation verify` (docs/install.md). Artifact storage
records are not created (`create-storage-record: false`), so the job needs no
`artifact-metadata` permission.

The card that specified this lot asked for `actions/attest-build-provenance`
and `actions/attest-sbom`. Both are now wrappers of **`actions/attest`**,
which their own documentation asks to migrate to (`attest-sbom`'s README
announces its deprecation); this workflow uses `actions/attest` directly, with
the same inputs.

**Vulnerability scan: Grype** (Anchore), installed from its GitHub release
archive whose SHA-256, taken from the release's checksums file, is pinned in
the workflow. Not Trivy: its release binary and its GitHub actions were
compromised in March 2026 (CVE-2026-33634, GHSA-69fq-xp46-6x23); Grype does
the same job with an equivalent database. The `Container image` job fails if
the image has a vulnerability of **high or critical** severity **with a fix
available** (`--only-fixed --fail-on high`); every finding, fixed or not, goes
to code scanning (category `container-image`). A vulnerability without a fix
does not block a release: there is nothing to update to, and code scanning
keeps it visible.

**Versions and cooldown.** The tools pinned in the workflow (Grype, BuildKit,
binfmt, the SBOM scanner) were chosen among releases public for at least
seven days, as the Dependabot cooldown of ADR 0014 does for dependencies. The
Python base image digest is the latest of its tag: those rebuilds carry Debian
security updates. Dependabot updates the `FROM` lines (`docker` ecosystem) and
the PostgreSQL image of `compose.yaml` (`docker-compose` ecosystem). The
pinned tools of `image.yml` (environment variables) and the PostgreSQL image of
`ci.yml` and `image-smoke.sh` are updated by hand, together.

### Third-party actions

None. `image.yml` uses only actions published by GitHub: `actions/checkout`,
`actions/upload-artifact` v7.0.2, `actions/download-artifact` v8.0.2,
`actions/attest` v4.2.2 and `github/codeql-action/upload-sarif`. QEMU,
BuildKit and the registry login go through the `docker` command line rather
than Docker's actions.

### Checks to add to the `main` ruleset

Once each has passed once on GitHub:

- `Container image`
- `Container image (multi-arch build)`

Not required: `Container image (code scanning)` (skipped for forks and
Dependabot), `Publish image` (never runs on a pull request).

## Consequences

- One image, `ghcr.io/housecairn/housecairn`, for both databases and both
  architectures; an instance's state is the `/data` volume and nothing else.
- A host directory mounted on `/data` must belong to `10001:10001`.
- What only happens after a merge to `main` cannot be tested on a pull
  request: the push to GHCR, the attestations and the first publication of the
  package (its visibility and its link to the repository are set once, by the
  maintainer, after the first push).
- A fixable high or critical vulnerability in the base image or a dependency
  blocks pull requests until it is updated, which Dependabot proposes.
- The `X.Y` and `latest` tags move to the most recently published release,
  even if it is a patch of an older line.
