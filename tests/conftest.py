import os
from collections.abc import Callable, Iterator

import pytest
from hypothesis import settings as hypothesis_settings
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.homes import services as home_services
from housecairn.homes.models import Home, Membership, Role

PASSWORD = "correct-horse-battery-staple"

# Property-based tests (docs/adr/0019). CI sets HYPOTHESIS_PROFILE=ci: a fixed
# number of examples, the same ones on every run, no example database. The
# default `dev` profile tries more examples and keeps failing ones in
# `.hypothesis/` (ignored by Git) to replay them first.
hypothesis_settings.register_profile(
    "ci", max_examples=50, derandomize=True, database=None, deadline=None, print_blob=True
)
hypothesis_settings.register_profile("dev", max_examples=300, deadline=None)
hypothesis_settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


def pytest_report_header() -> str:
    profile = hypothesis_settings.get_current_profile_name()
    return f"hypothesis profile: {profile} ({hypothesis_settings.default.max_examples} examples)"


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


@pytest.fixture(autouse=True)
def _fresh_instance_settings() -> Iterator[None]:
    """The settings snapshot of one test must not leak into the next (docs/adr/0031)."""
    from housecairn.instance import config

    config.reset()
    yield
    config.reset()
