# Instructions for coding agents

This file is for AI coding agents working on HouseCairn. It points to the
rules; it does not repeat them. Read the linked files before you change
anything.

- **Contribution rules:** [CONTRIBUTING.md](CONTRIBUTING.md). It covers the
  CLA, the sign-off of every commit, local setup, the checks to run and the
  pull request format.
- **Screens:** the [design guide](docs/developer/design-guide.md) says where a
  screen goes, where its back link and forms lead, and how its actions behave.
  Follow its checklist in the pull request.
- **Decisions:** the architecture decision records in
  [docs/adr/](docs/adr/README.md). Read the relevant ones before changing a
  structure; a change that contradicts one needs a new record.

## Rules that are easy to miss

Each is explained where it is linked.

- Pull request titles and commits follow Conventional Commits, and every commit
  has a `Signed-off-by` line
  ([CONTRIBUTING.md](CONTRIBUTING.md#before-your-pull-request-can-be-merged)).
- Release notes: one fragment per pull request under
  `docs/release-notes/unreleased/`, never an edit of `docs/release-notes.md`
  ([format](docs/release-notes/unreleased/README.md)).
- Translations: one catalog per Django app, regenerated with `makemessages`
  per app; never commit a `.mo` file
  ([CONTRIBUTING.md](CONTRIBUTING.md#local-development)).
- No screenshots, in the documentation or in CI
  ([CONTRIBUTING.md](CONTRIBUTING.md#documentation)).
- A test added for a fix or a feature must fail on the code without the change.
  Run the checks listed in [CONTRIBUTING.md](CONTRIBUTING.md#local-development)
  and report only what you ran.
- The repository is public: no secret, no personal data, no detail of a private
  infrastructure in code, commits, issues or pull requests.

## Publishing

You never merge a pull request and never push to `main`. The maintainer's own
agents publish through `scripts/hc.py`, a wrapper kept outside this repository
that sets the public commit identity and checks the diff for private data; any
other contributor uses plain `git`, as described in
[CONTRIBUTING.md](CONTRIBUTING.md). Declare the tool and model in the pull
request ([AI-assisted contributions](CONTRIBUTING.md#ai-assisted-contributions)).
