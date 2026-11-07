# Security policy

## Supported versions

Housecairn has no released version yet. Until the first release, only the
`main` branch is considered, and nothing in it is meant for production use.

## Reporting a vulnerability

Please report vulnerabilities **only** through GitHub Private Vulnerability
Reporting: open the repository's **Security** tab and choose **Report a
vulnerability**.

Do **not** open a public issue, pull request or discussion about a
vulnerability.

You will receive an acknowledgement within 7 days. We will then work with you
on an assessment and a fix, and agree on a disclosure date. If you wish, you
will be credited in the published advisory.

## How the code is protected

These safeguards are described in
[ADR 0014](docs/adr/0014-continuous-integration-and-supply-chain.md):

- every pull request passes automatic checks before the maintainer reads it:
  tests, type checks, Django's deployment checks, and a review of new
  dependencies, which refuses known vulnerabilities of moderate severity or
  more;
- code scanning: CodeQL for the Python code, zizmor for the GitHub Actions
  workflows, and OpenSSF Scorecard for the repository's practices;
- GitHub Actions are pinned to full commit SHAs, workflow tokens are read-only
  unless a job needs more, and no workflow runs the code of a pull request with
  write access;
- Dependabot proposes dependency updates weekly, only once a release has been
  public for 7 days; security updates are not delayed.
