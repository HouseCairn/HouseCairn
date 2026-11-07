"""Tags and version of the container image for a Git ref (docs/adr/0015).

- push to `main`: `edge` and `sha-<short>`; version `edge-<short>`;
- release tag `vX.Y.Z`: `X.Y.Z`, `X.Y`, `latest` and `sha-<short>`;
- pre-release tag `vX.Y.Z-<pre>`: `X.Y.Z-<pre>` and `sha-<short>` only, so
  that `latest` and `X.Y` always point to a final release.

Usage: python scripts/image_tags.py <ref> <commit sha>
Prints `version=<version>` and `tags=<tag> <tag> ...`, the format of
`$GITHUB_OUTPUT`. Any other ref is an error: nothing is published for it.
"""

import re
import sys

RELEASE = re.compile(
    r"^refs/tags/v(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$"
)
PRERELEASE = re.compile(
    r"^refs/tags/v(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)-[0-9A-Za-z.-]+)$"
)
SHA = re.compile(r"^[0-9a-f]{40}$")


def image_tags(ref: str, sha: str) -> tuple[str, list[str]]:
    """(version, tags) for this ref; ValueError if nothing is published for it."""
    # fullmatch: `match` with `$` would also accept a trailing line break.
    if not SHA.fullmatch(sha):
        raise ValueError(f"not a full commit SHA: {sha!r}")
    short = sha[:7]
    if ref == "refs/heads/main":
        return f"edge-{short}", ["edge", f"sha-{short}"]
    if release := RELEASE.fullmatch(ref):
        major, minor, patch = release.group("major", "minor", "patch")
        version = f"{major}.{minor}.{patch}"
        return version, [version, f"{major}.{minor}", "latest", f"sha-{short}"]
    if prerelease := PRERELEASE.fullmatch(ref):
        version = prerelease.group("version")
        return version, [version, f"sha-{short}"]
    raise ValueError(f"no image is published for {ref!r}")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        sys.stderr.write("usage: image_tags.py <ref> <commit sha>\n")
        return 2
    try:
        version, tags = image_tags(args[0], args[1])
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    sys.stdout.write(f"version={version}\ntags={' '.join(tags)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
