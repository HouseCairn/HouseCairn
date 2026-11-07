"""Property-based tests of the code that reads outside input without a database.

CI scripts read pull request titles, commit messages and Git refs written by
anyone who opens a pull request; the container entry point reads environment
variables and arguments set by the operator. Each test states its property in
its docstring (docs/adr/0019).
"""

import os
import re
from unittest import mock

import pytest
from django.http.request import validate_host
from hypothesis import assume, given
from hypothesis import strategies as st
from hypothesis.provisional import domains

from housecairn import entrypoint
from scripts import check_external_urls, check_pr_title, check_signoff, image_tags

# Text an environment variable can hold: anything but NUL and lone surrogates.
env_text = st.text(st.characters(codec="utf-8", exclude_characters="\x00"), max_size=30)
# Text without control characters or line and paragraph separators.
printable = st.characters(exclude_categories=("Cc", "Cs", "Zl", "Zp"))

# Pull request titles

scopes = st.from_regex(r"[a-z0-9][a-z0-9._/-]{0,15}", fullmatch=True)
subjects = st.text(printable, min_size=1, max_size=60).filter(lambda s: s == s.strip())
strict_title = re.compile(
    rf"(?:{'|'.join(check_pr_title.TYPES)})(?:\([a-z0-9][a-z0-9._/-]*\))?!?: \S[^\n]*"
)


@given(
    kind=st.sampled_from(check_pr_title.TYPES),
    scope=st.none() | scopes,
    breaking=st.booleans(),
    subject=subjects,
)
def test_well_formed_titles_are_accepted(
    kind: str, scope: str | None, breaking: bool, subject: str
) -> None:
    """Every `type(scope)!: subject` title of at most 100 characters passes."""
    title = f"{kind}{f'({scope})' if scope else ''}{'!' if breaking else ''}: {subject}"
    assume(len(title) <= check_pr_title.MAX_LENGTH)
    assert check_pr_title.problems(title) == []


@given(
    st.text(max_size=120)
    | st.builds(
        lambda kind, rest: kind + rest, st.sampled_from(check_pr_title.TYPES), st.text(max_size=40)
    )
)
def test_accepted_titles_are_conventional_commits(title: str) -> None:
    """Any text: no exception, and a title passes only if it is a strict Conventional Commit."""
    if check_pr_title.problems(title) == []:
        assert strict_title.fullmatch(title)
        assert title == title.strip()
        assert len(title) <= check_pr_title.MAX_LENGTH


# Signed-off-by trailers (DCO)

names = st.text(st.characters(exclude_categories=("Cc", "Cs", "Zl", "Zp", "Zs")), min_size=1)
messages = st.text(st.characters(exclude_characters="\x1e\x1f"), max_size=80)
shas = st.from_regex(r"[0-9a-f]{40}", fullmatch=True)


def commit(email: str, message: str) -> check_signoff.Commit:
    return check_signoff.Commit("b" * 40, ("a" * 40,), email, message)


@given(
    email=st.emails(),
    name=names.filter(lambda n: "<" not in n and ">" not in n),
    before=messages,
    case=st.sampled_from([str.lower, str.upper, str]),
)
def test_signoff_of_the_author_is_found(email: str, name: str, before: str, case: object) -> None:
    """A trailer with the author's address, in any letter case, signs the commit off."""
    assert callable(case)
    message = f"{before}\n\nSigned-off-by: {name} <{case(email)}>"
    assert check_signoff.is_signed_off(commit(email, message))


@given(author=st.emails(), other=st.emails(), name=names, message=messages)
def test_signoff_of_someone_else_does_not_count(
    author: str, other: str, name: str, message: str
) -> None:
    """A trailer with another address never signs the commit off."""
    assume(author.lower() != other.lower())
    assume(author.lower() not in check_signoff.signoff_emails(message))
    signed = f"{message}\n\nSigned-off-by: {name} <{other}>"
    assert not check_signoff.is_signed_off(commit(author, signed))
    assert check_signoff.unsigned([commit(author, signed)]) == [commit(author, signed)]


