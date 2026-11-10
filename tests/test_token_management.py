"""Managing API tokens: the screen and `/api/v1/me/tokens/` (docs/adr/0007).

The format, the hashing and the checks of a token are in `test_apitokens.py`; here is what
a person does with them: create (the value shown once), list, revoke, and what a token
itself is never allowed to do.
"""

import json
import re
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import pytest
from django.db import connection
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.apitokens import services
from housecairn.apitokens.models import ApiToken, Scope
from housecairn.audit.models import AuditEvent
from housecairn.core.middleware import FORM_TOKEN_FIELD
from housecairn.homes.models import Home

pytestmark = pytest.mark.django_db

LIST = "api-v1:token-list"
CSRF = "a" * 32


def detail(token_id: Any) -> str:
    return reverse("api-v1:token-detail", kwargs={"token_id": token_id})


def post_json(client: Client, url: str, body: dict[str, Any]) -> Any:
    return client.post(url, json.dumps(body), content_type="application/json")


def bearer(raw: str) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


def home_url(home: Home) -> str:
    return reverse("api-v1:home-detail", kwargs={"home_id": home.id})


@pytest.fixture
def session(alice: User) -> APIClient:
    client = APIClient()
    client.force_login(alice)
    return client


@pytest.fixture
def web(alice: User) -> Client:
    client = Client()
    client.force_login(alice)
    return client


def create(client: APIClient, home: Home, **extra: Any) -> dict[str, Any]:
    response = client.post(
        reverse(LIST), {"name": "Home Assistant", "homes": [str(home.id)], **extra}, format="json"
    )
    assert response.status_code == 201, response.content
    body: dict[str, Any] = response.json()
    return body


class TestCreateThroughTheApi:
    def test_the_value_comes_once_and_is_never_stored(
        self, session: APIClient, alice_home: Home
    ) -> None:
        body = create(session, alice_home)
        raw = body["token"]
        assert raw.startswith("hc_")
        stored = ApiToken.objects.get(pk=body["id"])
        assert stored.digest == services.hash_token(raw)
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM apitokens_apitoken")
            assert all(raw not in str(v) for row in cursor.fetchall() for v in row)
        listed = session.get(reverse(LIST))
        assert listed.status_code == 200
        assert raw not in listed.content.decode()
        assert all("token" not in row for row in listed.json())

    def test_the_answer_is_not_cached(self, session: APIClient, alice_home: Home) -> None:
        response = session.post(
            reverse(LIST), {"name": "x", "homes": [str(alice_home.id)]}, format="json"
        )
        assert "no-store" in response["Cache-Control"]

    def test_defaults_are_read_only_and_the_instance_lifetime(
        self, session: APIClient, alice_home: Home
    ) -> None:
        body = create(session, alice_home)
        assert body["scopes"] == ["read"]
        assert body["homes"] == [str(alice_home.id)]
        token = ApiToken.objects.get(pk=body["id"])
        assert token.expires_at is not None
        assert timedelta(days=89) < token.expires_at - timezone.now() <= timedelta(days=90)

    def test_a_chosen_lifetime_and_scopes(self, session: APIClient, alice_home: Home) -> None:
        body = create(session, alice_home, scopes=["read", "write"], expires_in_days=365)
        token = ApiToken.objects.get(pk=body["id"])
        assert token.scopes == ["read", "write"]
        assert token.expires_at is not None
        assert timedelta(days=364) < token.expires_at - timezone.now() <= timedelta(days=365)

    @pytest.mark.parametrize("days", [0, 7, 3650, None, "never"])
    def test_the_lifetime_is_a_closed_choice_without_never(
        self, session: APIClient, alice_home: Home, days: Any
    ) -> None:
        response = session.post(
            reverse(LIST),
            {"name": "x", "homes": [str(alice_home.id)], "expires_in_days": days},
            format="json",
        )
        assert response.status_code == 400
        assert not ApiToken.objects.exists()

    @pytest.mark.parametrize(
        "extra", [{"scopes": []}, {"scopes": ["admin"]}, {"name": "  "}, {"homes": []}]
    )
    def test_invalid_input_creates_nothing(
        self, session: APIClient, alice_home: Home, extra: dict[str, Any]
    ) -> None:
        body = {"name": "x", "homes": [str(alice_home.id)], **extra}
        assert session.post(reverse(LIST), body, format="json").status_code == 400
        assert not ApiToken.objects.exists()

    def test_a_home_of_someone_else_is_refused_like_a_missing_one(
        self, session: APIClient, alice_home: Home, bob_home: Home
    ) -> None:
        theirs = session.post(
            reverse(LIST), {"name": "x", "homes": [str(bob_home.id)]}, format="json"
        )
        missing = session.post(
            reverse(LIST),
            {"name": "x", "homes": ["00000000-0000-0000-0000-000000000000"]},
            format="json",
        )
        assert theirs.status_code == missing.status_code == 400
        assert theirs.json() == missing.json()
        mixed = session.post(
            reverse(LIST),
            {"name": "x", "homes": [str(alice_home.id), str(bob_home.id)]},
            format="json",
        )
        assert mixed.status_code == 400
        assert not ApiToken.objects.exists()

    def test_a_home_that_requires_a_provider_cannot_be_opened_by_a_token(
        self, session: APIClient, alice_home: Home
    ) -> None:
        Home.objects.filter(pk=alice_home.pk).update(required_provider="corp")
        response = session.post(
            reverse(LIST), {"name": "x", "homes": [str(alice_home.id)]}, format="json"
        )
        assert response.status_code == 400

    def test_the_token_made_here_is_accepted_by_the_v1_api(
        self, session: APIClient, alice_home: Home
    ) -> None:
        raw = create(session, alice_home)["token"]
        assert bearer(raw).get(home_url(alice_home)).status_code == 200

    def test_the_scopes_do_not_imply_each_other(self, session: APIClient, alice_home: Home) -> None:
        raw = create(session, alice_home, scopes=["write"])["token"]
        assert bearer(raw).get(home_url(alice_home)).status_code == 403

    def test_the_last_use_shows_in_the_list(self, session: APIClient, alice_home: Home) -> None:
        body = create(session, alice_home)
        assert session.get(reverse(LIST)).json()[0]["last_used_at"] is None
        bearer(body["token"]).get(home_url(alice_home))
        assert session.get(reverse(LIST)).json()[0]["last_used_at"] is not None


