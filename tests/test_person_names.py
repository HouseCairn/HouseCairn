"""A person in charge is named by their display name, never by their address (docs/adr/0045)."""

from collections.abc import Callable

import pytest
from django.test import Client
from django.urls import reverse
from hypothesis import example, given, settings
from hypothesis import strategies as st
from rest_framework.test import APIClient

from housecairn.accounts import names
from housecairn.accounts import services as account_services
from housecairn.accounts.models import User
from housecairn.homes import services as homes_services
from housecairn.homes.models import Home, Membership, Role
from housecairn.tasks import agenda, services
from housecairn.tasks.models import Task
from tests.tasks_fixtures import TODAY

pytest_plugins = ("tests.tasks_fixtures", "tests.rooms_fixtures")
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root", "frozen_today")]

ADDRESS = "bob@example.com"


@pytest.fixture
def shared_task(
    alice: User, bob: User, alice_home: Home, add_member: Callable[..., Membership]
) -> Task:
    add_member(alice_home, bob, Role.MEMBER)
    task = services.create_task(
        alice, alice_home, title="Bleed the radiators", assignee=bob, due_on=None
    )
    occurrence = services.open_occurrence_of(task)
    assert occurrence is not None
    services.complete(bob, occurrence)
    services.create_task(alice, alice_home, title="Clean the gutters", assignee=bob, due_on=TODAY)
    return task


def pages(home: Home, task: Task) -> dict[str, str]:
    kwargs = {"home_id": home.id}
    return {
        "today": reverse("tasks:today", kwargs=kwargs),
        "list": reverse("tasks:list", kwargs=kwargs),
        # The history is the Done filter of the task list (docs/adr/0017).
        "history": f"{reverse('tasks:list', kwargs=kwargs)}?status=done",
        "history filtered": (
            f"{reverse('tasks:list', kwargs=kwargs)}?status=done&person={task.assignee_id}"
        ),
        "detail": reverse("tasks:detail", kwargs={**kwargs, "task_id": task.id}),
        "new": reverse("tasks:create", kwargs=kwargs),
        "edit": reverse("tasks:edit", kwargs={**kwargs, "task_id": task.id}),
        "household": reverse("homes:household", kwargs=kwargs),
    }


@pytest.mark.parametrize("display_name", ["Bobby", ""])
def test_the_address_of_a_member_is_on_no_task_page(
    client: Client,
    alice: User,
    bob: User,
    alice_home: Home,
    shared_task: Task,
    display_name: str,
) -> None:
    account_services.set_display_name(bob, display_name)
    alice_prefs = agenda.update_preferences(alice, today_group="person")
    assert alice_prefs.today_group == "person"
    client.force_login(alice)
    shown = display_name or "bob"
    for label, url in pages(alice_home, shared_task).items():
        response = client.get(url)
        assert response.status_code == 200, label
        text = response.text
        assert ADDRESS not in text, label
        if label in {"today", "history", "household", "edit", "new"}:
            assert shown in text, label


def test_the_occurrence_row_of_today_names_the_assignee(
    client: Client, alice: User, bob: User, alice_home: Home, shared_task: Task
) -> None:
    """Grouped as it is by default, Today shows the person on each row, by name."""
    account_services.set_display_name(bob, "Bobby")
    client.force_login(alice)
    assert agenda.preferences_of(alice).today_group != "person"  # the person is on the row
    page = client.get(pages(alice_home, shared_task)["today"]).text
    row = page[page.index("Clean the gutters") :]
    assert "Bobby" in row.split("</li>")[0]
    assert ADDRESS not in page
    assert "bob@" not in page


def test_the_home_of_a_member_names_them_too(
    client: Client, bob: User, alice_home: Home, shared_task: Task
) -> None:
    account_services.set_display_name(bob, "Bobby")
    client.force_login(bob)
    text = client.get(reverse("my-home")).text
    assert ADDRESS not in text
    assert "Clean the gutters" in text


