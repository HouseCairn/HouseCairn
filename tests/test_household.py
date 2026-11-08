"""Household of a home: roles, changes, leaving, ownership (docs/adr/0020)."""

from collections.abc import Callable

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.homes import services
from housecairn.homes.models import Home, Membership, Role

pytestmark = pytest.mark.django_db

AddMember = Callable[[Home, User, Role], Membership]


def owner_of(home: Home) -> Membership:
    return Membership.objects.get(home=home, role=Role.OWNER)


class TestRules:
    def test_create_home_makes_the_creator_owner(self, alice: User) -> None:
        home = services.create_home(alice, name="Cottage", currency="CHF")
        assert services.role_of(alice, home) == Role.OWNER

    def test_create_home_validates_the_currency(self, alice: User) -> None:
        with pytest.raises(ValidationError):
            services.create_home(alice, name="Cottage", currency="euro")

    def test_owner_changes_a_role(
        self, alice: User, bob: User, alice_home: Home, add_member: AddMember
    ) -> None:
        membership = add_member(alice_home, bob, Role.MEMBER)
        services.change_role(alice, membership, Role.READ_ONLY)
        assert services.role_of(bob, alice_home) == Role.READ_ONLY

    @pytest.mark.parametrize("role", [Role.MEMBER, Role.READ_ONLY])
    def test_only_owners_change_roles(
        self,
        alice: User,
        bob: User,
        make_user: Callable[..., User],
        alice_home: Home,
        add_member: AddMember,
        role: Role,
    ) -> None:
        add_member(alice_home, bob, role)
        carol = add_member(alice_home, make_user(), Role.READ_ONLY)
        with pytest.raises(PermissionDenied):
            services.change_role(bob, carol, Role.OWNER)
        with pytest.raises(PermissionDenied):
            services.change_role(bob, Membership.objects.get(user=bob), Role.OWNER)
        assert services.role_of(bob, alice_home) == role

    def test_the_last_owner_cannot_be_demoted_removed_or_leave(
        self, alice: User, alice_home: Home
    ) -> None:
        mine = owner_of(alice_home)
        with pytest.raises(ValidationError):
            services.change_role(alice, mine, Role.MEMBER)
        with pytest.raises(ValidationError):
            services.remove_member(alice, mine)
        with pytest.raises(ValidationError):
            services.leave_home(alice, alice_home)
        assert services.role_of(alice, alice_home) == Role.OWNER

    def test_with_two_owners_one_can_step_down(
        self, alice: User, bob: User, alice_home: Home, add_member: AddMember
    ) -> None:
        add_member(alice_home, bob, Role.OWNER)
        services.change_role(alice, owner_of_user(alice_home, alice), Role.MEMBER)
        assert services.role_of(alice, alice_home) == Role.MEMBER
        with pytest.raises(ValidationError):
            services.leave_home(bob, alice_home)

    def test_transfer_ownership(
        self, alice: User, bob: User, alice_home: Home, add_member: AddMember
    ) -> None:
        membership = add_member(alice_home, bob, Role.READ_ONLY)
        services.transfer_ownership(alice, alice_home, membership)
        assert services.role_of(bob, alice_home) == Role.OWNER
        assert services.role_of(alice, alice_home) == Role.MEMBER

    def test_transfer_needs_an_owner_and_another_member(
        self, alice: User, bob: User, alice_home: Home, add_member: AddMember
    ) -> None:
        membership = add_member(alice_home, bob, Role.MEMBER)
        with pytest.raises(PermissionDenied):
            services.transfer_ownership(bob, alice_home, membership)
        with pytest.raises(ValidationError):
            services.transfer_ownership(alice, alice_home, owner_of(alice_home))

    def test_owner_removes_a_member_who_then_sees_nothing(
        self, alice: User, bob: User, alice_home: Home, add_member: AddMember
    ) -> None:
        membership = add_member(alice_home, bob, Role.MEMBER)
        services.remove_member(alice, membership)
        assert services.role_of(bob, alice_home) is None
        assert not services.homes_for(bob).exists()
        assert Membership.all_objects.get(pk=membership.pk).deleted_at is not None

    def test_a_member_cannot_remove_another(
        self,
        alice: User,
        bob: User,
        make_user: Callable[..., User],
        alice_home: Home,
        add_member: AddMember,
    ) -> None:
        add_member(alice_home, bob, Role.MEMBER)
        carol = add_member(alice_home, make_user(), Role.MEMBER)
        with pytest.raises(PermissionDenied):
            services.remove_member(bob, carol)
        with pytest.raises(PermissionDenied):
            services.remove_member(bob, owner_of(alice_home))

    def test_a_member_leaves(self, bob: User, alice_home: Home, add_member: AddMember) -> None:
        add_member(alice_home, bob, Role.READ_ONLY)
        services.leave_home(bob, alice_home)
        assert services.role_of(bob, alice_home) is None

    def test_a_removed_member_can_be_added_again(
        self, alice: User, bob: User, alice_home: Home, add_member: AddMember
    ) -> None:
        services.remove_member(alice, add_member(alice_home, bob, Role.MEMBER))
        add_member(alice_home, bob, Role.READ_ONLY)
        assert services.role_of(bob, alice_home) == Role.READ_ONLY

    def test_members_of_another_home_cannot_be_reached(
        self, alice: User, bob: User, alice_home: Home, bob_home: Home
    ) -> None:
        with pytest.raises(PermissionDenied):
            services.change_role(alice, owner_of(bob_home), Role.MEMBER)
        with pytest.raises(PermissionDenied):
            services.remove_member(alice, owner_of(bob_home))
        with pytest.raises(PermissionDenied):
            services.transfer_ownership(alice, bob_home, owner_of(bob_home))