class TestATokenManagesNoToken:
    @pytest.fixture
    def raw(self, alice: User, alice_home: Home) -> str:
        return services.issue_token(
            alice,
            name="power",
            scopes=[Scope.READ, Scope.WRITE, Scope.EVENTS],
            homes=[alice_home],
        )[1]

    def test_it_cannot_list_create_or_revoke(self, raw: str, alice: User, alice_home: Home) -> None:
        other = services.issue_token(alice, name="o", scopes=["read"], homes=[alice_home])[0]
        client = bearer(raw)
        assert client.get(reverse(LIST)).status_code == 403
        made = client.post(
            reverse(LIST), {"name": "x", "homes": [str(alice_home.id)]}, format="json"
        )
        assert made.status_code == 403
        assert client.delete(detail(other.id)).status_code == 403
        assert ApiToken.objects.count() == 2
        other.refresh_from_db()
        assert other.revoked_at is None


class TestIsolation:
    def test_each_person_sees_only_their_tokens(
        self, session: APIClient, alice_home: Home, bob: User, bob_home: Home
    ) -> None:
        create(session, alice_home)
        services.issue_token(bob, name="bob's", scopes=["read"], homes=[bob_home])
        listed = session.get(reverse(LIST)).json()
        assert [row["name"] for row in listed] == ["Home Assistant"]

    def test_the_token_of_another_is_not_found_and_stays_valid(
        self, session: APIClient, alice_home: Home, bob: User, bob_home: Home
    ) -> None:
        theirs, raw = services.issue_token(bob, name="b", scopes=["read"], homes=[bob_home])
        assert session.delete(detail(theirs.id)).status_code == 404
        assert bearer(raw).get(home_url(bob_home)).status_code == 200

    def test_an_unknown_id_is_the_same_404(self, session: APIClient) -> None:
        assert session.delete(detail("00000000-0000-0000-0000-000000000000")).status_code == 404


class TestRevocation:
    def test_the_next_request_is_refused(self, session: APIClient, alice_home: Home) -> None:
        body = create(session, alice_home)
        client = bearer(body["token"])
        assert client.get(home_url(alice_home)).status_code == 200
        assert session.delete(detail(body["id"])).status_code == 204
        assert client.get(home_url(alice_home)).status_code == 401
        assert session.get(reverse(LIST)).json() == []
        assert session.delete(detail(body["id"])).status_code == 404

    def test_an_expired_token_is_listed_to_be_revoked_and_does_not_work(
        self, session: APIClient, alice_home: Home
    ) -> None:
        body = create(session, alice_home)
        ApiToken.objects.filter(pk=body["id"]).update(expires_at=timezone.now() - timedelta(1))
        assert bearer(body["token"]).get(home_url(alice_home)).status_code == 401
        assert [row["id"] for row in session.get(reverse(LIST)).json()] == [body["id"]]
        assert session.delete(detail(body["id"])).status_code == 204


