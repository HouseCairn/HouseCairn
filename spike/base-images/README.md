# Spike: a smaller base image

Throwaway experiment, not part of the product: can the container image use a
smaller base than `python:3.13-slim-trixie`, with fewer tools and fewer
vulnerability reports? The production `Dockerfile` and the `Image` workflow are
not changed. The maintainer decides on the numbers; this directory is deleted
or replaced by an ADR afterwards.

| Candidate | Final stage | Virtual environment built on |
| --- | --- | --- |
| `current` | `python:3.13.18-slim-trixie` (production `Dockerfile`) | the same image |
| `distroless` | `gcr.io/distroless/python3-debian13:nonroot` (Debian's python3.13) | `debian:trixie-slim` with Debian's python3.13 |
| `wolfi` | `scratch` + Wolfi packages installed by apk (`python-3.13`) | `cgr.dev/chainguard/wolfi-base` with `python-3.13` |
| `chainguard` | `cgr.dev/chainguard/python:latest` | `cgr.dev/chainguard/python:latest-dev` |

Static files and translations are built as in production in every candidate.

`.github/workflows/spike-base-images.yml` builds each candidate on amd64 and
arm64 (native runners), then `measure.sh` measures it and the `Report` job
writes `report.md` (artifact `spike-base-images-report`, also in the job
summary):

- sizes: layers saved by `docker save`, compressed with gzip level 6;
- Grype (same version as `image.yml`): findings by severity, fixable ones, and
  the gate of the Image workflow (fixable High or Critical); also for the bare
  base image;
- Syft: packages in the SBOM;
- shell, package manager and pip present in the file system, image user;
- a real run without any shell in the container: health check, migrations,
  `/healthz`, sign-in page, photos uploaded and read back with Pillow, the
  backup command, read-only root file system, then the same against a
  PostgreSQL service of the job;
- build time on a fresh runner.

Start it from the Actions tab (`Spike base images`, `Run workflow`) on the
spike branch, or push to that branch.