def test_the_assignee_choice_lists_names(
    client: Client, bob: User, alice: User, alice_home: Home, shared_task: Task
) -> None:
    account_services.set_display_name(bob, "Bobby")
    client.force_login(alice)
    text = client.get(pages(alice_home, shared_task)["new"]).text
    assert ">Bobby</option>" in text
    assert f">{ADDRESS}</option>" not in text


def test_the_api_names_the_assignee_and_who_closed_it(
    api_client: APIClient, alice: User, bob: User, alice_home: Home, shared_task: Task
) -> None:
    account_services.set_display_name(bob, "Bobby")
    api_client.force_authenticate(alice)
    kwargs = {"home_id": alice_home.id}
    tasks = api_client.get(reverse("api-v1:home-task-list", kwargs=kwargs)).json()["results"]
    assert {t["assignee_name"] for t in tasks} == {"Bobby"}
    rows = api_client.get(reverse("api-v1:home-occurrence-list", kwargs=kwargs)).json()["results"]
    assert {r["assignee_name"] for r in rows} == {"Bobby"}
    assert "Bobby" in {r["completed_by_name"] for r in rows}
    members = api_client.get(reverse("api-v1:home-member-list", kwargs=kwargs)).json()["results"]
    assert {m["user"]["name"] for m in members} == {"alice", "Bobby"}


class TestSameName:
    """Two members of the same name show their address, in brackets, to be told apart."""

    @pytest.fixture
    def twins(
        self,
        alice: User,
        bob: User,
        alice_home: Home,
        add_member: Callable[..., Membership],
        make_user: Callable[..., User],
    ) -> User:
        carol = make_user("carol@example.com")
        add_member(alice_home, bob, Role.MEMBER)
        add_member(alice_home, carol, Role.MEMBER)
        account_services.set_display_name(bob, "Sam")
        account_services.set_display_name(carol, "sam")  # case is not a difference
        return carol

    def test_the_assignee_list(
        self, client: Client, alice: User, alice_home: Home, twins: User
    ) -> None:
        client.force_login(alice)
        text = client.get(reverse("tasks:create", kwargs={"home_id": alice_home.id})).text
        assert ">Sam (bob@example.com)</option>" in text
        assert ">sam (carol@example.com)</option>" in text
        # Alone with their name, a member shows no address.
        assert ">alice</option>" in text

    def test_the_done_by_list(
        self, client: Client, alice: User, alice_home: Home, twins: User
    ) -> None:
        client.force_login(alice)
        text = client.get(
            reverse("tasks:history", kwargs={"home_id": alice_home.id}), follow=True
        ).text
        assert ">Sam (bob@example.com)</option>" in text
        assert ">sam (carol@example.com)</option>" in text
        assert ">alice</option>" in text

    def test_a_name_alone_in_its_home_shows_no_address(
        self,
        client: Client,
        alice: User,
        bob: User,
        alice_home: Home,
        add_member: Callable[..., Membership],
    ) -> None:
        add_member(alice_home, bob, Role.MEMBER)
        account_services.set_display_name(bob, "Bobby")
        client.force_login(alice)
        for name in ("create", "history"):
            url = reverse(f"tasks:{name}", kwargs={"home_id": alice_home.id})
            text = client.get(url, follow=True).text
            assert ">Bobby</option>" in text
            assert "bob@example.com" not in text