@given(
    st.lists(
        st.tuples(shas, st.lists(shas, max_size=3), st.emails(), messages),
        max_size=5,
    )
)
def test_git_log_output_is_read_back(
    records: list[tuple[str, list[str], str, str]],
) -> None:
    """`parse_log` reads back every commit of `git log --format=%H^_%P^_%ae^_%B^^`."""
    output = "".join(
        f"{sha}\x1f{' '.join(parents)}\x1f{email}\x1f{message}\x1e\n"
        for sha, parents, email, message in records
    )
    assert check_signoff.parse_log(output) == [
        check_signoff.Commit(sha, tuple(parents), email, message.strip())
        for sha, parents, email, message in records
    ]


@given(
    email=st.emails() | st.sampled_from(["49699333+dependabot[bot]@users.noreply.github.com"]),
    pr_author=st.none() | st.text(max_size=20) | st.sampled_from(sorted(check_signoff.EXEMPT_BOTS)),
    message=messages,
    parents=st.lists(shas, max_size=3),
)
def test_only_merges_and_the_bots_own_commits_skip_the_signoff(
    email: str, pr_author: str | None, message: str, parents: list[str]
) -> None:
    """A commit is skipped only if it is a merge, or a bot's commit in that bot's pull request."""
    c = check_signoff.Commit("c" * 40, tuple(parents), email, message)
    if c not in check_signoff.unsigned([c], pr_author) and not check_signoff.is_signed_off(c):
        login = email.split("@")[0].partition("+")[2].lower()
        assert len(parents) >= 2 or (
            login in check_signoff.EXEMPT_BOTS and login == (pr_author or "").lower()
        )


# Container image tags

versions = st.tuples(*[st.integers(0, 10_000)] * 3)
pre_suffixes = st.from_regex(r"[0-9A-Za-z.-]{1,20}", fullmatch=True)
# The tag grammar of the OCI distribution specification.
oci_tag = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")


@given(version=versions, sha=shas)
def test_release_tags(version: tuple[int, int, int], sha: str) -> None:
    """`vX.Y.Z` publishes `X.Y.Z`, `X.Y`, `latest` and `sha-<short>`, all valid tags."""
    major, minor, patch = version
    published, tags = image_tags.image_tags(f"refs/tags/v{major}.{minor}.{patch}", sha)
    assert published == f"{major}.{minor}.{patch}"
    assert tags == [published, f"{major}.{minor}", "latest", f"sha-{sha[:7]}"]
    assert all(oci_tag.fullmatch(tag) for tag in tags)


@given(version=versions, suffix=pre_suffixes, sha=shas)
def test_prereleases_never_move_latest(
    version: tuple[int, int, int], suffix: str, sha: str
) -> None:
    """A pre-release publishes only its own version and `sha-<short>`."""
    major, minor, patch = version
    published, tags = image_tags.image_tags(f"refs/tags/v{major}.{minor}.{patch}-{suffix}", sha)
    assert tags == [published, f"sha-{sha[:7]}"]
    assert all(oci_tag.fullmatch(tag) for tag in tags)


# A valid ref or SHA followed by a few characters: the classic traps of regular
# expressions first (`$` also matches before a final line break), then any text.
suffixes = st.sampled_from(["\n", "\r\n", " ", "\t", "\x00", "/", ".0", "-"]) | st.text(
    min_size=1, max_size=3
)
refs = st.sampled_from(["refs/heads/main", "refs/tags/v1.2.3", "refs/tags/v1.2.3-rc.1"])
published_ref = re.compile(
    r"refs/heads/main|refs/tags/v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?"
)


@given(ref=st.text(max_size=30) | st.builds(lambda r, s: r + s, refs, suffixes), sha=shas)
def test_nothing_is_published_for_any_other_ref(ref: str, sha: str) -> None:
    """Any ref outside the documented forms is refused with ValueError."""
    try:
        image_tags.image_tags(ref, sha)
    except ValueError:
        return
    assert published_ref.fullmatch(ref)


