"""The Compose file for Coolify (docs/administration/coolify.md) against compose.yaml.

`deploy/coolify/docker-compose.yaml` must run the same image as the example
`compose.yaml`, with the same hardening, and keep out what breaks under Coolify:
a published port, an `env_file`, a fixed network range, a project name. The
`Container image` job of `.github/workflows/image.yml` also runs
`docker compose config` on it.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
COMPOSE = REPO / "compose.yaml"
COOLIFY = REPO / "deploy" / "coolify" / "docker-compose.yaml"
SERVICE = "housecairn"
# What the two files must set identically on the HouseCairn service.
SHARED_KEYS = (
    "image",
    "restart",
    "read_only",
    "tmpfs",
    "cap_drop",
    "security_opt",
    "stop_grace_period",
    "volumes",
)
# Keys of a Coolify service template header (templates/compose/*.yaml in Coolify).
HEADER_KEYS = ("documentation", "slogan", "category", "tags", "port")


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict)
    return data


def _service(data: dict[str, Any]) -> dict[str, Any]:
    service = data["services"][SERVICE]
    assert isinstance(service, dict)
    return service


def _environment(service: dict[str, Any]) -> dict[str, str | None]:
    environment = service["environment"]
    assert isinstance(environment, list), "a list, as in Coolify's service templates"
    pairs = (str(item).partition("=") for item in environment)
    return {name: (value if sep else None) for name, sep, value in pairs}


def divergences(compose: dict[str, Any], coolify: dict[str, Any]) -> list[str]:
    """Shared keys whose value differs between the two files."""
    ours, theirs = _service(compose), _service(coolify)
    return [key for key in SHARED_KEYS if ours.get(key) != theirs.get(key)]


def coolify_problems(coolify: dict[str, Any]) -> list[str]:
    """What would break a deployment under Coolify, or two instances on one server."""
    problems = []
    if "name" in coolify:
        problems.append("project name")
    for name, service in coolify["services"].items():
        for key in ("ports", "env_file", "network_mode"):
            if key in service:
                problems.append(f"{name}: {key}")
    for name, network in (coolify.get("networks") or {}).items():
        if (network or {}).get("ipam"):
            problems.append(f"network {name}: fixed range")
    return problems


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return _load(COMPOSE)


@pytest.fixture(scope="module")
def coolify() -> dict[str, Any]:
    return _load(COOLIFY)


def test_same_image_and_hardening(compose: dict[str, Any], coolify: dict[str, Any]) -> None:
    assert divergences(compose, coolify) == []
    service = _service(coolify)
    assert "@sha256:" in service["image"]
    assert service["cap_drop"] == ["ALL"]
    assert service["read_only"] is True


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (
            "image",
            "ghcr.io/housecairn/housecairn:0.1.0@sha256:"
            "0000000000000000000000000000000000000000000000000000000000000000",
        ),
        ("image", "ghcr.io/housecairn/housecairn:0.0.9"),
        ("cap_drop", None),
        ("read_only", None),
        ("tmpfs", ["/tmp:rw,size=64m"]),  # noqa: S108 - a mount option, not a file
        ("security_opt", None),
        ("stop_grace_period", "10s"),
        ("volumes", ["housecairn-data:/srv"]),
    ],
)
def test_a_change_in_one_file_only_is_caught(
    compose: dict[str, Any], coolify: dict[str, Any], key: str, value: object
) -> None:
    mutant = yaml.safe_load(yaml.safe_dump(coolify))
    if value is None:
        del mutant["services"][SERVICE][key]
    else:
        mutant["services"][SERVICE][key] = value
    assert divergences(compose, mutant) == [key]


def test_nothing_that_breaks_under_coolify(coolify: dict[str, Any]) -> None:
    assert coolify_problems(coolify) == []


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(name="housecairn"),
        lambda d: d["services"][SERVICE].update(ports=["8000:8000"]),
        lambda d: d["services"][SERVICE].update(env_file="deploy/production.env"),
        lambda d: d.update(
            networks={"default": {"ipam": {"config": [{"subnet": "192.0.2.0/24"}]}}}
        ),
    ],
)
def test_coolify_problems_are_caught(coolify: dict[str, Any], change: Any) -> None:
    mutant = yaml.safe_load(yaml.safe_dump(coolify))
    change(mutant)
    assert len(coolify_problems(mutant)) == 1


def test_domain_comes_from_coolify(coolify: dict[str, Any]) -> None:
    environment = _environment(_service(coolify))
    # Declared without a value: Coolify generates the URL and routes it to port 8000.
    assert environment["SERVICE_URL_HOUSECAIRN_8000"] is None
    assert environment["ALLOWED_HOSTS"] == "${SERVICE_FQDN_HOUSECAIRN}"
    assert environment["CSRF_TRUSTED_ORIGINS"] == "${SERVICE_URL_HOUSECAIRN}"
    assert environment["HOUSECAIRN_SITE_URL"] == "${SERVICE_URL_HOUSECAIRN}"
    assert environment["HOUSECAIRN_BEHIND_TLS_PROXY"] == "true"
    assert environment["HOUSECAIRN_FORWARDED_ALLOW_IPS"] == (
        "${HOUSECAIRN_FORWARDED_ALLOW_IPS:-172.16.0.0/12}"
    )
    assert environment["DEBUG"] == "false"
    assert environment["HOUSECAIRN_DATA_DIR"] == "/data"


def test_optional_settings_never_block_a_deployment(coolify: dict[str, Any]) -> None:
    """Every other variable has a default: none is required (`:?`), none is a secret."""
    environment = _environment(_service(coolify))
    for name, value in environment.items():
        if value is None or "${" not in value or value.startswith("${SERVICE_"):
            continue
        assert value.startswith(f"${{{name}:-"), name
        assert ":?" not in value, name
    assert "SECRET_KEY" not in environment
    for name in ("OIDC_SERVER_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET"):
        assert environment[name] == f"${{{name}:-}}", name


def test_health_check_without_curl(coolify: dict[str, Any]) -> None:
    healthcheck = _service(coolify)["healthcheck"]
    assert healthcheck["test"] == ["CMD", "python", "-m", "housecairn.entrypoint", "healthcheck"]
    assert healthcheck["start_period"]
    assert _service(coolify)["pull_policy"] == "missing"


def test_template_header() -> None:
    header = {}
    for line in COOLIFY.read_text().splitlines():
        if not line.startswith("# ") or ":" not in line:
            break
        key, _, value = line[2:].partition(":")
        header[key] = value.strip()
    assert tuple(header) == HEADER_KEYS
    assert header["port"] == "8000"
    assert all(header.values())


def test_kept_up_to_date_by_dependabot() -> None:
    config = _load(REPO / ".github" / "dependabot.yml")
    compose_updates = [u for u in config["updates"] if u["package-ecosystem"] == "docker-compose"]
    assert len(compose_updates) == 1
    assert "/deploy/coolify" in compose_updates[0]["directories"]