def owner_of_user(home: Home, user: User) -> Membership:
    return Membership.objects.get(home=home, user=user)


class TestWeb:
    def test_create_a_home(self, client: Client, alice: User) -> None:
        client.force_login(alice)
        response = client.post(reverse("homes:create"), {"name": "Cottage", "currency": "EUR"})
        home = Home.objects.get(name="Cottage")
        assert response.status_code == 302
        assert response["Location"] == reverse("homes:detail", kwargs={"home_id": home.id})
        assert services.role_of(alice, home) == Role.OWNER

    def test_owner_sees_the_household_and_the_invitation_form(
        self, client: Client, alice: User, bob: User, alice_home: Home, add_member: AddMember
    ) -> None:
        add_member(alice_home, bob, Role.READ_ONLY)
        client.force_login(alice)
        html = client.get(reverse("homes:household", kwargs={"home_id": alice_home.id})).text
        # People are named, not addressed (docs/adr/0045); the address is on their own page.
        assert "alice@example.com" not in html
        assert "bob@example.com" not in html
        assert ">bob<" in html
        assert "read only" in html
        assert reverse("homes:invite", kwargs={"home_id": alice_home.id}) in html

    def test_member_sees_the_household_without_management(
        self, client: Client, bob: User, alice_home: Home, add_member: AddMember
    ) -> None:
        add_member(alice_home, bob, Role.MEMBER)
        client.force_login(bob)
        html = client.get(reverse("homes:household", kwargs={"home_id": alice_home.id})).text
        assert ">alice<" in html
        assert reverse("homes:invite", kwargs={"home_id": alice_home.id}) not in html
        assert "Only owners invite" in html

    def test_other_home_is_404(self, client: Client, alice: User, bob_home: Home) -> None:
        client.force_login(alice)
        kwargs = {"home_id": bob_home.id}
        assert client.get(reverse("homes:household", kwargs=kwargs)).status_code == 404
        member = owner_of(bob_home)
        member_kwargs = {**kwargs, "member_id": member.id}
        assert client.get(reverse("homes:member", kwargs=member_kwargs)).status_code == 404
        assert client.post(reverse("homes:member-remove", kwargs=member_kwargs)).status_code == 404
        assert services.role_of(member.user, bob_home) == Role.OWNER

    def test_role_change_remove_and_transfer(
        self,
        client: Client,
        alice: User,
        bob: User,
        make_user: Callable[..., User],
        alice_home: Home,
        add_member: AddMember,
    ) -> None:
        bob_membership = add_member(alice_home, bob, Role.MEMBER)
        carol = make_user("carol@example.com")
        carol_membership = add_member(alice_home, carol, Role.MEMBER)
        client.force_login(alice)
        kwargs = {"home_id": alice_home.id, "member_id": bob_membership.id}
        page = client.get(reverse("homes:member", kwargs=kwargs)).text
        assert "Make owner" in page
        client.post(reverse("homes:member-role", kwargs=kwargs), {"role": "read_only"})
        assert services.role_of(bob, alice_home) == Role.READ_ONLY
        carol_kwargs = {"home_id": alice_home.id, "member_id": carol_membership.id}
        client.post(reverse("homes:member-remove", kwargs=carol_kwargs))
        assert services.role_of(carol, alice_home) is None
        client.post(reverse("homes:transfer", kwargs=kwargs))
        assert services.role_of(bob, alice_home) == Role.OWNER
        assert services.role_of(alice, alice_home) == Role.MEMBER

    def test_last_owner_gets_a_message_not_an_error(
        self, client: Client, alice: User, alice_home: Home
    ) -> None:
        client.force_login(alice)
        response = client.post(
            reverse("homes:leave", kwargs={"home_id": alice_home.id}), follow=True
        )
        assert response.status_code == 200
        assert "at least one owner" in response.text
        assert services.role_of(alice, alice_home) == Role.OWNER

    def test_member_leaves(
        self, client: Client, bob: User, alice_home: Home, add_member: AddMember
    ) -> None:
        add_member(alice_home, bob, Role.MEMBER)
        client.force_login(bob)
        response = client.post(reverse("homes:leave", kwargs={"home_id": alice_home.id}))
        assert response["Location"] == reverse("homes:list")
        assert services.role_of(bob, alice_home) is None

    def test_leaving_and_removing_are_confirmed_first(
        self, client: Client, alice: User, bob: User, alice_home: Home, add_member: AddMember
    ) -> None:
        """A page asks first (GET changes nothing); only the POST acts."""
        membership = add_member(alice_home, bob, Role.MEMBER)
        client.force_login(alice)
        remove = reverse(
            "homes:member-remove", kwargs={"home_id": alice_home.id, "member_id": membership.id}
        )
        page = client.get(remove)
        assert page.status_code == 200
        assert "Remove this member?" in page.text
        assert services.role_of(bob, alice_home) == Role.MEMBER
        member_page = client.get(
            reverse("homes:member", kwargs={"home_id": alice_home.id, "member_id": membership.id})
        )
        assert f'href="{remove}"' in member_page.text
        client.force_login(bob)
        leave = reverse("homes:leave", kwargs={"home_id": alice_home.id})
        asked = client.get(leave)
        assert "Leave this home?" in asked.text
        assert services.role_of(bob, alice_home) == Role.MEMBER
        client.post(leave)
        assert services.role_of(bob, alice_home) is None

    def test_member_cannot_manage(
        self,
        client: Client,
        bob: User,
        alice_home: Home,
        add_member: AddMember,
    ) -> None:
        add_member(alice_home, bob, Role.MEMBER)
        client.force_login(bob)
        owner = owner_of(alice_home)
        kwargs = {"home_id": alice_home.id, "member_id": owner.id}
        assert (
            client.post(reverse("homes:member-role", kwargs=kwargs), {"role": "member"}).status_code
            == 403
        )
        assert client.post(reverse("homes:transfer", kwargs=kwargs)).status_code == 403
        assert services.role_of(owner.user, alice_home) == Role.OWNER

    def test_french(self, client: Client, alice: User, alice_home: Home) -> None:
        client.force_login(alice)
        html = client.get(
            reverse("homes:household", kwargs={"home_id": alice_home.id}),
            headers={"Accept-Language": "fr"},
        ).text
        assert "Foyer et rôles" in html
        assert "Inviter quelqu" in html


