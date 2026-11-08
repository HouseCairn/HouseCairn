"""The display name of a person: the helper, the profile screen, the API (docs/adr/0045)."""

from collections.abc import Callable
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts import services
from housecairn.accounts.models import User
from housecairn.accounts.names import person_name
from housecairn.apitokens import services as token_services
from housecairn.homes.models import Home

pytestmark = pytest.mark.django_db


class TestHelper:
    def test_display_name_then_full_name_then_the_start_of_the_address(
        self, make_user: Callable[..., User]
    ) -> None:
        user = make_user("jane.doe@example.com", first_name="Jane", last_name="Doe")
        assert person_name(user) == "Jane Doe"
        user.display_name = "  Janie "
        assert person_name(user) == "Janie"
        user.display_name = ""
        user.first_name = user.last_name = ""
        assert person_name(user) == "jane.doe"

    def test_never_the_whole_address(self, make_user: Callable[..., User]) -> None:
        assert "@" not in person_name(make_user("someone@example.com"))

    def test_nobody_has_no_name(self) -> None:
        assert person_name(None) == ""


class TestService:
    def test_it_is_cleaned_to_one_line_without_control_characters(self, alice: User) -> None:
        services.set_display_name(alice, "  Al\x07ice\n\u202e Smith\u200b ")
        alice.refresh_from_db()
        assert alice.display_name == "Alice Smith"

    def test_it_can_be_emptied(self, alice: User) -> None:
        services.set_display_name(alice, "Ally")
        services.set_display_name(alice, "")
        alice.refresh_from_db()
        assert alice.display_name == ""

    def test_it_is_bounded(self, alice: User) -> None:
        with pytest.raises(ValidationError):
            services.set_display_name(alice, "x" * 61)
        assert services.set_display_name(alice, "x" * 60).display_name == "x" * 60

    def test_it_changes_nothing_else(self, alice: User) -> None:
        before = User.objects.get(pk=alice.pk)
        services.set_display_name(alice, "Ally")
        after = User.objects.get(pk=alice.pk)
        assert (after.email, after.password, after.is_staff) == (
            before.email,
            before.password,
            before.is_staff,
        )


MISLEADING = [
    "alice@example.com",
    "Ally @ work",
    "@boss",
    "Ally\uff20x",  # a full-width at sign
    "\u3164",  # Hangul filler
    "\u115f\u1160",  # Hangul choseong and jungseong fillers
    "\u2800",  # blank Braille pattern
    "\u2800 \u3164 \u00a0",
    "\u0301\u0301",  # combining marks with nothing to stand on
]


class TestMisleadingNames:
    """A name that passes for an address, or that draws nothing, is no name."""

    @pytest.mark.parametrize("value", MISLEADING)
    def test_the_service_refuses_it(self, alice: User, value: str) -> None:
        with pytest.raises(ValidationError):
            services.set_display_name(alice, value)
        alice.refresh_from_db()
        assert alice.display_name == ""

    @pytest.mark.parametrize("value", MISLEADING)
    def test_the_screen_refuses_it(self, client: Client, alice: User, value: str) -> None:
        client.force_login(alice)
        response = client.post(reverse("profile"), {"display_name": value})
        assert response.status_code == 200
        alice.refresh_from_db()
        assert alice.display_name == ""

    @pytest.mark.parametrize("value", MISLEADING)
    def test_the_api_refuses_it(self, api_client: APIClient, alice: User, value: str) -> None:
        api_client.force_authenticate(alice)
        response = api_client.patch(reverse("api-v1:me"), {"display_name": value}, format="json")
        assert response.status_code == 400
        assert "display_name" in response.json()
        alice.refresh_from_db()
        assert alice.display_name == ""

    @pytest.mark.parametrize("value", ["Zoë", "Chloé Durand", "李雷", "Ally 🙂", "O'Neil", ""])
    def test_a_real_name_stays_welcome(self, alice: User, value: str) -> None:
        assert services.set_display_name(alice, value).display_name == value


class TestScreen:
    def test_the_profile_screen_changes_it(self, client: Client, alice: User) -> None:
        client.force_login(alice)
        url = reverse("profile")
        assert client.get(url).status_code == 200
        response = client.post(url, {"display_name": "Ally"})
        assert response.status_code == 302
        alice.refresh_from_db()
        assert alice.display_name == "Ally"

    def test_a_too_long_name_is_refused_on_the_screen(self, client: Client, alice: User) -> None:
        client.force_login(alice)
        response = client.post(reverse("profile"), {"display_name": "x" * 61})
        assert response.status_code == 200
        alice.refresh_from_db()
        assert alice.display_name == ""

    def test_it_is_for_people_signed_in(self, client: Client) -> None:
        assert client.get(reverse("profile")).status_code == 302

    def test_it_is_offered_on_the_more_page(self, client: Client, alice: User) -> None:
        client.force_login(alice)
        assert reverse("profile") in client.get(reverse("more")).text


class TestApi:
    def test_me_reads_and_changes_it(self, api_client: APIClient, alice: User) -> None:
        api_client.force_authenticate(alice)
        url = reverse("api-v1:me")
        body = api_client.get(url).json()
        assert body["email"] == "alice@example.com"
        assert body["display_name"] == ""
        assert body["name"] == "alice"
        patched = api_client.patch(url, {"display_name": " Ally\x07 "}, format="json")
        assert patched.status_code == 200
        assert patched.json()["display_name"] == "Ally"
        assert patched.json()["name"] == "Ally"

    def test_the_address_and_the_identifier_cannot_be_changed(
        self, api_client: APIClient, alice: User
    ) -> None:
        api_client.force_authenticate(alice)
        api_client.patch(
            reverse("api-v1:me"), {"email": "x@example.com", "is_staff": True}, format="json"
        )
        alice.refresh_from_db()
        assert alice.email == "alice@example.com"
        assert not alice.is_staff

    def test_too_long_is_a_400(self, api_client: APIClient, alice: User) -> None:
        api_client.force_authenticate(alice)
        response = api_client.patch(reverse("api-v1:me"), {"display_name": "x" * 61}, format="json")
        assert response.status_code == 400

    def test_it_needs_authentication(self, api_client: APIClient) -> None:
        assert api_client.get(reverse("api-v1:me")).status_code in (401, 403)


class TestApiTokens:
    """A token stands for an integration tied to some homes: the account is not its business."""

    def _client(self, alice: User, home: Home, scopes: list[str]) -> APIClient:
        _token, raw = token_services.issue_token(
            alice, name="t", scopes=scopes, homes=[home], lifetime=timedelta(days=1)
        )
        found = APIClient()
        found.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        return found

    def test_a_write_token_cannot_rename_the_account(self, alice: User, alice_home: Home) -> None:
        writing = self._client(alice, alice_home, ["read", "write"])
        response = writing.patch(reverse("api-v1:me"), {"display_name": "Mallory"}, format="json")
        assert response.status_code == 403
        alice.refresh_from_db()
        assert alice.display_name == ""

    def test_a_token_still_reads_the_account(self, alice: User, alice_home: Home) -> None:
        reading = self._client(alice, alice_home, ["read"])
        assert reading.get(reverse("api-v1:me")).status_code == 200

    def test_the_person_signed_in_still_renames_it(self, alice: User) -> None:
        signed_in = APIClient()
        signed_in.force_authenticate(alice)
        response = signed_in.patch(reverse("api-v1:me"), {"display_name": "Ally"}, format="json")
        assert response.status_code == 200