class TestLabelsIgnoreFillers:
    """Two names the same on screen are told apart, whatever hides in them."""

    @pytest.mark.parametrize("other", ["Sam\u3164", "\u3164sam", "S\u115fAM", "Sam\u2800", "sam"])
    def test_a_filler_or_the_case_is_no_difference(
        self, alice: User, bob: User, other: str
    ) -> None:
        User.objects.filter(pk=alice.pk).update(display_name="Sam")
        User.objects.filter(pk=bob.pk).update(display_name=other)
        alice.refresh_from_db()
        bob.refresh_from_db()
        shown = names.labels([alice, bob])
        assert shown[alice.pk] == f"Sam ({alice.email})"
        assert shown[bob.pk].endswith(f"({bob.email})")

    def test_different_names_stay_alone(self, alice: User, bob: User) -> None:
        User.objects.filter(pk=alice.pk).update(display_name="Sam")
        User.objects.filter(pk=bob.pk).update(display_name="Sami\u3164")
        alice.refresh_from_db()
        bob.refresh_from_db()
        assert names.labels([alice, bob]) == {alice.pk: "Sam", bob.pk: "Sami"}


def _invisible() -> st.SearchStrategy[str]:
    return st.one_of(
        st.characters(categories=("Cc", "Cf", "Mn", "Me")),
        st.sampled_from(sorted(names._BLANK_GLYPHS)),
        # Unassigned and default-ignorable: renderers hide them.
        st.sampled_from(["\u2065", "\ufff0", "\U000e0080"]),
    )


class TestNameKey:
    """`same_name_key` ignores what draws nothing and the width, never a visible letter."""

    @given(
        base=st.text(st.characters(categories=("Lu", "Ll", "Lo", "Nd")), min_size=1, max_size=12),
        junk=st.lists(_invisible(), min_size=1, max_size=4),
        places=st.lists(st.integers(min_value=0, max_value=12), min_size=4, max_size=4),
    )
    # Falsifying cases: a mark that fuses with the letter before it in NFC, joiners, fillers.
    @example(base="e", junk=["\u0301"], places=[1, 0, 0, 0])
    @example(base="Sam", junk=["\u17b4"], places=[3, 0, 0, 0])
    @example(base="Sam", junk=["\u17b5"], places=[3, 0, 0, 0])
    @example(base="Sam", junk=["\u034f"], places=[2, 0, 0, 0])
    @example(base="Sam", junk=["\u200d"], places=[1, 0, 0, 0])
    @example(base="0", junk=["\u0345"], places=[0, 0, 0, 0])  # case folding makes it a letter
    @example(base="Sam", junk=["\u3164", "\u2800", "\u0000"], places=[0, 3, 1, 0])
    @example(base="Sam", junk=["\u20dd"], places=[1, 0, 0, 0])  # enclosing mark (Me)
    @example(base="Sam", junk=["\u2065"], places=[2, 0, 0, 0])  # unassigned, ignorable
    @example(base="Sam", junk=["\ufff0"], places=[3, 0, 0, 0])
    @settings(max_examples=300, deadline=None)
    def test_inserting_what_draws_nothing_changes_nothing(
        self, base: str, junk: list[str], places: list[int]
    ) -> None:
        noisy = base
        for char, at in zip(junk, places, strict=False):
            at %= len(noisy) + 1
            noisy = noisy[:at] + char + noisy[at:]
        assert names.same_name_key(noisy) == names.same_name_key(base)

    @given(st.text(st.characters(categories=("Lu", "Ll", "Nd")), min_size=1, max_size=12))
    @example("Sam")
    def test_the_full_width_form_is_the_same_name(self, text: str) -> None:
        wide = "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in text)
        assert names.same_name_key(wide) == names.same_name_key(text)

    @given(
        st.text(st.sampled_from("abcdefghij"), min_size=1, max_size=8),
        st.sampled_from("klmnopqrst"),
        st.integers(0, 7),
    )
    @example("sam", "x", 1)
    def test_a_visible_letter_is_a_difference(self, text: str, letter: str, at: int) -> None:
        at %= len(text)
        other = text[:at] + letter + text[at + 1 :]
        assert names.same_name_key(other) != names.same_name_key(text)

    def test_runs_of_spaces_are_one_space_and_the_ends_are_trimmed(self) -> None:
        assert names.same_name_key("  Sam \u3000\u00a0 Lee\u2003") == "sam lee"

    def test_a_cyrillic_look_alike_is_not_caught(self) -> None:
        """Assumed (docs/adr/0045): the address in brackets is the only proof of identity."""
        assert names.same_name_key("\u0405\u0430m") != names.same_name_key("Sam")


