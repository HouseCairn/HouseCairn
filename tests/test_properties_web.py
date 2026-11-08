"""Property-based tests of what the web application reads from the outside.

Request headers, JSON bodies, query strings and the claims of an identity
provider are written by someone else. Each test states its property in its
docstring (docs/adr/0019). Tests that use the database share it between the
examples of one test, inside its transaction: each example reads the state it
starts from, so they do not depend on the order.
"""

import json
import re
from typing import Any
from urllib.parse import urlsplit

import pytest
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.http import HttpResponseRedirect
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st
from rest_framework.test import APIClient

from housecairn.accounts.adapters import provider_identity
from housecairn.accounts.models import User
from housecairn.apitokens.models import Scope
from housecairn.apitokens.services import issue_token
from housecairn.core.redirects import is_safe_redirect
from housecairn.homes.models import Home

# Fixtures are created once per test and shared by its examples, on purpose.
shared_fixtures = settings(suppress_health_check=[HealthCheck.function_scoped_fixture])

# Claims of an identity provider

json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(max_size=20),
    lambda children: (
        st.lists(children, max_size=3) | st.dictionaries(st.text(max_size=10), children, max_size=3)
    ),
    max_leaves=10,
)
claims = st.fixed_dictionaries(
    {},
    optional={
        "email": json_values | st.emails() | st.emails().map(lambda e: f"  {e} "),
        "email_verified": json_values | st.sampled_from([True, "true", 1]),
    },
)
extra_data = (
    json_values
    | st.fixed_dictionaries({}, optional={"userinfo": claims | json_values, "id_token": claims})
    | claims
)


@given(extra_data)
# Found by this property; `ci` explores too few examples to find them again by itself.
@example(data={"userinfo": [None]})
@example(data=True)
def test_provider_identity_reads_any_claims(data: Any) -> None:
    """Any JSON from the provider: no exception, and verified only on a JSON `true`."""
    login = SocialLogin(account=SocialAccount(extra_data=data))
    email, verified = provider_identity(login)
    if email is None:
        assert verified is False
        return
    assert email == email.strip() != ""
    # The claims the address came from: userinfo, else the ID token, else the data.
    candidates = [data.get("userinfo"), data.get("id_token"), data]
    found = next(c for c in candidates if isinstance(c, dict) and c)
    assert found["email"].strip() == email
    assert verified is (found.get("email_verified") is True)


# API tokens in the Authorization header

latin1 = st.text(st.characters(min_codepoint=1, max_codepoint=255), max_size=60)
headers = (
    latin1
    | latin1.map(lambda t: "Bearer " + t)
    | latin1.map(lambda t: "Bearer hc_" + t)
    | st.sampled_from(["Bearer", "Bearer ", "bearer hc_", "Bearer hc_ hc_", "Token hc_x"])
)


@pytest.mark.django_db
@shared_fixtures
@given(header=headers)
def test_no_authorization_header_but_the_token_opens_the_api(
    api_client: APIClient, alice: User, alice_home: Home, header: str
) -> None:
    """Any Authorization header but the issued token is refused with 401 or 403, never 500."""
    _, raw = issue_token(alice, name="t", scopes=[Scope.READ], homes=[alice_home])
    url = reverse("api-v1:home-list")
    response = api_client.get(url, HTTP_AUTHORIZATION=header)
    assert response.status_code in {401, 403}, (header, response.status_code)
    assert api_client.get(url, HTTP_AUTHORIZATION=f"Bearer {raw}").status_code == 200


# Home serializer

any_value = (
    st.text(st.characters(exclude_categories=()), max_size=130)
    | st.integers()
    | st.none()
    | st.booleans()
    | st.lists(st.text(max_size=5), max_size=2)
)
currencies = st.sampled_from(["EUR", "USD", "eur", "EURO", "", "E1R", "ÉUR"]) | any_value


@pytest.mark.django_db
@shared_fixtures
@given(
    payload=st.fixed_dictionaries({}, optional={"name": any_value, "currency": currencies}),
)
def test_home_update_round_trips_or_is_refused(
    api_client: APIClient, alice: User, alice_home: Home, payload: dict[str, Any]
) -> None:
    """Any PATCH body: 200 with what is stored and read back, or 400 and nothing changes."""
    api_client.force_authenticate(alice)
    url = reverse("api-v1:home-detail", kwargs={"home_id": alice_home.id})
    before = Home.objects.values("name", "currency").get(pk=alice_home.pk)
    response = api_client.patch(url, data=json.dumps(payload), content_type="application/json")
    stored = Home.objects.values("name", "currency").get(pk=alice_home.pk)
    assert response.status_code in {200, 400}, response.content
    if response.status_code == 400:
        assert stored == before
        return
    body = response.json()
    assert {"name": body["name"], "currency": body["currency"]} == stored
    assert api_client.get(url).json() == body
    assert 0 < len(stored["name"]) <= 120
    assert re.fullmatch(r"[A-Z]{3}", stored["currency"])


# Redirection after sign-in

next_values = st.text(max_size=40) | st.builds(
    lambda prefix, rest: prefix + rest,
    st.sampled_from(
        [
            "//",
            "///",
            "/\\",
            "\\\\",
            "https://",
            "http:",
            "https:/",
            " //",
            "\t//",
            "/%2F",
            "%2F%2F",
            "javascript:",
            "data:",
            "/homes/",
        ]
    ),
    st.sampled_from(
        ["evil.example", "testserver.evil.example", "testserver@evil.example", "[", "[::1"]
    )
    | st.text(max_size=15),
)


@pytest.mark.django_db
@shared_fixtures
@given(target=next_values, signed_in=st.booleans())
# Found by the `dev` profile: allauth's urlparse raised ValueError (a 500).
@example(target="//[", signed_in=False)
# Found in CI: Python strips "\r", "\n" and "\t" before parsing (bpo-43882), so Django
# saw a path; the browser received "//%0D", a scheme-relative address.
@example(target="//\r", signed_in=True)
@example(target="//\n", signed_in=True)
@example(target="//\t", signed_in=True)
@example(target="/\t/evil.example", signed_in=True)
@example(target="/\\\r", signed_in=True)
@example(target="\\\\/\n", signed_in=True)
@example(target="\\/\x00", signed_in=True)
def test_sign_in_never_redirects_to_another_host(
    client: Client, alice: User, target: str, signed_in: bool
) -> None:
    """Whatever `next` holds, the sign-in page answers and redirects only within the instance."""
    if signed_in:
        client.force_login(alice)
    else:
        client.logout()
    response = client.get(reverse("account_login"), {"next": target})
    assert response.status_code == (302 if signed_in else 200)
    if response.status_code == 302:
        location = response["Location"]
        assert url_has_allowed_host_and_scheme(location, allowed_hosts={"testserver"}), location
        assert not location.startswith(("//", "\\")), location


@given(target=next_values)
@example(target="//\r")
@example(target="/\\\r")
@example(target="\uff0f\uff0fevil.example")
def test_an_accepted_next_stays_on_this_site(target: str) -> None:
    """Every `next` the shared rule accepts is sent as an address on this host only."""
    request = RequestFactory().get("/")
    if not is_safe_redirect(target, request):
        return
    location = HttpResponseRedirect(target)["Location"]
    assert not location.startswith(("//", "\\")), location
    assert urlsplit(location).netloc in {"", "testserver"}, location
    assert not re.search(r"%(0[0-9A-F]|1[0-9A-F]|7F|20)", location, re.IGNORECASE), location
