# 0019. Property-based tests with Hypothesis

- Status: accepted
- Date: 2026-11-07
- Extends: [0014](0014-continuous-integration-and-supply-chain.md)

## Context

The tests check chosen examples. The code that reads what someone else wrote
also has to hold for input nobody thought of: request headers and JSON
bodies, the `next` parameter of the sign-in page, the claims of an identity
provider, and, in the CI scripts, pull request titles, commit messages and Git
refs that anyone opening a pull request controls.

OpenSSF Scorecard reports no fuzzing for the repository. Its Fuzzing check
(`checks/raw/fuzzing.go` in ossf/scorecard, read at `b753b11`, 2026-11-07)
recognises ClusterFuzzLite, OSS-Fuzz, and for Python only a line
`import atheris`; property-based testing is recognised for other languages
(QuickCheck, fast-check, FsCheck…) but not Python's Hypothesis
([ossf/scorecard#4549](https://github.com/ossf/scorecard/issues/4549) is open;
the pull request that added it, #4957, was closed without being merged). The
tests below are worth having for what they find; they do not change that
score.

## Decision

**Hypothesis** (MPL-2.0, already on the list of allowed licenses of ADR 0014)
is a development dependency (`dev` group), not shipped in the image. Its only
dependency is `sortedcontainers` (Apache-2.0). The locked version was public
for at least 7 days, as Dependabot's cooldown asks of updates.

Two test modules hold the properties, each stated in the docstring of its test:

- `tests/test_properties_tools.py`, without a database: pull request titles,
  `Signed-off-by` trailers and `git log` parsing, image tags of a Git ref,
  external URLs in templates, and the container entry point (integer
  variables, Host header of the health check, exit status, unknown commands);
- `tests/test_properties_web.py`: identity provider claims, the
  `Authorization` header of the API, `PATCH` of a home, and the redirection
  after sign-in. They run on both databases, SQLite and PostgreSQL.

Two profiles, set in `tests/conftest.py` and chosen by `HYPOTHESIS_PROFILE`:

| Profile | Where | Examples per test | Other settings |
| --- | --- | --- | --- |
| `ci` | the test jobs of `ci.yml` | 50 | derandomized (the same examples on every run), no example database, no deadline |
| `dev` | default, locally | 300 | random, failing examples kept in `.hypothesis/` (ignored by Git) and replayed first |

CI runs pytest with `--hypothesis-show-statistics`, so the log shows the
profile and the number of examples of each property.

A property that finds a bug gets its fix in a commit of its own. The first run
found three: OIDC claims that are not a JSON object raised an exception
during sign-in, `image_tags.py` accepted a ref or a SHA followed by a line
break, and `check_external_urls.py` missed URLs with a port, a query or no path.

## Consequences

- The `ci` profile adds about ten seconds to each test job; a run is
  reproducible, so a failure in CI fails again locally with
  `HYPOTHESIS_PROFILE=ci`.
- Being derandomized, CI explores the same 50 examples each time; the `dev`
  profile, run by contributors, explores new ones.
- If Scorecard learns to recognise Hypothesis, the Fuzzing check rises with no
  change here. Otherwise, a fuzzing harness with Atheris (which can drive these
  same Hypothesis tests) would be a separate decision.
