from collections.abc import Callable

import pytest
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.homes import services as home_services
from housecairn.homes.models import Home, Membership, Role

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def make_user(db: None) -> Callable[..., User]:
    counter = iter(range(1000))

    def make(email: str | None = None, **extra: object) -> User:
        return User.objects.create_user(
            email=email or f"user{next(counter)}@example.com", password=PASSWORD, **extra
        )

    return make


@pytest.fixture
def alice(make_user: Callable[..., User]) -> User:
    return make_user("alice@example.com")


@pytest.fixture
def bob(make_user: Callable[..., User]) -> User:
    return make_user("bob@example.com")


@pytest.fixture
def alice_home(alice: User) -> Home:
    return home_services.create_home(alice, name="Main house")


@pytest.fixture
def bob_home(bob: User) -> Home:
    return home_services.create_home(bob, name="Flat")


@pytest.fixture
def add_member() -> Callable[[Home, User, Role], Membership]:
    def add(home: Home, user: User, role: Role) -> Membership:
        membership: Membership = Membership.objects.create(home=home, user=user, role=role)
        return membership

    return add


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()
