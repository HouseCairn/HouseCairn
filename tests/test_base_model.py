import uuid

import pytest

from housecairn.homes.models import Home

pytestmark = pytest.mark.django_db


def test_uuid_and_timestamps() -> None:
    home = Home.objects.create(name="A")
    assert isinstance(home.id, uuid.UUID)
    assert home.created_at is not None
    assert home.updated_at >= home.created_at
    assert not home.is_deleted


def test_soft_delete_hides_from_default_manager() -> None:
    home = Home.objects.create(name="A")
    home.soft_delete()
    assert home.is_deleted
    assert not Home.objects.filter(id=home.id).exists()
    assert Home.all_objects.filter(id=home.id).exists()
    home.restore()
    assert Home.objects.filter(id=home.id).exists()


def test_queryset_soft_delete() -> None:
    Home.objects.create(name="A")
    Home.objects.create(name="B")
    assert Home.objects.all().soft_delete() == 2
    assert Home.objects.count() == 0
    assert Home.all_objects.count() == 2