class TestCsrf:
    @pytest.fixture
    def strict(self, alice: User) -> Client:
        client = Client(enforce_csrf_checks=True)
        client.force_login(alice)
        client.cookies["csrftoken"] = CSRF
        return client

    def test_writes_need_the_csrf_token(self, strict: Client, alice_home: Home) -> None:
        body = {"name": "x", "homes": [str(alice_home.id)]}
        assert post_json(strict, reverse(LIST), body).status_code == 403
        assert not ApiToken.objects.exists()
        ok = strict.post(
            reverse(LIST),
            json.dumps(body),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=CSRF,
        )
        assert ok.status_code == 201

    def test_revoking_needs_it_too(self, strict: Client, alice: User, alice_home: Home) -> None:
        token = services.issue_token(alice, name="t", scopes=["read"], homes=[alice_home])[0]
        assert strict.delete(detail(token.id)).status_code == 403
        token.refresh_from_db()
        assert token.revoked_at is None
        assert strict.delete(detail(token.id), HTTP_X_CSRFTOKEN=CSRF).status_code == 204


class TestAuditLog:
    def test_creation_and_revocation_are_logged_without_the_value(
        self, session: APIClient, alice_home: Home, alice: User
    ) -> None:
        body = create(session, alice_home)
        session.delete(detail(body["id"]))
        entries = list(
            AuditEvent.objects.filter(action__startswith="apitoken.").order_by("created_at")
        )
        assert [e.action for e in entries] == ["apitoken.created", "apitoken.revoked"]
        assert all(e.actor_id == alice.pk for e in entries)
        assert all(e.detail == {"title": "Home Assistant"} for e in entries)
        assert all(body["token"] not in str(e.detail) + e.label for e in entries)
        assert entries[0].label == "API token created: Home Assistant"

    def test_revoking_twice_logs_once(self, alice: User, alice_home: Home) -> None:
        token = services.issue_token(alice, name="t", scopes=["read"], homes=[alice_home])[0]
        services.revoke_token(alice, token)
        services.revoke_token(alice, token)
        assert AuditEvent.objects.filter(action="apitoken.revoked").count() == 1


