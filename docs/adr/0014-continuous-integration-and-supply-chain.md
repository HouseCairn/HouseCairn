# 0014. Continuous integration and supply-chain security

- Status: accepted
- Date: 2026-11-07

## Context

Housecairn is public from its first commit and is meant to be installed by
people who will not read its code. Every pull request, from a contributor, a
bot or the AI agent that develops it, must pass the same automatic checks
before the maintainer reads it, and the build chain itself must not be the weak
point: a workflow that runs untrusted code with a write token, an action moved
to another commit, or a dependency release compromised a day ago.

## Decision

### Workflows

All workflows are in `.github/workflows/`. Their job names are the status
checks of the pull requests; they are stable and only renamed together with
the `main` ruleset.

| Workflow | Trigger | What it checks |
| --- | --- | --- |
| `ci.yml` | pull request, push to `main` | `uv sync --locked`; ruff lint and format; mypy (`src`, `scripts`); pytest with coverage of at least 85 %, on SQLite and on PostgreSQL; `makemigrations --check`; `spectacular --validate --fail-on-warn`; `check --deploy --fail-level WARNING` with `deploy/production.env.example` and a key generated in the job; `build_design_tokens --check`; `check_translations --sources`; no external URL in templates and static files (`scripts/check_external_urls.py`, ADR 0011). |
| `zizmor.yml` | pull request, push to `main` | Static analysis of the workflows with zizmor. One job fails on any finding of medium severity or more; another uploads all findings (SARIF) to code scanning. |
| `dependency-review.yml` | pull request | New dependencies: fails on a known vulnerability of moderate severity or more, or on a license outside the allowed list below. |
| `pr-title.yml` | pull request opened, edited, synchronized, reopened | The title is a Conventional Commit (`scripts/check_pr_title.py`): it becomes the squash commit message on `main` and feeds the release notes. |
| `dco.yml` | pull request | Every non-merge commit has a `Signed-off-by` trailer with its author's address (`scripts/check_signoff.py`). |
| `cla.yml` | pull request target, issue comment | Every contributor has signed `CLA.md` (CLA Assistant Lite). |
| `scorecard.yml` | push to `main`, weekly | OpenSSF Scorecard; results published to the Scorecard API (README badge) and to code scanning. |

**CodeQL** runs through GitHub's default setup, enabled in the repository
settings. There is no CodeQL workflow in the repository: an advanced
configuration would conflict with the default setup.

The repository scripts in `scripts/` use the standard library only, so the
title and sign-off checks need neither uv nor the dependencies. They have their
own tests in `tests/test_ci_scripts.py`.

### Rules every workflow follows

- Every action is pinned to a full commit SHA, with its tag in a comment;
  container images are pinned by digest. The repository setting that requires
  SHA pinning enforces it.
- The workflow-level token has `contents: read` or no permission at all.
  Write permissions are granted per job, each with a comment saying why.
- Every `actions/checkout` sets `persist-credentials: false`.
- Values from the event (titles, commit SHAs) reach a `run:` step through
  `env:`, never through `${{ }}` inside the script.
- `concurrency` cancels outdated runs of the same pull request (except the CLA
  workflow, whose runs are queued so two signatures do not race).
- No `pull_request_target` workflow checks out or runs the code of a pull
  request. The only `pull_request_target` workflow is `cla.yml`, see below.

### Exceptions

- **`cla.yml` uses `pull_request_target` and `issue_comment`.** CLA Assistant
  Lite must comment on pull requests from forks, set a status and commit the
  signature, which the read-only token of a `pull_request` run cannot do. The
  workflow has no checkout step and runs no code from the pull request; the
  comment body is only compared to two fixed strings in `if:`. zizmor's
  `dangerous-triggers` finding is ignored by inline comments in this file
  only.
- **CLA Assistant Lite is archived.** Its upstream repository is archived
  (read-only), so it will get no fixes; zizmor reports it
  (`archived-uses`, ignored inline in `cla.yml` only). Its last release, v2.6.1,
  is pinned and still declares the `node20` runtime. It is kept because it
  stores signatures in this repository without any third-party service or
  personal token. Replacing it (a maintained fork or a small script in this
  repository) is a follow-up decision, to be taken before the first external
  contribution.
- **Merge commits are not checked for a sign-off.** They only bring in commits
  that are checked on their own; the sign-off check would otherwise fail on the
  merge commit created by GitHub's "Update branch" button.

### Third-party actions

