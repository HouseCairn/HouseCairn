from collections.abc import Callable

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.events.models import Event
from housecairn.homes.models import Home, Membership, Role

pytestmark = pytest.mark.django_db


def events_url(home: Home) -> str:
    return reverse("api-v1:home-events", kwargs={"home_id": home.id})


def test_event_is_recorded_with_its_token(
    api_client: APIClient, alice: User, alice_home: Home
) -> None:
    token, raw = token_services.issue_token(alice, name="ha", scopes=["events"], homes=[alice_home])
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    response = api_client.post(events_url(alice_home), {"kind": "leak"}, format="json")
    assert response.status_code == 202
    event = Event.objects.get()
    assert event.home == alice_home
    assert event.token == token
    assert event.received_by == alice
    assert event.payload == {}
    assert str(event) == "leak"
    assert list(Event.objects.in_homes(Home.objects.filter(id=alice_home.id))) == [event]


def test_session_user_can_post(api_client: APIClient, alice: User, alice_home: Home) -> None:
    api_client.force_authenticate(alice)
    response = api_client.post(events_url(alice_home), {"kind": "leak"}, format="json")
    assert response.status_code == 202
    assert Event.objects.get().token is None


def test_read_only_member_cannot_post(
    api_client: APIClient,
    bob: User,
    alice_home: Home,
    add_member: Callable[[Home, User, Role], Membership],
) -> None:
    add_member(alice_home, bob, Role.READ_ONLY)
    _token, raw = token_services.issue_token(bob, name="x", scopes=["events"], homes=[alice_home])
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert api_client.post(events_url(alice_home), {"kind": "leak"}).status_code == 403
    assert not Event.objects.exists()


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"kind": "not a slug"}, "kind"),
        ({}, "kind"),
        ({"kind": "big", "payload": {"data": "x" * 20000}}, "payload"),
        ({"kind": "list", "payload": [1, 2]}, "payload"),
    ],
)
def test_invalid_events(
    api_client: APIClient, alice: User, alice_home: Home, body: dict[str, object], field: str
) -> None:
    api_client.force_authenticate(alice)
    response = api_client.post(events_url(alice_home), body, format="json")
    assert response.status_code == 400
    assert field in response.json()
    assert not Event.objects.exists()
