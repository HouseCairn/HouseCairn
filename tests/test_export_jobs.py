"""The archive of a large home is made by the worker and handed a few times (docs/adr/0048)."""

import datetime
import io
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.audit.models import AuditEvent
from housecairn.homes import quotas, restore, services
from housecairn.homes.models import ExportJob, ExportStatus, Home, Role
from housecairn.rooms import services as room_services
from tests.data_support import export_data
from tests.rooms_support import image_bytes, upload

pytest_plugins = ("tests.rooms_fixtures",)
pytestmark = pytest.mark.django_db


@pytest.fixture
def large(settings: Any, media_root: Path, alice: User, alice_home: Home) -> Home:
    """Any file makes the home "large": the threshold is lowered to one byte."""
    settings.HOUSECAIRN_EXPORT_INLINE_MAX_BYTES = 1
    room = room_services.create_room(alice, alice_home, name="Kitchen")
    room_services.add_photo(alice, upload=upload(image_bytes()), room=room)
    return alice_home


def start(client: Client, home: Home) -> ExportJob:
    response = client.post(reverse("homes:export", kwargs={"home_id": home.id}))
    assert response.status_code == 302
    job = ExportJob.objects.get(home=home)
    assert response["Location"] == reverse(
        "homes:export-job", kwargs={"home_id": home.id, "job_id": job.id}
    )
    return job


def download(client: Client, job: ExportJob) -> Any:
    return client.post(
        reverse("homes:export-download", kwargs={"home_id": job.home_id, "job_id": job.id})
    )


def test_a_large_home_is_exported_in_the_background_then_downloaded(
    client: Client, alice: User, large: Home
) -> None:
    client.force_login(alice)
    job = start(client, large)  # the worker runs at once in the tests (HOUSECAIRN_TASKS_SYNC)
    job.refresh_from_db()
    assert job.status == ExportStatus.READY
    page = client.get(reverse("homes:export-job", kwargs={"home_id": large.id, "job_id": job.id}))
    assert page.status_code == 200
    assert (
        reverse("homes:export-download", kwargs={"home_id": large.id, "job_id": job.id})
        in page.content.decode()
    )
    response = download(client, job)
    assert response.status_code == 200
    data = export_data(zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))))
    assert data["home"]["id"] == str(large.id)
    assert len(data["photos"]) == 1
    assert AuditEvent.objects.filter(action="home.exported", home_id=large.id).count() == 1


def test_the_archive_restores(client: Client, alice: User, large: Home) -> None:
    client.force_login(alice)
    archive = b"".join(download(client, start(client, large)).streaming_content)
    services.erase_home(large)
    assert restore.restore_bytes(alice, archive).home.id == large.id


def test_the_downloads_are_limited(client: Client, alice: User, large: Home, settings: Any) -> None:
    client.force_login(alice)
    job = start(client, large)
    for _ in range(settings.HOUSECAIRN_EXPORT_DOWNLOADS):
        assert download(client, job).status_code == 200
    assert download(client, job).status_code == 404
    # Used up, the archive and its row go at the next export or download.
    download(client, job)
    assert not ExportJob.all_objects.filter(pk=job.pk).exists()
    assert not list((Path(settings.MEDIA_ROOT) / "exports" / str(large.id)).glob("*.zip"))


def test_an_expired_archive_is_not_handed_and_is_removed(
    client: Client, alice: User, large: Home, settings: Any
) -> None:
    client.force_login(alice)
    job = start(client, large)
    ExportJob.objects.filter(pk=job.pk).update(
        expires_at=timezone.now() - datetime.timedelta(seconds=1)
    )
    assert download(client, job).status_code == 404
    assert not (Path(settings.MEDIA_ROOT) / "exports" / str(large.id) / f"{job.id}.zip").exists()


def test_the_archive_does_not_count_in_the_quota_and_goes_with_the_home(
    client: Client, alice: User, large: Home, settings: Any
) -> None:
    before = quotas.usage(large.id)
    client.force_login(alice)
    job = start(client, large)
    assert quotas.usage(large.id) == before
    folder = Path(settings.MEDIA_ROOT) / "exports" / str(large.id)
    assert (folder / f"{job.id}.zip").exists()
    from django.test import TestCase

    with TestCase.captureOnCommitCallbacks(execute=True):
        services.delete_home(alice, large, confirmation="Main house")
    assert not folder.exists()


def test_only_an_owner_of_the_home_sees_or_downloads_it(
    client: Client,
    alice: User,
    large: Home,
    make_user: Callable[..., User],
    add_member: Callable[..., Any],
    bob: User,
) -> None:
    client.force_login(alice)
    job = start(client, large)
    member = make_user("member@example.com")
    add_member(large, member, Role.MEMBER)
    client.force_login(member)
    page = reverse("homes:export-job", kwargs={"home_id": large.id, "job_id": job.id})
    assert client.get(page).status_code == 403
    assert download(client, job).status_code == 403
    client.force_login(bob)
    assert client.get(page).status_code == 404
    assert download(client, job).status_code == 404
    job.refresh_from_db()
    assert job.downloads_left == 3


def test_the_link_is_a_post_and_works_under_a_path_prefix(
    client: Client, alice: User, large: Home
) -> None:
    client.force_login(alice)
    job = start(client, large)
    url = reverse("homes:export-download", kwargs={"home_id": large.id, "job_id": job.id})
    assert client.get(url).status_code == 405
    assert url.endswith(f"/h/{large.id}/export/{job.id}/download/") or url.endswith(
        f"/{large.id}/export/{job.id}/download/"
    )


def test_the_api_answers_202_with_the_job_then_hands_the_archive(
    client: Client, api_client: APIClient, alice: User, large: Home
) -> None:
    client.force_login(alice)
    response = client.post(reverse("api-v1:home-export", kwargs={"home_id": large.id}))
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "ready"
    assert body["downloads_left"] == 3
    detail = client.get(
        reverse("api-v1:home-export-job", kwargs={"home_id": large.id, "job_id": body["id"]})
    )
    assert detail.status_code == 200
    archive = client.post(body["download"])
    assert archive.status_code == 200
    assert archive["Content-Type"] == "application/zip"
    _token, raw = token_services.issue_token(
        alice, name="all", scopes=["read", "write"], homes=[large]
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert (
        api_client.get(
            reverse("api-v1:home-export-job", kwargs={"home_id": large.id, "job_id": body["id"]})
        ).status_code
        == 403
    )
    assert api_client.post(body["download"]).status_code == 403


@pytest.mark.django_db(transaction=True)
def test_the_migration_of_the_export_jobs_is_reversible() -> None:
    from django.core.management import call_command
    from django.db import connection

    call_command("migrate", "homes", "0004", verbosity=0)
    assert "homes_exportjob" not in connection.introspection.table_names()
    # Back up with every app: going back in `homes` may undo the apps that depend on it.
    call_command("migrate", verbosity=0)
    assert "homes_exportjob" in connection.introspection.table_names()