The organization only allows actions published by GitHub and an explicit list
of other actions. Each one below is on that list for a reason:

| Action | Pinned version | Why |
| --- | --- | --- |
| `astral-sh/setup-uv` | v10.3.3 | Installs uv, the tool that locks and installs the dependencies (ADR 0001), with its cache. Published by uv's authors. |
| `zizmorcore/zizmor-action` | v0.8.1 | Runs zizmor, the workflow security analyser, and uploads its SARIF. Published by zizmor's authors. |
| `ossf/scorecard-action` | v2.5.0 | The only way to publish OpenSSF Scorecard results for the badge. Published by the OpenSSF. |
| `contributor-assistant/github-action` | v2.6.1 | CLA signatures stored in this repository (see Exceptions). |

Actions published by GitHub: `actions/checkout` v7.0.1,
`actions/dependency-review-action` v5.0.0, `github/codeql-action/upload-sarif`
v4.39.3.

### CLA signatures

Signatures are stored by the CLA workflow in `signatures/v1/cla.json` on the
`cla-signatures` branch, never on `main`. The branch must exist and stay
outside the `main` ruleset, because the workflow pushes to it with the
workflow token. The maintainer (`Robvred`), `dependabot[bot]` and
`github-actions[bot]` are exempt. A contributor signs by commenting, on their
pull request, exactly:

```text
I have read the CLA Document and I hereby sign the CLA
```

After a merge, the workflow locks the pull request conversation so the
signature comment cannot be edited or deleted.

### Licenses allowed for dependencies

Housecairn is distributed under AGPL-3.0-only. A dependency may be combined
with it if its license is permissive or a compatible copyleft:

- permissive: `0BSD`, `Apache-2.0`, `BlueOak-1.0.0`, `BSD-2-Clause`,
  `BSD-3-Clause`, `CC0-1.0`, `ISC`, `MIT`, `MIT-0`, `PSF-2.0`, `Python-2.0`,
  `Unlicense`, `Zlib`;
- weak copyleft: `LGPL-2.1-or-later`, `LGPL-3.0-only`, `LGPL-3.0-or-later`,
  `MPL-2.0` (its section 3.3 allows combining with the GNU licenses);
- strong copyleft compatible with AGPL-3.0: `GPL-3.0-only`,
  `GPL-3.0-or-later`, `AGPL-3.0-only`, `AGPL-3.0-or-later`.

An allow list, rather than a deny list, makes every other license, including
`GPL-2.0-only` (incompatible with the GPL-3.0 family), proprietary licenses and
licenses the dependency graph cannot identify, a decision recorded in an ADR
before the dependency is accepted. Every package locked when this decision was
taken has a license in this list.

### Dependency updates

Dependabot (`.github/dependabot.yml`) checks weekly the `uv`, `github-actions`
and `docker` ecosystems. Minor and patch updates are grouped per ecosystem;
commits are prefixed `chore(deps)`. A cooldown of 7 days (`cooldown:
default-days: 7`, supported for these three ecosystems by GitHub's Dependabot
options reference) delays version updates until a release has been public for
a week, which leaves time for a compromised release to be noticed and pulled.
Security updates are not delayed. The `docker` entry prepares lot J1-D and has
nothing to update until a Dockerfile exists. The PostgreSQL service image of
`ci.yml` is not seen by Dependabot: its tag and digest are updated by hand,
together.

### Checks required on `main`

These exact names are to be set as required status checks in the `main`
ruleset, once each has passed once on GitHub (a check that has never run blocks
every merge):

- `Lint and types`
- `Tests (SQLite)`
- `Tests (PostgreSQL)`
- `Django and repository checks`
- `zizmor`
- `Dependency review`
- `Conventional Commits title`
- `Signed-off-by`
- `CLA`

Not required: `zizmor (code scanning)` (skipped for pull requests from forks),
`Scorecard analysis` (runs on `main` only). CodeQL findings are enforced, if
wanted, with the ruleset's code scanning merge protection rather than a status
check.

## Consequences

- A pull request cannot be merged until its code, its workflows, its new
  dependencies, its title, its sign-offs and its author's CLA pass.
- A new third-party action needs an update of this record and of the
  organization's allowed list before its workflow can run.
- `cla.yml` takes effect once it is on `main`: `pull_request_target` workflows
  always run in the version of the base branch.
- The PostgreSQL tests need the `postgres` extra (`psycopg`, ADR 0001).
