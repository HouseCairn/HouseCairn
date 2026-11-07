"""Home scoping: a user never sees another user's home, by the web or the API."""

from collections.abc import Callable

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.homes import services
from housecairn.homes.models import Home, Membership, Role

pytestmark = pytest.mark.django_db


class TestWeb:
    def test_anonymous_is_sent_to_sign_in(self, client: Client, alice_home: Home) -> None:
        response = client.get(reverse("homes:detail", kwargs={"home_id": alice_home.id}))
        assert response.status_code == 302
        assert reverse("account_login") in response["Location"]

    def test_list_shows_only_own_homes(
        self, client: Client, alice: User, alice_home: Home, bob_home: Home
    ) -> None:
        client.force_login(alice)
        response = client.get(reverse("homes:list"))
        assert response.status_code == 200
        assert alice_home.name in response.text
        assert bob_home.name not in response.text

    def test_detail_of_other_home_is_404(
        self, client: Client, alice: User, alice_home: Home, bob_home: Home
    ) -> None:
        client.force_login(alice)
        own = client.get(reverse("homes:detail", kwargs={"home_id": alice_home.id}))
        other = client.get(reverse("homes:detail", kwargs={"home_id": bob_home.id}))
        assert own.status_code == 200
        assert "Owner" in own.text
        assert other.status_code == 404

    def test_empty_list(self, client: Client, alice: User) -> None:
        client.force_login(alice)
        response = client.get(reverse("homes:list"))
        assert "not a member of any home" in response.text

    def test_stable_address(self, alice_home: Home) -> None:
        assert reverse("homes:detail", kwargs={"home_id": alice_home.id}) == (
            f"/h/{alice_home.id}/"
        )


class TestApi:
    def test_list_shows_only_own_homes(
        self, api_client: APIClient, alice: User, alice_home: Home, bob_home: Home
    ) -> None:
        api_client.force_authenticate(alice)
        response = api_client.get(reverse("api-v1:home-list"))
        assert response.status_code == 200
        ids = [item["id"] for item in response.json()["results"]]
        assert ids == [str(alice_home.id)]
        assert response.json()["results"][0]["role"] == "owner"

    def test_detail_of_other_home_is_404(
        self, api_client: APIClient, alice: User, bob_home: Home
    ) -> None:
        api_client.force_authenticate(alice)
        url = reverse("api-v1:home-detail", kwargs={"home_id": bob_home.id})
        assert api_client.get(url).status_code == 404
        assert api_client.patch(url, {"name": "Mine"}, format="json").status_code == 404
        bob_home.refresh_from_db()
        assert bob_home.name == "Flat"

    def test_anonymous_is_refused(self, api_client: APIClient, alice_home: Home) -> None:
        assert api_client.get(reverse("api-v1:home-list")).status_code == 401

    def test_member_can_rename(
        self,
        api_client: APIClient,
        bob: User,
        alice_home: Home,
        add_member: Callable[[Home, User, Role], Membership],
    ) -> None:
        add_member(alice_home, bob, Role.MEMBER)
        api_client.force_authenticate(bob)
        url = reverse("api-v1:home-detail", kwargs={"home_id": alice_home.id})
        response = api_client.patch(url, {"name": "Renamed"}, format="json")
        assert response.status_code == 200
        assert response.json()["name"] == "Renamed"
        assert response.json()["role"] == "member"

    def test_read_only_member_cannot_rename(
        self,
        api_client: APIClient,
        bob: User,
        alice_home: Home,
        add_member: Callable[[Home, User, Role], Membership],
    ) -> None:
        add_member(alice_home, bob, Role.READ_ONLY)
        api_client.force_authenticate(bob)
        url = reverse("api-v1:home-detail", kwargs={"home_id": alice_home.id})
        assert api_client.get(url).status_code == 200
        assert api_client.patch(url, {"name": "Renamed"}, format="json").status_code == 403

    def test_invalid_currency(self, api_client: APIClient, alice: User, alice_home: Home) -> None:
        api_client.force_authenticate(alice)
        url = reverse("api-v1:home-detail", kwargs={"home_id": alice_home.id})
        assert api_client.patch(url, {"currency": "euro"}, format="json").status_code == 400

    def test_put_is_not_offered(self, api_client: APIClient, alice: User, alice_home: Home) -> None:
        api_client.force_authenticate(alice)
        url = reverse("api-v1:home-detail", kwargs={"home_id": alice_home.id})
        assert api_client.put(url, {"name": "x"}, format="json").status_code == 405

    def test_cursor_pagination(self, api_client: APIClient, alice: User) -> None:
        for i in range(3):
            services.create_home(alice, name=f"Home {i}")
        api_client.force_authenticate(alice)
        first = api_client.get(reverse("api-v1:home-list"), {"page_size": 2}).json()
        assert len(first["results"]) == 2
        assert "cursor=" in first["next"]
        second = api_client.get(first["next"]).json()
        assert len(second["results"]) == 1
        assert second["next"] is None


class TestServices:
    def test_soft_deleted_home_is_hidden(self, alice: User, alice_home: Home) -> None:
        alice_home.soft_delete()
        assert not services.homes_for(alice).exists()
        assert Home.all_objects.filter(id=alice_home.id).exists()
        alice_home.restore()
        assert services.homes_for(alice).exists()

    def test_soft_deleted_membership_hides_home(self, alice: User, alice_home: Home) -> None:
        Membership.objects.filter(home=alice_home, user=alice).soft_delete()
        assert not services.homes_for(alice).exists()
        assert services.role_of(alice, alice_home) is None

    def test_inactive_user_sees_nothing(self, alice: User, alice_home: Home) -> None:
        alice.is_active = False
        alice.save()
        assert not services.homes_for(alice).exists()

    def test_update_home_rules(self, alice: User, bob: User, alice_home: Home) -> None:
        with pytest.raises(PermissionDenied):
            services.update_home(bob, alice_home, name="x")
        with pytest.raises(ValueError, match="Cannot change"):
            services.update_home(alice, alice_home, id="x")
        with pytest.raises(ValidationError):
            services.update_home(alice, alice_home, currency="eur")

    def test_one_active_membership_per_user(self, alice: User, alice_home: Home) -> None:
        from django.db import IntegrityError, transaction

        with pytest.raises(IntegrityError), transaction.atomic():
            Membership.objects.create(home=alice_home, user=alice, role=Role.MEMBER)

    def test_str(self, alice: User, alice_home: Home) -> None:
        membership = Membership.objects.get(home=alice_home)
        assert str(alice_home) == "Main house"
        assert str(membership) == "alice@example.com @ Main house (owner)"
        assert str(alice) == "alice@example.com"
