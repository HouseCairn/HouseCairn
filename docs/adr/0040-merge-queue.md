# 0040. Merge queue

- Status: accepted
- Date: 2026-11-08

## Context

The `main` ruleset requires pull requests to be up to date with `main` before
they merge (ADR 0014). After every merge, each open pull request has to receive
a merge commit from `main` ("Update branch") and run the whole CI again, one
after the other, before the next one can merge.

GitHub's merge queue does that work itself. It is available in any public
repository owned by an organization. The maintainer queues pull requests whose
checks pass; for each one, GitHub builds a temporary branch
`gh-readonly-queue/main/pr-<number>-<sha>` that holds `main`, the pull requests
ahead in the queue and this one, runs the required checks on it through the
`merge_group` event, and merges the entries in order. A required check that
does not report on that branch blocks the queue; a job that is skipped counts
as passing.

## Decision

`main` is merged through the merge queue. Every workflow that reports a required
check also runs on `merge_group` (`types: [checks_requested]`), and each check
keeps the same name, so the queue waits for the same thirteen checks as a pull
request. A test (`tests/test_ci_scripts.py`) fails when one of these workflows
loses the trigger.

What each check does on a queue entry:

| Check | On the queue entry |
| --- | --- |
| `Lint and types`, `Tests (SQLite)`, `Tests (PostgreSQL)`, `Django and repository checks` | Run as on a pull request, on the code of the entry: what lands on `main` is what was tested. |
| `zizmor` | Runs on the workflows of the entry. The SARIF upload job stays limited to `main` and to pull requests. |
| `Dependency review` | The action reads `merge_group.base_sha` and `head_sha` and reviews the dependencies of the entry against the advisories of that moment. |
| `Container image` | Builds, smoke-tests and scans the image of the entry. A vulnerability published while the pull request waited is found here. Its SARIF upload stays limited to `main` and to pull requests. |
| `Container image (multi-arch build)` | Builds amd64 and arm64 again. It takes about three minutes, like `Container image`, so the queue keeps it; skipping it would also turn it into a passing check without a build. |
| `Documentation` | Builds and checks the site of the entry. `Documentation (external links)`, not required, does not run on the queue: an outage elsewhere must not hold it up. |
| `Conventional Commits title` | Reads the title of the queued pull request again from the API and checks it. A title edited after queuing, which becomes the squash commit message, is still checked before it reaches `main`. |
| `Signed-off-by` | Reads the queued pull request from the API, fetches its head (`refs/pull/<n>/head`, which also covers forks), checks that it is the head the API returned, and checks the sign-off of its commits as on the pull request. The commits of the queue branch itself are written by GitHub, not by a contributor, so they are not what the sign-off certifies. |
| `Documentation updated` | Same as `Signed-off-by`, with the diff of the pull request and its labels of that moment. |
| `CLA` | A separate job of `cla.yml`, `CLA queue`, checks the signatures of the queued pull request (its commit authors and its opener) again and sets the `CLA` status on the head of the entry. It only reads and sets statuses: no signature is recorded and no comment is posted from the queue. |

No check passes without checking. The four checks that read the pull request
find it from the name of the queue branch (`scripts/merge_queue.py`, and the
same pattern in `cla.js`), and fail when the branch is not a queue branch of
`main` or when the pull request is not open against `main`. Each queue entry
names one pull request and runs its own checks, so with the grouping that
requires every entry to pass ("only merge non-failing pull requests"), each
pull request of a group is checked on its own entry.

**Code scanning.** CodeQL runs in default setup, which analyzes pull requests,
pushes to `main` and a weekly schedule; it cannot run on `merge_group`. The
ruleset's `code_scanning` rule is not a status check, and GitHub documents that
it does not apply to merge queue entries. A pull request is still analyzed and
gated before it can be queued, and `main` after each merge. What is lost is
the analysis of the exact combination before the merge; restoring it means an
advanced CodeQL workflow with a `merge_group` trigger, which replaces default
setup.

**Settings of the queue** (ruleset `main`, applied by the maintainer): squash,
as today; only non-failing pull requests are merged (`ALLGREEN`); up to five
entries built and merged at a time; no minimum group size; one hour for the
checks to report. The rule "branches must be up to date" is removed: the queue
tests every entry on the latest `main`.

## Consequences

- The maintainer no longer updates pull request branches after each merge.
  "Merge when ready" queues a pull request once its checks pass; GitHub merges
  it once the checks of its entry pass, or removes it from the queue and says
  why.
- Every merge runs the required checks twice, once on the pull request and once
  on its entry: about three more minutes of waiting per entry (the longest
  jobs, the two image builds), on the free runners of a public repository.
- The commit that lands on `main` is the commit of its queue entry (same SHA,
  so same tree), already tested by `ci.yml` on `merge_group`. `ci.yml`
  therefore no longer runs on `push` to `main` (amendment of 2026-11-09): that
  third run tested the same commit again. The workflows that must run on
  `main` keep their `push` trigger: `image.yml` (publication), `docs.yml`
  (publication), `zizmor.yml` (code scanning upload) and `scorecard.yml`. The
  CI badge of the README shows the merge queue runs.
- Push nothing to a queued pull request: remove it from the queue first. The
  checks that read the pull request read its head when they run, and a push
  while it is queued is not a case this design relies on.
- The commit on `main` is the squash commit created by the queue, as it was the
  squash commit created by the merge button.
- A new required check needs its workflow to run on `merge_group` before it is
  added to the ruleset, or the queue waits for it until the timeout.