class TestApi:
    def url(self, home: Home, member: Membership | None = None, suffix: str = "") -> str:
        if member is None:
            return reverse("api-v1:home-member-list", kwargs={"home_id": home.id})
        name = "api-v1:home-member-make-owner" if suffix else "api-v1:home-member-detail"
        return reverse(name, kwargs={"home_id": home.id, "member_id": member.id})

    def test_create_a_home(self, api_client: APIClient, alice: User) -> None:
        api_client.force_authenticate(alice)
        response = api_client.post(reverse("api-v1:home-list"), {"name": "Cottage"})
        assert response.status_code == 201
        assert response.json()["role"] == "owner"
        assert response.json()["currency"] == "EUR"

    def test_list_members(
        self, api_client: APIClient, bob: User, alice_home: Home, add_member: AddMember
    ) -> None:
        add_member(alice_home, bob, Role.READ_ONLY)
        api_client.force_authenticate(bob)
        response = api_client.get(self.url(alice_home))
        assert response.status_code == 200
        roles = {m["user"]["email"]: m["role"] for m in response.json()["results"]}
        assert roles == {"alice@example.com": "owner", "bob@example.com": "read_only"}

    def test_other_home_is_404(self, api_client: APIClient, alice: User, bob_home: Home) -> None:
        api_client.force_authenticate(alice)
        owner = owner_of(bob_home)
        assert api_client.get(self.url(bob_home)).status_code == 404
        assert api_client.patch(self.url(bob_home, owner), {"role": "member"}).status_code == 404
        assert api_client.delete(self.url(bob_home, owner)).status_code == 404
        leave = reverse("api-v1:home-leave", kwargs={"home_id": bob_home.id})
        assert api_client.post(leave).status_code == 404
        assert services.role_of(owner.user, bob_home) == Role.OWNER

    def test_change_role_remove_transfer_and_leave(
        self,
        api_client: APIClient,
        alice: User,
        bob: User,
        make_user: Callable[..., User],
        alice_home: Home,
        add_member: AddMember,
    ) -> None:
        bob_membership = add_member(alice_home, bob, Role.MEMBER)
        carol = make_user()
        carol_membership = add_member(alice_home, carol, Role.MEMBER)
        api_client.force_authenticate(alice)
        response = api_client.patch(self.url(alice_home, bob_membership), {"role": "read_only"})
        assert response.status_code == 200
        assert response.json()["role"] == "read_only"
        assert (
            api_client.patch(self.url(alice_home, bob_membership), {"role": "boss"}).status_code
            == 400
        )
        assert api_client.delete(self.url(alice_home, carol_membership)).status_code == 204
        response = api_client.post(self.url(alice_home, bob_membership, "make-owner"))
        assert response.status_code == 200
        assert services.role_of(alice, alice_home) == Role.MEMBER
        leave = reverse("api-v1:home-leave", kwargs={"home_id": alice_home.id})
        assert api_client.post(leave).status_code == 204
        assert services.role_of(alice, alice_home) is None
        api_client.force_authenticate(bob)
        response = api_client.post(leave)
        assert response.status_code == 400
        assert "at least one owner" in str(response.json())

    def test_tokens_read_the_household_but_never_change_it(
        self, api_client: APIClient, alice: User, bob: User, alice_home: Home, add_member: AddMember
    ) -> None:
        bob_membership = add_member(alice_home, bob, Role.MEMBER)
        _token, raw = token_services.issue_token(
            alice, name="all", scopes=["read", "write"], homes=[alice_home]
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        assert api_client.get(self.url(alice_home)).status_code == 200
        assert (
            api_client.patch(self.url(alice_home, bob_membership), {"role": "owner"}).status_code
            == 403
        )
        assert api_client.delete(self.url(alice_home, bob_membership)).status_code == 403
        assert (
            api_client.post(self.url(alice_home, bob_membership, "make-owner")).status_code == 403
        )
        leave = reverse("api-v1:home-leave", kwargs={"home_id": alice_home.id})
        assert api_client.post(leave).status_code == 403
        assert api_client.post(reverse("api-v1:home-list"), {"name": "X"}).status_code == 403
        assert services.role_of(bob, alice_home) == Role.MEMBER
