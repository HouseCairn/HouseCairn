# Contributing to Housecairn

Thank you for your interest. Housecairn is in early development: before
starting significant work, please open an issue to discuss it.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Before your pull request can be merged

1. **Sign the CLA.** Every contributor signs the
   [Contributor License Agreement](CLA.md) once. You keep the copyright of your
   work. On your first pull request, the CLA Assistant bot posts a comment;
   read the CLA, then sign it by posting this comment on the pull request,
   exactly as written:

   ```text
   I have read the CLA Document and I hereby sign the CLA
   ```

   The `CLA` check then turns green. Your signature is recorded in this
   repository, on the `cla-signatures` branch, and covers all your later pull
   requests. If the check does not update, comment `recheck`.
2. **Sign off every commit** with the
   [Developer Certificate of Origin](https://developercertificate.org/):

   ```sh
   git commit -s -m "fix: handle empty schedules"
   ```

   This adds a `Signed-off-by: Your Name <you@example.com>` line. The
   `Signed-off-by` check requires it on every commit of the pull request
   (merge commits excepted), with the same address as the commit author. To
   fix commits you already pushed, run `git rebase --signoff origin/main`,
   then `git push --force-with-lease`.

## Local development

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 if
needed) and, to update translations, GNU gettext.

```sh
uv sync --locked                 # create .venv with the locked dependencies
cp .env.example .env             # DEBUG=true for development
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
uv run python manage.py qcluster # background task worker, in another terminal
```

The application is at <http://localhost:8000/>, the API documentation at
`/api/docs/` once signed in. Architecture decisions are in
[docs/adr/](docs/adr/README.md); read them before changing the structure.

Checks to run before opening a pull request:

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy src scripts
uv run pytest --cov=housecairn --cov-fail-under=85
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py spectacular --validate --fail-on-warn --file /dev/null
uv run python manage.py build_design_tokens --check
uv run python manage.py check_translations --sources
uv run python scripts/check_external_urls.py
```

To run the tests on PostgreSQL as well, install the driver and point
`DATABASE_URL` at a server where the user may create databases:

```sh
uv sync --locked --extra postgres
DATABASE_URL=postgres://housecairn:***@localhost:5432/housecairn \
  uv run --extra postgres pytest
```

`manage.py` commands other than tests need `DEBUG=true` (from `.env`) or a
`SECRET_KEY`. To check the production settings:

```sh
set -a; . deploy/production.env.example; set +a
SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(50))')" \
  HOUSECAIRN_DATA_DIR=./data uv run python manage.py check --deploy --fail-level WARNING
```

When you change `design/tokens.json`, run `manage.py build_design_tokens` and
commit the generated `tokens.css`. When you add or change a user-facing string,
update the French catalog as described in
[ADR 0013](docs/adr/0013-internationalization.md).

## Checks run on every pull request

GitHub runs these checks on each pull request; all must pass before the
maintainer merges it ([ADR 0014](docs/adr/0014-continuous-integration-and-supply-chain.md)):

| Check | What it verifies |
| --- | --- |
| `Lint and types` | `uv sync --locked`, ruff lint and format, mypy. |
| `Tests (SQLite)`, `Tests (PostgreSQL)` | The test suite and at least 85 % coverage, on both databases. |
| `Django and repository checks` | Migrations, OpenAPI schema, production `check --deploy`, design tokens, translations, no external URL in templates and static files. |
| `zizmor` | Security of the GitHub Actions workflows. |
| `Dependency review` | New dependencies: no known vulnerability of moderate severity or more, a license compatible with AGPL-3.0-only. |
| `Conventional Commits title` | The pull request title. |
| `Signed-off-by` | The sign-off of every commit. |
| `CLA` | Every author has signed the CLA. |

Workflows of a pull request from outside the project only start once the
maintainer approves them.

## Pull requests

- **Small and focused.** One topic per pull request. Unrelated refactoring or
  reformatting goes in its own pull request.
- **Title in [Conventional Commits](https://www.conventionalcommits.org/)
  format**, for example `feat: add yearly recurrence` or
  `fix(schedule): skip archived rooms`. Pull requests are merged by squash: the
  title and description become the commit message on `main`.
- **Documentation in the same pull request as the code** it describes.
- **Fill in the pull request template**, including what you actually ran to
  verify the change.
- All user-facing text is in English in the code and goes through translation
  functions; no hard-coded strings.

## AI-assisted contributions

AI tools are welcome, under these rules:

- **Declare the tool and model** you used in the pull request template.
- **A human is responsible for the pull request.** You must understand every
  line you submit, have reviewed it yourself, and be able to answer questions
  about it.
- **No unsolicited pull requests from autonomous agents.** Pull requests
  opened by an agent without a human author who answers for them will be
  closed.

## Security issues

Do not report vulnerabilities in public issues or pull requests. See
[SECURITY.md](SECURITY.md).