class TestTrimFillers:
    @pytest.mark.parametrize(
        "value",
        [
            "\u3000Sam\u3000",
            "\u00a0Sam\u00a0",
            "\u17b4Sam",
            "Sam\u17b5",
            "\u034fSam\u034f",
            "\u2003Sam",
            "Sam\ufff0",
            "\u2065Sam",
        ],
    )
    def test_ends_lose_blanks_and_spaces_of_any_kind(self, value: str) -> None:
        assert names.trim_fillers(value) == "Sam"

    def test_the_inside_stays_with_its_joiners(self) -> None:
        # A Persian word with a zero-width non-joiner inside it.
        persian = "\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645"
        family = "\U0001f469\u200d\U0001f467"  # emoji joined by a zero-width joiner
        for kept in (persian, family, f"{persian} {family}"):
            assert names.trim_fillers(f"\u3000{kept}\u00a0") == kept


REVIEW_CASES = [
    "Sam\u17b4",
    "Sam\u17b5",
    "Sa\u034fm",
    "Sa\u200dm",
    "\uff33\uff41\uff4d",
    "Sa\u2065m",
    "Sam\ufff0",
]


class TestInvisibleTwins:
    """Names that look like \"Sam\" are told apart by address in each list the review named."""

    @pytest.fixture
    def pair(
        self,
        alice: User,
        bob: User,
        alice_home: Home,
        add_member: Callable[..., Membership],
    ) -> tuple[User, User]:
        add_member(alice_home, bob, Role.MEMBER)
        return alice, bob

    @pytest.mark.parametrize("twin", REVIEW_CASES)
    def test_the_key_is_the_same(self, twin: str) -> None:
        assert names.same_name_key(twin) == names.same_name_key("Sam")

    @pytest.mark.parametrize("twin", REVIEW_CASES)
    def test_assignee_and_done_by_show_the_address(
        self, client: Client, pair: tuple[User, User], alice_home: Home, twin: str
    ) -> None:
        alice, bob = pair
        User.objects.filter(pk=alice.pk).update(display_name="Sam")
        User.objects.filter(pk=bob.pk).update(display_name=twin)
        client.force_login(alice)
        for name in ("create", "history"):
            url = reverse(f"tasks:{name}", kwargs={"home_id": alice_home.id})
            text = client.get(url, follow=True).text
            assert f"Sam ({alice.email})</option>" in text, name
            assert f"({bob.email})</option>" in text, name

    @pytest.mark.parametrize("twin", REVIEW_CASES)
    def test_the_audit_log_web_and_api_show_the_address(
        self,
        client: Client,
        api_client: APIClient,
        pair: tuple[User, User],
        alice_home: Home,
        twin: str,
    ) -> None:
        alice, bob = pair
        User.objects.filter(pk=alice.pk).update(display_name="Sam")
        User.objects.filter(pk=bob.pk).update(display_name=twin)
        membership = Membership.objects.get(user=bob, home=alice_home)
        homes_services.change_role(alice, membership, Role.READ_ONLY)
        client.force_login(alice)
        web = client.get(reverse("homes:audit", kwargs={"home_id": alice_home.id})).text
        assert f"Sam ({alice.email})" in web
        assert f"({bob.email})" in web
        api_client.force_authenticate(alice)
        url = reverse("api-v1:home-audit", kwargs={"home_id": alice_home.id})
        results = api_client.get(url).json()["results"]
        entry = next(e for e in results if e["action"] == "member.role_changed")
        assert entry["actor_name"] == f"Sam ({alice.email})"
        assert entry["target_name"].endswith(f"({bob.email})")
