import re

import pytest
from django.test import Client
from django.urls import reverse

from housecairn.accounts.models import User

pytestmark = pytest.mark.django_db


def test_schema_requires_authentication(client: Client) -> None:
    assert client.get(reverse("api-schema")).status_code in (401, 403)


def test_schema_is_openapi_31(client: Client, alice: User) -> None:
    client.force_login(alice)
    response = client.get(reverse("api-schema"), HTTP_ACCEPT="application/vnd.oai.openapi+json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["openapi"] == "3.1.0"
    assert "/api/v1/homes/" in schema["paths"]
    assert "/api/v1/homes/{home_id}/events/" in schema["paths"]
    assert schema["components"]["securitySchemes"]["apiToken"]["scheme"] == "bearer"


def test_docs_are_served_locally_without_inline_script(client: Client, alice: User) -> None:
    client.force_login(alice)
    page = client.get(reverse("api-docs"))
    assert page.status_code == 200
    html = page.content.decode()
    scripts = re.findall(r"<script\b[^>]*>", html)
    assert scripts
    assert all("src=" in tag for tag in scripts)
    assert "<style" not in html
    assert "drf_spectacular_sidecar/swagger-ui-dist/" in html
    script = client.get(reverse("api-docs") + "?script=")
    assert script.status_code == 200
    assert script["Content-Type"].startswith("application/javascript")
