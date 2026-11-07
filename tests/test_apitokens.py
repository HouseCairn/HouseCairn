"""API tokens: hashed storage, scopes, home restriction, expiry and revocation."""

from collections.abc import Callable
from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.apitokens import services
from housecairn.apitokens.models import ApiToken, Scope
from housecairn.homes import services as home_services
from housecairn.homes.models import Home, Membership, Role

pytestmark = pytest.mark.django_db


def bearer(client: APIClient, raw: str) -> APIClient:
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


def detail_url(home: Home) -> str:
    return reverse("api-v1:home-detail", kwargs={"home_id": home.id})


def events_url(home: Home) -> str:
    return reverse("api-v1:home-events", kwargs={"home_id": home.id})


@pytest.fixture
def issue(alice: User, alice_home: Home) -> Callable[..., str]:
    def make(*scopes: Scope, homes: list[Home] | None = None, **kwargs: object) -> str:
        _token, raw = services.issue_token(
            alice, name="test", scopes=scopes, homes=homes or [alice_home], **kwargs
        )
        return raw

    return make


class TestStorage:
    def test_only_a_hash_is_stored(self, alice: User, alice_home: Home) -> None:
        token, raw = services.issue_token(
            alice, name="ha", scopes=[Scope.EVENTS], homes=[alice_home]
        )
        token.refresh_from_db()
        assert raw.startswith("hc_")
        assert len(raw) > 40
        assert token.digest == services.hash_token(raw)
        assert token.digest != raw
        assert raw.startswith(token.prefix)
        assert len(token.prefix) < len(raw) // 3
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM apitokens_apitoken")
            rows = cursor.fetchall()
        assert all(raw not in str(value) for row in rows for value in row)

    def test_default_lifetime(self, alice: User, alice_home: Home) -> None:
        token, _raw = services.issue_token(alice, name="x", scopes=["read"], homes=[alice_home])
        assert token.expires_at is not None
        assert timedelta(days=89) < token.expires_at - timezone.now() <= timedelta(days=90)
        assert str(token) == f"x ({token.prefix}…)"

    def test_no_expiry_on_request(self, alice: User, alice_home: Home) -> None:
        token, _raw = services.issue_token(
            alice, name="x", scopes=["read"], homes=[alice_home], lifetime=None
        )
        assert token.expires_at is None
        assert token.is_active


class TestIssue:
    def test_needs_a_scope(self, alice: User, alice_home: Home) -> None:
        with pytest.raises(ValidationError):
            services.issue_token(alice, name="x", scopes=[], homes=[alice_home])

    def test_unknown_scope(self, alice: User, alice_home: Home) -> None:
        with pytest.raises(ValueError, match="admin"):
            services.issue_token(alice, name="x", scopes=["admin"], homes=[alice_home])

    def test_needs_a_home(self, alice: User) -> None:
        with pytest.raises(ValidationError):
            services.issue_token(alice, name="x", scopes=["read"], homes=[])

    def test_cannot_bind_someone_elses_home(self, alice: User, bob_home: Home) -> None:
        with pytest.raises(PermissionDenied):
            services.issue_token(alice, name="x", scopes=["read"], homes=[bob_home])


class TestScopes:
    def test_read_can_read_but_not_write(
        self, api_client: APIClient, issue: Callable[..., str], alice_home: Home
    ) -> None:
        bearer(api_client, issue(Scope.READ))
        assert api_client.get(detail_url(alice_home)).status_code == 200
        response = api_client.patch(detail_url(alice_home), {"name": "x"}, format="json")
        assert response.status_code == 403
        assert api_client.post(events_url(alice_home), {"kind": "x"}).status_code == 403
        alice_home.refresh_from_db()
        assert alice_home.name == "Main house"

    def test_write_can_write(
        self, api_client: APIClient, issue: Callable[..., str], alice_home: Home
    ) -> None:
        bearer(api_client, issue(Scope.WRITE))
        response = api_client.patch(detail_url(alice_home), {"name": "New"}, format="json")
        assert response.status_code == 200
        # Write does not imply read.
        assert api_client.get(detail_url(alice_home)).status_code == 403

    def test_events_can_only_post_events(
        self, api_client: APIClient, issue: Callable[..., str], alice_home: Home
    ) -> None:
        bearer(api_client, issue(Scope.EVENTS))
        assert api_client.get(reverse("api-v1:home-list")).status_code == 403
        assert api_client.get(detail_url(alice_home)).status_code == 403
        response = api_client.patch(detail_url(alice_home), {"name": "x"}, format="json")
        assert response.status_code == 403
        response = api_client.post(
            events_url(alice_home),
            {"kind": "battery-low", "payload": {"entity": "sensor.smoke"}},
            format="json",
        )
        assert response.status_code == 202
        assert response.json()["kind"] == "battery-low"

    def test_schema_needs_read_scope(
        self, api_client: APIClient, issue: Callable[..., str]
    ) -> None:
        schema_url = reverse("api-schema")
        bearer(api_client, issue(Scope.EVENTS))
        assert api_client.get(schema_url).status_code == 403
        bearer(api_client, issue(Scope.READ))
        assert api_client.get(schema_url).status_code == 200