@given(ref=refs, sha=st.text(max_size=41) | st.builds(lambda h, s: h + s, shas, suffixes))
def test_nothing_is_published_without_a_full_sha(ref: str, sha: str) -> None:
    """Anything but 40 lowercase hexadecimal digits is refused with ValueError."""
    try:
        image_tags.image_tags(ref, sha)
    except ValueError:
        return
    assert re.fullmatch(r"[0-9a-f]{40}", sha)


# External URLs in templates and static files

hosts = domains()
ends = st.sampled_from(["/", ":443/", "?v=1", "#top", '"', "'", " ", ")", ""])


@given(
    scheme=st.sampled_from(["https:", "http:", "", "HTTPS:"]),
    host=hosts,
    end=ends,
    before=st.sampled_from(['src="', "url(", "href='", "@import "]),
)
def test_every_url_to_another_host_is_found(scheme: str, host: str, end: str, before: str) -> None:
    """An absolute or protocol-relative URL to any host name is reported (docs/adr/0011)."""
    line = f"{before}{scheme}//{host}{end}"
    assert check_external_urls.EXTERNAL_URL.search(line), line


@given(st.text(st.characters(exclude_characters="/")))
def test_text_without_a_double_slash_is_never_reported(line: str) -> None:
    """No URL to another host, no report: relative paths stay allowed."""
    assert check_external_urls.EXTERNAL_URL.search(line) is None


# Container entry point


@given(env_text)
def test_integer_variables(raw: str) -> None:
    """Any value: the integer, the default when blank, or a clear exit; no other exception."""
    try:
        expected = int(raw.strip()) if raw.strip() else 8000
    except ValueError:
        expected = None
    with mock.patch.dict(os.environ, {"HOUSECAIRN_PORT": raw}):
        if expected is None:
            with pytest.raises(SystemExit, match="HOUSECAIRN_PORT must be an integer"):
                entrypoint.env_int("HOUSECAIRN_PORT", 8000)
        else:
            assert entrypoint.env_int("HOUSECAIRN_PORT", 8000) == expected


host_entries = (
    domains()
    | domains().map(lambda d: "." + d)
    | st.sampled_from(["*", "", "localhost", "127.0.0.1", "[::1]"])
)


@given(entries=st.lists(host_entries, max_size=4), pad=st.sampled_from(["", " ", "  "]))
def test_health_check_host_is_accepted_by_the_instance(entries: list[str], pad: str) -> None:
    """The probe's Host header is one the instance accepts, whatever ALLOWED_HOSTS lists."""
    host = entrypoint.health_host(",".join(pad + e + pad for e in entries))
    assert host == host.strip()
    assert "," not in host
    if any(e not in ("", "*") for e in entries):
        assert validate_host(host.lower(), [e for e in entries if e])
    else:
        assert host == "localhost"


@given(st.integers(min_value=-64, max_value=255))
def test_a_process_that_stops_by_itself_never_exits_0(returncode: int) -> None:
    """The container never reports success when one of its processes stopped unasked."""
    status = entrypoint.exit_status(returncode)
    assert 1 <= status <= 255
    if returncode < 0:
        assert status == 128 - returncode


@given(st.lists(st.text(max_size=12), max_size=4))
def test_unknown_commands_start_nothing(argv: list[str]) -> None:
    """Anything but the four documented commands prints the usage and returns 2."""
    command, args = (argv[0], argv[1:]) if argv else ("run", [])
    assume(not (command in {"run", "healthcheck", "backup"} and not args))
    assume(not (command == "manage" and args))
    started = pytest.fail
    with (
        mock.patch.object(entrypoint, "command_run", started),
        mock.patch.object(entrypoint, "command_healthcheck", started),
        mock.patch.object(entrypoint, "command_backup", started),
        mock.patch.object(entrypoint, "command_manage", started),
        mock.patch("sys.stderr"),
    ):
        assert entrypoint.main(argv) == 2
