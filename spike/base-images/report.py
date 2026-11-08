"""Markdown report of the base image spike (spike/base-images/README.md).

Usage: python3 report.py <directory of <candidate>-<arch>.json files>

Prints one table per architecture, candidates as columns, and the details of
every failed check. Only reads the files written by measure.sh.
"""

import json
import sys
from pathlib import Path

ORDER = ["current", "distroless", "wolfi", "chainguard"]
SEVERITIES = ["Critical", "High", "Medium", "Low", "Negligible", "Unknown"]
CHECKS = [
    ("start_sqlite", "Starts (SQLite), healthy"),
    ("migrate_sqlite", "Migrations (SQLite)"),
    ("healthz_sqlite", "/healthz"),
    ("login_page_sqlite", "Sign-in page"),
    ("photo_sqlite", "Photo upload and read, Pillow (SQLite)"),
    ("backup", "Backup command"),
    ("non_root", "Runs as 10001"),
    ("read_only", "Read-only root file system"),
    ("start_postgresql", "Starts (PostgreSQL service)"),
    ("migrate_postgresql", "Migrations (PostgreSQL)"),
    ("login_page_postgresql", "Sign-in page (PostgreSQL)"),
    ("photo_postgresql", "Photo upload and read (PostgreSQL)"),
    ("exec_shell", "`docker exec sh` (debugging)"),
]


def mb(value: object) -> str:
    return f"{int(value) / 1_000_000:.1f} MB" if isinstance(value, int) else "n/a"


def get(data: dict, *path: str) -> object:
    for key in path:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def vulns(grype: object) -> list[str]:
    if not isinstance(grype, dict):
        return ["n/a"] * (len(SEVERITIES) + 2)
    rows = [f"{grype['total']} ({grype['fixable']})"]
    for severity in SEVERITIES:
        entry = grype["by_severity"].get(severity, {"total": 0, "fixable": 0})
        rows.append(f"{entry['total']} ({entry['fixable']})")
    failures = grype["ci_gate_failures"]
    rows.append("pass" if failures == 0 else f"**fail ({failures})**")
    return rows


def column(r: dict) -> list[str]:
    build = r.get("build", {})
    built = "yes" if build.get("ok") else f"**no**: {build.get('reason', '')[:120]}"
    files = r.get("files", {})
    image_rows = [
        r.get("measured", "n/a"),
        built,
        f"{build.get('seconds', 'n/a')} s",
        get(r, "image", "python") or "n/a",
        mb(get(r, "image", "layers", "compressed")),
        mb(get(r, "image", "layers", "uncompressed")),
        str(get(r, "image", "layers", "layers") or "n/a"),
        mb(get(r, "base", "layers", "compressed")),
        *vulns(get(r, "image", "grype")),
        *vulns(get(r, "base", "grype"))[:1],
        str(get(r, "sbom", "packages") or "n/a"),
        ", ".join(f"{k} {v}" for k, v in sorted((get(r, "sbom", "by_type") or {}).items())),
        files.get("shells") or "none",
        files.get("package_managers") or "none",
        files.get("pip") or "none",
        get(r, "image", "user") or "(root)",
    ]
    checks = r.get("checks", {})
    for key, _label in CHECKS:
        status = get(checks, key, "status")
        if status is None:
            image_rows.append("not run")
        elif status in {"pass", "absent", "present"}:
            image_rows.append(str(status))
        else:
            image_rows.append(f"**{status}**")
    return [str(cell).replace("|", "\\|").strip() for cell in image_rows]


LABELS = [
    "Measured",
    "Application built",
    "Build time (fresh runner, pulls included)",
    "Python, libc",
    "Compressed size (gzip -6 of the layers)",
    "Uncompressed size",
    "Layers",
    "Base image alone, compressed",
    "Grype: all (fixable)",
    *(f"Grype: {s} (fixable)" for s in SEVERITIES),
    "CI gate (fixable High or Critical)",
    "Grype on the base image alone: all (fixable)",
    "SBOM packages (Syft)",
    "SBOM packages by type",
    "Shell",
    "Package manager",
    "pip",
    "Image user",
    *(label for _key, label in CHECKS),
]


def main(directory: str) -> int:
    results = [json.loads(p.read_text()) for p in sorted(Path(directory).glob("*-*.json"))]
    lines = ["# Base image spike: measurements", ""]
    for arch in sorted({r["arch"] for r in results}):
        rows = sorted(
            (r for r in results if r["arch"] == arch), key=lambda r: ORDER.index(r["candidate"])
        )
        lines += [f"## {arch}", ""]
        lines.append("| | " + " | ".join(r["candidate"] for r in rows) + " |")
        lines.append("| --- |" + " --- |" * len(rows))
        columns = [column(r) for r in rows]
        for index, label in enumerate(LABELS):
            lines.append(f"| {label} | " + " | ".join(c[index] for c in columns) + " |")
        lines.append("")
        for r in rows:
            for key, value in sorted(r.get("checks", {}).items()):
                if value["status"] not in {"pass", "absent", "present"}:
                    lines.append(f"- {r['candidate']} {key}: {value['detail']}")
        lines.append("")
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