class TestValidity:
    def test_expired_token_is_refused(
        self, api_client: APIClient, issue: Callable[..., str], alice_home: Home
    ) -> None:
        raw = issue(Scope.READ)
        ApiToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        response = bearer(api_client, raw).get(detail_url(alice_home))
        assert response.status_code == 401
        assert response["WWW-Authenticate"] == "Bearer"

    def test_revoked_token_is_refused(
        self, api_client: APIClient, alice: User, issue: Callable[..., str], alice_home: Home
    ) -> None:
        raw = issue(Scope.READ)
        services.revoke_token(alice, ApiToken.objects.get())
        assert bearer(api_client, raw).get(detail_url(alice_home)).status_code == 401
        services.revoke_token(alice, ApiToken.objects.get())  # idempotent

    def test_soft_deleted_token_is_refused(
        self, api_client: APIClient, issue: Callable[..., str], alice_home: Home
    ) -> None:
        raw = issue(Scope.READ)
        ApiToken.objects.get().soft_delete()
        assert bearer(api_client, raw).get(detail_url(alice_home)).status_code == 401

    def test_inactive_user_is_refused(
        self, api_client: APIClient, alice: User, issue: Callable[..., str], alice_home: Home
    ) -> None:
        raw = issue(Scope.READ)
        alice.is_active = False
        alice.save()
        assert bearer(api_client, raw).get(detail_url(alice_home)).status_code == 401

    @pytest.mark.parametrize(
        "header",
        ["Bearer hc_unknown", "Bearer wrongprefix", "Bearer", "Bearer a b", "Bearer \u00e9t\u00e9"],
    )
    def test_bad_credentials(self, api_client: APIClient, alice_home: Home, header: str) -> None:
        api_client.credentials(HTTP_AUTHORIZATION=header.encode("utf-8").decode("latin-1"))
        assert api_client.get(reverse("api-v1:home-list")).status_code == 401

    def test_last_used_is_recorded(
        self, api_client: APIClient, issue: Callable[..., str], alice_home: Home
    ) -> None:
        raw = issue(Scope.READ)
        bearer(api_client, raw).get(detail_url(alice_home))
        assert ApiToken.objects.get().last_used_at is not None

    def test_only_owner_or_staff_revokes(
        self, alice: User, bob: User, make_user: Callable[..., User], issue: Callable[..., str]
    ) -> None:
        issue(Scope.READ)
        token = ApiToken.objects.get()
        with pytest.raises(PermissionDenied):
            services.revoke_token(bob, token)
        staff = make_user(is_staff=True)
        services.revoke_token(staff, token)
        assert not ApiToken.objects.get().is_active


class TestHomeRestriction:
    def test_token_sees_only_its_homes(
        self, api_client: APIClient, alice: User, alice_home: Home, issue: Callable[..., str]
    ) -> None:
        second = home_services.create_home(alice, name="Cabin")
        bearer(api_client, issue(Scope.READ, homes=[alice_home]))
        ids = [h["id"] for h in api_client.get(reverse("api-v1:home-list")).json()["results"]]
        assert ids == [str(alice_home.id)]
        assert api_client.get(detail_url(second)).status_code == 404

    def test_token_cannot_reach_other_users_home(
        self, api_client: APIClient, bob_home: Home, issue: Callable[..., str]
    ) -> None:
        bearer(api_client, issue(Scope.READ, Scope.EVENTS))
        assert api_client.get(detail_url(bob_home)).status_code == 404
        assert api_client.post(events_url(bob_home), {"kind": "x"}).status_code == 404

    def test_token_loses_access_with_membership(
        self,
        api_client: APIClient,
        alice: User,
        bob: User,
        alice_home: Home,
        add_member: Callable[[Home, User, Role], Membership],
    ) -> None:
        membership = add_member(alice_home, bob, Role.MEMBER)
        _token, raw = services.issue_token(bob, name="x", scopes=["read"], homes=[alice_home])
        bearer(api_client, raw)
        assert api_client.get(detail_url(alice_home)).status_code == 200
        membership.soft_delete()
        assert api_client.get(detail_url(alice_home)).status_code == 404
