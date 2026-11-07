# Contributing to Housecairn

Thank you for your interest. Housecairn is in early development: before
starting significant work, please open an issue to discuss it.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Before your pull request can be merged

1. **Sign the CLA.** Every contributor signs the
   [Contributor License Agreement](CLA.md) once. The CLA Assistant bot asks you
   to do so in your first pull request. You keep the copyright of your work.
2. **Sign off every commit** with the
   [Developer Certificate of Origin](https://developercertificate.org/):

   ```sh
   git commit -s -m "fix: handle empty schedules"
   ```

   This adds a `Signed-off-by: Your Name <you@example.com>` line. Pull requests
   with unsigned-off commits cannot be merged.

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
uv run mypy src
uv run pytest --cov=housecairn --cov-fail-under=85
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py spectacular --validate --fail-on-warn --file /dev/null
uv run python manage.py build_design_tokens --check
uv run python manage.py check_translations --sources
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
