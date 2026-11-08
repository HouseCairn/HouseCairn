"""Scripts run by the CI workflows (scripts/, docs/adr/0014)."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts import check_external_urls, check_pr_title, check_signoff, merge_queue

# Pull request titles


@pytest.mark.parametrize(
    "title",
    [
        "feat: add yearly recurrence",
        "fix(schedule): skip archived rooms",
        "ci: add CI, supply-chain checks and CLA workflow",
        "feat(api)!: drop the v0 endpoints",
        "chore(deps): bump the minor-and-patch group with 3 updates",
        "docs(adr/0014): list the required checks",
        "revert: feat: add yearly recurrence",
    ],
)
def test_conventional_titles_pass(title: str) -> None:
    assert check_pr_title.problems(title) == []
    assert check_pr_title.main([title]) == 0


@pytest.mark.parametrize(
    "title",
    [
        "",
        "Add yearly recurrence",
        "feat:add yearly recurrence",
        "feat:  ",
        "Feat: add yearly recurrence",
        "feature: add yearly recurrence",
        "feat(Schedule): add yearly recurrence",
        "feat(): add yearly recurrence",
        "feat (api): add yearly recurrence",
        " feat: add yearly recurrence",
        "feat: " + "x" * 100,
    ],
)
def test_other_titles_fail(title: str) -> None:
    assert check_pr_title.problems(title) != []
    assert check_pr_title.main([title]) == 1


def test_title_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PR_TITLE", "fix: handle empty schedules")
    assert check_pr_title.main([]) == 0
    monkeypatch.setenv("PR_TITLE", "handle empty schedules")
    assert check_pr_title.main([]) == 1


def test_unknown_type_is_named(capsys: pytest.CaptureFixture[str]) -> None:
    check_pr_title.main(["feature: add yearly recurrence"])
    assert "unknown type 'feature'" in capsys.readouterr().err


# Sign-off (DCO)

AUTHOR = "Ada Example <ada@example.com>"


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Ada Example",
        "GIT_AUTHOR_EMAIL": "ada@example.com",
        "GIT_COMMITTER_NAME": "Ada Example",
        "GIT_COMMITTER_EMAIL": "ada@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    result = subprocess.run(  # noqa: S603 - fixed program, test-controlled arguments
        ["git", "-C", str(repo), *args],  # noqa: S607 - git from PATH
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "commit", "--allow-empty", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _commit(tmp_path, "chore: initial commit")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_signed_off_commits_pass(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, f"feat: one\n\nSigned-off-by: {AUTHOR}")
    head = _commit(repo, "fix: two\n\nBody.\n\nSigned-off-by: Ada Example <ADA@example.com>")
    assert check_signoff.main([base, head]) == 0


def test_commit_without_signoff_fails(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, f"feat: one\n\nSigned-off-by: {AUTHOR}")
    unsigned = _commit(repo, "fix: two")
    assert check_signoff.main([base, unsigned]) == 1
    err = capsys.readouterr().err
    assert unsigned[:12] in err
    assert "fix: two" in err


def test_signoff_from_someone_else_fails(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit(repo, "feat: one\n\nSigned-off-by: Bob Example <bob@example.com>")
    assert check_signoff.main([base, head]) == 1


def test_signoff_must_be_a_trailer_line(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit(repo, f"feat: one\n\nNot a trailer: Signed-off-by: {AUTHOR}")
    assert check_signoff.main([base, head]) == 1


def test_merge_commits_are_skipped(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "topic")
    _commit(repo, f"feat: one\n\nSigned-off-by: {AUTHOR}")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, f"fix: on main\n\nSigned-off-by: {AUTHOR}")
    _git(repo, "checkout", "-q", "topic")
    _git(repo, "merge", "-q", "--no-ff", "--no-edit", "main")
    head = _git(repo, "rev-parse", "HEAD")
    commits = check_signoff.read_commits(base, head)
    assert len(commits) == 3
    assert check_signoff.unsigned(commits) == []
    assert check_signoff.main([base, head]) == 0


def test_empty_range_passes(repo: Path) -> None:
    head = _git(repo, "rev-parse", "HEAD")
    assert check_signoff.main([head, head]) == 0


def test_signoff_usage_error() -> None:
    assert check_signoff.main([]) == 2


DEPENDABOT_EMAIL = "49699333+dependabot[bot]@users.noreply.github.com"
# As Dependabot writes it: the sign-off address is not the author address.
DEPENDABOT_MESSAGE = (
    "chore(deps): bump django from 5.2.7 to 5.2.8\n\n"
    "Signed-off-by: dependabot[bot] <support@github.com>"
)


def _dependabot_commit(repo: Path) -> str:
    subprocess.run(  # noqa: S603 - fixed program, test-controlled arguments
        ["git", "-C", str(repo), "commit", "--allow-empty", "-q", "-m", DEPENDABOT_MESSAGE],  # noqa: S607
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "dependabot[bot]",
            "GIT_AUTHOR_EMAIL": DEPENDABOT_EMAIL,
            "GIT_COMMITTER_NAME": "GitHub",
            "GIT_COMMITTER_EMAIL": "noreply@github.com",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    return _git(repo, "rev-parse", "HEAD")


def test_dependabot_commits_pass_in_a_dependabot_pull_request(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    head = _dependabot_commit(repo)
    monkeypatch.setenv("PR_AUTHOR", "dependabot[bot]")
    assert check_signoff.main([base, head]) == 0


def test_bot_address_in_someone_elses_pull_request_is_checked(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    head = _dependabot_commit(repo)
    monkeypatch.setenv("PR_AUTHOR", "mallory")
    assert check_signoff.main([base, head]) == 1
    monkeypatch.delenv("PR_AUTHOR")
    assert check_signoff.main([base, head]) == 1


def test_only_listed_bots_are_exempt() -> None:
    commit = check_signoff.Commit(
        "a" * 40, ("b" * 40,), "123+other[bot]@users.noreply.github.com", "chore: x"
    )
    assert check_signoff.unsigned([commit], "other[bot]") == [commit]
    actions = check_signoff.Commit(
        "c" * 40, ("b" * 40,), "41898282+github-actions[bot]@users.noreply.github.com", "chore: y"
    )
    assert check_signoff.unsigned([actions], "github-actions[bot]") == []
    assert check_signoff.unsigned([actions], "dependabot[bot]") == [actions]


# External URLs


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_external_urls_are_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path, "templates/base.html", '<link href="/static/app.css">\n')
    _write(tmp_path, "templates/page.html", '\n<script src="https://cdn.example.com/x.js">\n')
    _write(tmp_path, "static/css/app.css", "@import url(//fonts.example.net/css);\n")
    found = check_external_urls.offenders(tmp_path)
    assert [(p.name, n, url) for p, n, url in found] == [
        ("app.css", 1, "//fonts.example.net"),
        ("page.html", 2, "https://cdn.example.com"),
    ]
    assert check_external_urls.main([str(tmp_path)]) == 1
    assert "page.html:2" in capsys.readouterr().err


def test_local_and_non_web_files_pass(tmp_path: Path) -> None:
    _write(tmp_path, "templates/base.html", '<a href="/homes/">Homes</a>\n')
    _write(tmp_path, "static/vendor/LICENSE", "See https://example.com/license\n")
    _write(tmp_path, "static/vendor/README.md", "From https://example.com/\n")
    assert check_external_urls.offenders(tmp_path) == []
    assert check_external_urls.main([str(tmp_path)]) == 0


def test_repository_has_no_external_url() -> None:
    assert check_external_urls.main([]) == 0


# Merge queue entries (scripts/merge_queue.py, docs/adr/0040)

_QUEUE_SHA = "929f8209d40f77f4abc622a499c93a83babdbe64"


def _pull(**changes: object) -> dict[str, object]:
    pull: dict[str, object] = {
        "number": 104,
        "state": "open",
        "title": "feat: add yearly recurrence",
        "user": {"login": "alice"},
        "base": {"ref": "main", "sha": "b" * 40},
        "head": {"sha": "h" * 40},
        "labels": [{"name": "no-docs-needed"}],
    }
    pull.update(changes)
    return pull


def test_queue_branch_gives_the_pull_request_number() -> None:
    ref = f"refs/heads/gh-readonly-queue/main/pr-104-{_QUEUE_SHA}"
    assert merge_queue.pull_request_number(ref, "main") == 104


@pytest.mark.parametrize(
    "ref",
    [
        "",
        "refs/heads/main",
        f"refs/heads/feature/pr-104-{_QUEUE_SHA}",
        f"refs/heads/gh-readonly-queue/release/pr-104-{_QUEUE_SHA}",
        f"refs/heads/gh-readonly-queue/main/pr-0104-{_QUEUE_SHA}",
        "refs/heads/gh-readonly-queue/main/pr-104-abc",
        f"refs/heads/gh-readonly-queue/main/pr-104-{_QUEUE_SHA}\n",
    ],
)
def test_other_references_are_refused(ref: str) -> None:
    with pytest.raises(merge_queue.QueueError):
        merge_queue.pull_request_number(ref, "main")


def test_queued_pull_request_is_read_from_the_api() -> None:
    urls: list[str] = []

    def fetch(url: str) -> dict[str, object]:
        urls.append(url)
        return _pull()

    ref = f"refs/heads/gh-readonly-queue/main/pr-104-{_QUEUE_SHA}"
    pull = merge_queue.queued_pull_request(ref, "main", "o/r", "https://api.example.com", fetch)
    assert urls == ["https://api.example.com/repos/o/r/pulls/104"]
    assert pull == {
        "number": 104,
        "title": "feat: add yearly recurrence",
        "author": "alice",
        "base_sha": "b" * 40,
        "head_sha": "h" * 40,
        "labels": ["no-docs-needed"],
    }


@pytest.mark.parametrize(
    "pull",
    [_pull(state="closed"), _pull(base={"ref": "release", "sha": "b" * 40})],
)
def test_a_pull_request_not_open_against_the_base_is_refused(pull: dict[str, object]) -> None:
    with pytest.raises(merge_queue.QueueError):
        merge_queue.summary(pull, "main")


def test_main_prints_the_pull_request_or_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    ref = f"refs/heads/gh-readonly-queue/main/pr-104-{_QUEUE_SHA}"
    monkeypatch.setenv("MERGE_GROUP_HEAD_REF", ref)
    assert merge_queue.main([], fetch=lambda url: _pull()) == 0
    assert json.loads(capsys.readouterr().out)["number"] == 104
    assert merge_queue.main([], fetch=lambda url: _pull(state="closed")) == 1
    assert "not open" in capsys.readouterr().err
    monkeypatch.setenv("MERGE_GROUP_HEAD_REF", "refs/heads/main")
    assert merge_queue.main([], fetch=lambda url: _pull()) == 1


# Every workflow of a required check also runs on the merge queue: a required
# check that never reports on a queue entry blocks the queue (docs/adr/0040).
_REQUIRED_CHECK_WORKFLOWS = (
    "ci.yml",
    "cla.yml",
    "dco.yml",
    "dependency-review.yml",
    "docs-updated.yml",
    "docs.yml",
    "image.yml",
    "pr-title.yml",
    "zizmor.yml",
)


@pytest.mark.parametrize("name", _REQUIRED_CHECK_WORKFLOWS)
def test_required_check_workflows_run_on_the_merge_queue(name: str) -> None:
    workflow = Path(__file__).parent.parent / ".github" / "workflows" / name
    text = workflow.read_text(encoding="utf-8")
    on_block = text.split("\non:\n", 1)[1].split("\n\n", 1)[0]
    assert "\n  merge_group:\n    types: [checks_requested]" in f"\n{on_block}"


# Retries of the downloads made by the CI (.github/scripts/retry.sh)

RETRY = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "retry.sh"
# Fails until it has been run `succeed_at` times, counting its runs in a file.
FLAKY = 'n=$(($(cat "$1" 2>/dev/null || echo 0) + 1)); echo "$n" >"$1"; [ "$n" -ge "$2" ] || exit 7'


def _retry(
    tmp_path: Path, succeed_at: int, attempts: int
) -> tuple[subprocess.CompletedProcess[str], int]:
    counter = tmp_path / "runs"
    result = subprocess.run(  # noqa: S603 - fixed program, test-controlled arguments
        ["bash", str(RETRY), "bash", "-c", FLAKY, "flaky", str(counter), str(succeed_at)],  # noqa: S607
        env={**os.environ, "RETRY_ATTEMPTS": str(attempts), "RETRY_DELAY": "0"},
        capture_output=True,
        text=True,
        check=False,
    )
    return result, int(counter.read_text())


def test_retry_succeeds_after_transient_failures(tmp_path: Path) -> None:
    result, runs = _retry(tmp_path, succeed_at=3, attempts=4)
    assert (result.returncode, runs) == (0, 3)
    assert "attempt 2 of 4" in result.stderr


def test_retry_keeps_the_last_failure(tmp_path: Path) -> None:
    result, runs = _retry(tmp_path, succeed_at=10, attempts=4)
    assert (result.returncode, runs) == (7, 4)
    assert "failed 4 times, last exit status 7" in result.stderr


def test_retry_runs_a_successful_command_once(tmp_path: Path) -> None:
    result, runs = _retry(tmp_path, succeed_at=1, attempts=4)
    assert (result.returncode, runs, result.stderr) == (0, 1, "")


def test_retry_needs_a_command() -> None:
    result = subprocess.run(  # noqa: S603 - fixed program
        ["bash", str(RETRY)],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "usage" in result.stderr