class TestScreen:
    def test_the_list_needs_a_sign_in(self, client: Client) -> None:
        assert client.get(reverse("api-tokens:list")).status_code == 302

    def test_it_is_in_more_next_to_security(self, web: Client) -> None:
        page = web.get(reverse("more")).content.decode()
        assert reverse("api-tokens:list") in page
        assert page.index(reverse("api-tokens:list")) < page.index(reverse("more-security"))

    def test_create_then_see_the_value_once(self, web: Client, alice_home: Home) -> None:
        page = web.get(reverse("api-tokens:new")).content.decode()
        marker = f'name="{FORM_TOKEN_FIELD}" value="'
        form_token = page.split(marker, 1)[1].split('"', 1)[0]
        data = urlencode(
            {
                "name": "Home Assistant",
                "scopes": ["read"],
                "homes": [str(alice_home.id)],
                "lifetime_days": "90",
                FORM_TOKEN_FIELD: form_token,
            },
            doseq=True,
        )
        # A browser's post is read by the CSRF check first; the test client skips that
        # check, so the form goes urlencoded, which the middleware reads itself.
        form = "application/x-www-form-urlencoded"
        response = web.post(reverse("api-tokens:new"), data, content_type=form)
        assert response.status_code == 200
        assert "no-store" in response["Cache-Control"]
        body = response.content.decode()
        raw = body.split('id="token-value"', 1)[1].split('value="', 1)[1].split('"', 1)[0]
        assert raw.startswith("hc_")
        assert bearer(raw).get(home_url(alice_home)).status_code == 200
        # Never again: not in the list, not in the database.
        assert raw not in web.get(reverse("api-tokens:list")).content.decode()
        assert ApiToken.objects.get().digest == services.hash_token(raw)
        assert ApiToken.objects.filter(prefix=raw[:9]).count() == 1
        # The same form sent again (back button, double tap) creates nothing more.
        again = web.post(reverse("api-tokens:new"), data, content_type=form)
        assert again.status_code == 302
        assert ApiToken.objects.count() == 1

    def test_the_form_offers_read_ticked_90_days_and_only_my_open_homes(
        self, web: Client, alice_home: Home, bob_home: Home
    ) -> None:
        page = web.get(reverse("api-tokens:new")).content.decode()
        assert "Main house" in page
        assert "Flat" not in page
        assert "checked" in page.split('value="read"')[1].split(">")[0]
        assert "checked" in page.split('value="90"')[1].split(">")[0]
        assert 'value="365"' in page
        assert "never" not in page.lower()
        assert "Home Assistant" in page

    def test_a_home_of_someone_else_is_refused_by_the_form(
        self, web: Client, alice_home: Home, bob_home: Home
    ) -> None:
        response = web.post(
            reverse("api-tokens:new"),
            {
                "name": "x",
                "scopes": ["read"],
                "homes": [str(bob_home.id)],
                "lifetime_days": "90",
            },
        )
        assert response.status_code == 200
        assert not ApiToken.objects.exists()

    def test_the_list_shows_what_is_known_and_never_the_value(
        self, web: Client, alice: User, alice_home: Home
    ) -> None:
        token, raw = services.issue_token(
            alice, name="Dashboard", scopes=["read", "events"], homes=[alice_home]
        )
        ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        page = web.get(reverse("api-tokens:list")).content.decode()
        for shown in ("Dashboard", token.prefix, "Main house", "Post events, Read"):
            assert shown in page
        for hidden in (raw, token.digest):
            assert hidden not in page
        assert 'data-label="Last used"' in page

    def test_the_action_cell_has_a_label_so_that_a_phone_draws_it(
        self, web: Client, alice: User, alice_home: Home
    ) -> None:
        # Under 56 rem `.table-stack td:not([data-label])` is not drawn: no label, no Revoke.
        services.issue_token(alice, name="Dashboard", scopes=["read"], homes=[alice_home])
        page = web.get(reverse("api-tokens:list")).content.decode()
        cells = re.findall(r"<td([^>]*)>(?=<a[^>]*/revoke/)", page)
        assert len(cells) == 1
        assert 'data-label="Actions"' in cells[0]

    def test_the_list_speaks_french_to_a_french_reader(self, alice: User, alice_home: Home) -> None:
        services.issue_token(alice, name="Dashboard", scopes=["read", "write"], homes=[alice_home])
        client = Client(headers={"accept-language": "fr"})
        client.force_login(alice)
        page = client.get(reverse("api-tokens:list")).content.decode()
        assert "Lecture, Écriture" in page or "Écriture, Lecture" in page
        for raw in (">read<", "read, ", ", write", ">write<"):
            assert raw not in page

    def test_the_form_words_the_expiry_in_the_language_of_the_reader(
        self, alice: User, alice_home: Home
    ) -> None:
        client = Client(headers={"accept-language": "fr"})
        client.force_login(alice)
        page = client.get(reverse("api-tokens:new")).content.decode()
        for shown in ("30 jours", "90 jours", "1 an"):
            assert shown in page
        assert "90 days" not in page
        # Another request in English is not stuck with the language of the first one.
        english = Client(headers={"accept-language": "en"})
        english.force_login(alice)
        assert "90 days" in english.get(reverse("api-tokens:new")).content.decode()

    def test_an_expired_token_says_so(self, web: Client, alice: User, alice_home: Home) -> None:
        token = services.issue_token(alice, name="Old", scopes=["read"], homes=[alice_home])[0]
        ApiToken.objects.filter(pk=token.pk).update(expires_at=timezone.now() - timedelta(1))
        assert "Expired on" in web.get(reverse("api-tokens:list")).content.decode()

    def test_revocation_asks_first_then_cuts_the_token(
        self, web: Client, alice: User, alice_home: Home
    ) -> None:
        token, raw = services.issue_token(alice, name="t", scopes=["read"], homes=[alice_home])
        url = reverse("api-tokens:revoke", kwargs={"token_id": token.id})
        assert web.get(url).status_code == 200
        token.refresh_from_db()
        assert token.revoked_at is None
        assert bearer(raw).get(home_url(alice_home)).status_code == 200
        response = web.post(url)
        assert response.status_code == 302
        assert response["Location"] == reverse("api-tokens:list")
        assert bearer(raw).get(home_url(alice_home)).status_code == 401
        assert "t" not in [
            r["token"].name for r in web.get(reverse("api-tokens:list")).context["rows"]
        ]

    def test_the_token_of_another_person_is_a_404_on_the_screen(
        self, web: Client, bob: User, bob_home: Home
    ) -> None:
        token, raw = services.issue_token(bob, name="b", scopes=["read"], homes=[bob_home])
        url = reverse("api-tokens:revoke", kwargs={"token_id": token.id})
        assert web.get(url).status_code == 404
        assert web.post(url).status_code == 404
        assert bearer(raw).get(home_url(bob_home)).status_code == 200

    def test_the_return_rule(self, web: Client, alice: User, alice_home: Home) -> None:
        listing = reverse("api-tokens:list")
        # Without `next`, the back link of the list leads to More, of the form to the list.
        assert f'href="{reverse("more")}"' in web.get(listing).content.decode()
        assert f'href="{listing}"' in web.get(reverse("api-tokens:new")).content.decode()
        token = services.issue_token(alice, name="t", scopes=["read"], homes=[alice_home])[0]
        revoke = reverse("api-tokens:revoke", kwargs={"token_id": token.id})
        page = web.get(f"{revoke}?next={listing}").content.decode()
        assert f'href="{listing}"' in page
        assert web.post(revoke).status_code == 302
