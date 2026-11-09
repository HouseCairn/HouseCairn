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
    """The settings snapshot of one test must not leak into the next (docs/adr/0035)."""
    from housecairn.instance import config

    config.reset()
    yield
    config.reset()


@pytest.fixture(autouse=True)
def _schema_stays_complete(request: pytest.FixtureRequest) -> Iterator[None]:
    """A test that migrates backwards must leave every app on its latest migration.

    Tests with a real transaction (`django_db(transaction=True)`) may roll an app
    back and forward again. `migrate <app> <target>` only touches that app and the
    apps that depend on it, so a forward `migrate <app>` can leave another app
    unapplied, and its tables are then missing for every later test of the same
    worker (xdist reuses the database). The check fails the offending test and
    repairs the schema so the damage stays contained.
    """
    yield
    marker = request.node.get_closest_marker("django_db")
    transactional = bool(marker and marker.kwargs.get("transaction")) or (
        "transactional_db" in request.fixturenames
    )
    if not transactional:
        return
    from django.core.management import call_command
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    if pending:
        names = ", ".join(f"{m.app_label}.{m.name}" for m, _ in pending)
        call_command("migrate", verbosity=0)
        pytest.fail(
            "this test left migrations unapplied (end it with `call_command('migrate')`, "
            f"not `migrate <app>`): {names}",
            pytrace=False,
        )
