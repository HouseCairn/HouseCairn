"""The language a person chooses in their display preferences (docs/adr/0042)."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import translation
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.instance import config
from housecairn.instance import settings_services as instance_services
from housecairn.tasks import agenda
from housecairn.tasks.models import DisplayPreference

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _back_to_english() -> Iterator[None]:
    """A request activates the person's language for its thread: do not leak it to other tests."""
    yield
    translation.activate("en")


@pytest.fixture
def signed_in(client: Client, alice: User) -> Client:
    client.force_login(alice)
    return client


@pytest.fixture
def admin_user(make_user: Callable[..., User]) -> User:
    return make_user("admin@example.com", is_staff=True, is_superuser=True)


def page(client: Client, **headers: Any) -> str:
    return client.get(reverse("display-preferences"), **headers).content.decode()


class TestPersonLanguage:
    def test_a_person_without_a_choice_follows_the_browser(self, signed_in: Client) -> None:
        assert "Display preferences" in page(signed_in, HTTP_ACCEPT_LANGUAGE="en")
        assert "Display preferences" not in page(signed_in, HTTP_ACCEPT_LANGUAGE="fr")

    def test_the_choice_wins_over_browser_cookie_and_default(
        self, signed_in: Client, alice: User, admin_user: User
    ) -> None:
        agenda.update_preferences(alice, language="fr")
        instance_services.update(admin_user, {"default_language": "en"})
        signed_in.cookies["django_language"] = "en"
        content = page(signed_in, HTTP_ACCEPT_LANGUAGE="en")
        assert "Display preferences" not in content
        assert 'lang="fr"' in content

    def test_it_applies_from_the_next_page(self, signed_in: Client) -> None:
        assert "Display preferences" in page(signed_in, HTTP_ACCEPT_LANGUAGE="en")
        signed_in.post(
            reverse("display-preferences"),
            {"today_group": "urgency", "horizon_days": "7", "language": "fr"},
        )
        assert "Display preferences" not in page(signed_in, HTTP_ACCEPT_LANGUAGE="en")
        signed_in.post(
            reverse("display-preferences"),
            {"today_group": "urgency", "horizon_days": "7", "language": ""},
        )
        assert "Display preferences" in page(signed_in, HTTP_ACCEPT_LANGUAGE="en")

    def test_it_is_personal(
        self, signed_in: Client, alice: User, bob: User, client: Client
    ) -> None:
        agenda.update_preferences(alice, language="fr")
        other = Client()
        other.force_login(bob)
        assert "Display preferences" in page(other, HTTP_ACCEPT_LANGUAGE="en")

    def test_a_language_the_instance_does_not_ship_is_refused(self, alice: User) -> None:
        from django.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            agenda.update_preferences(alice, language="de")
        assert DisplayPreference.objects.filter(language="de").count() == 0

    def test_the_api_reads_and_changes_it(self, alice: User) -> None:
        api = APIClient()
        api.force_authenticate(alice)
        url = reverse("api-v1:display-preferences")
        assert api.get(url).json()["language"] == ""
        assert api.patch(url, {"language": "fr"}, format="json").json()["language"] == "fr"
        assert agenda.preferences_of(alice).language == "fr"
        assert api.patch(url, {"language": "de"}, format="json").status_code == 400
        assert api.patch(url, {"language": ""}, format="json").json()["language"] == ""

    def test_the_default_of_the_instance_still_serves_those_without_a_choice(
        self, signed_in: Client, admin_user: User
    ) -> None:
        instance_services.update(admin_user, {"default_language": "fr"})
        assert config.get_setting("default_language") == "fr"
        assert "Display preferences" not in page(signed_in, HTTP_ACCEPT_LANGUAGE="de")


class TestStoredLanguageIsCheckedAgain:
    """A value in the database that the instance does not ship never reaches a page."""

    @pytest.mark.parametrize("stored", ["xx", "de", "../..", "fr\n", "fr\r\nX-Evil: 1", "FR"])
    def test_pages_and_api_fall_back(
        self, signed_in: Client, alice: User, alice_home: Any, stored: str
    ) -> None:
        agenda.update_preferences(alice, language="fr")
        DisplayPreference.objects.filter(user_id=alice.pk).update(language=stored)
        assert DisplayPreference.objects.get(user_id=alice.pk).language == stored
        home = alice_home
        urls = {
            "display-preferences": reverse("display-preferences"),
            "today": reverse("tasks:today", kwargs={"home_id": home.id}),
        }
        for name, url in urls.items():
            response = signed_in.get(url, HTTP_ACCEPT_LANGUAGE="en")
            assert response.status_code == 200, name
            content = response.content.decode()
            assert 'lang="en"' in content, name
            assert 'lang="xx"' not in content
            assert 'lang="de"' not in content
        api = signed_in.get(reverse("api-v1:display-preferences"), HTTP_ACCEPT_LANGUAGE="en")
        assert api.status_code == 200

    def test_the_fallback_is_the_choice_of_the_locale_middleware(
        self, signed_in: Client, alice: User
    ) -> None:
        agenda.update_preferences(alice, language="fr")
        DisplayPreference.objects.filter(user_id=alice.pk).update(language="xx")
        response = signed_in.get(reverse("display-preferences"), HTTP_ACCEPT_LANGUAGE="fr")
        assert response.status_code == 200
        assert 'lang="fr"' in response.content.decode()
