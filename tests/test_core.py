import pytest
from django.test import Client
from django.urls import reverse
from django_q.models import Task

from housecairn.core import services, tasks

pytestmark = pytest.mark.django_db


class TestHealthz:
    def test_ok_without_authentication(self, client: Client) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert "no-cache" in response["Cache-Control"]

    def test_unavailable_database(self, client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(services, "database_is_available", lambda: False)
        response = client.get("/healthz")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}

    def test_database_error_means_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from django.db import DatabaseError, connection

        def broken() -> None:
            raise DatabaseError

        monkeypatch.setattr(connection, "cursor", broken)
        assert services.database_is_available() is False

    def test_only_safe_methods(self, client: Client) -> None:
        assert client.post("/healthz").status_code == 405


class TestIndex:
    def test_anonymous(self, client: Client) -> None:
        response = client.get(reverse("index"))
        assert response.status_code == 200
        assert reverse("account_login") in response.text

    def test_signed_in(self, client: Client, alice: object) -> None:
        client.force_login(alice)  # type: ignore[arg-type]
        response = client.get(reverse("index"))
        assert reverse("homes:list") in response.text
        assert reverse("account_logout") in response.text


class TestTasks:
    def test_heartbeat(self) -> None:
        result = tasks.heartbeat("probe")
        assert result["label"] == "probe"
        assert "T" in result["ran_at"]

    def test_queue_runs_the_task(self) -> None:
        task_id = services.enqueue_heartbeat("queued")
        task = Task.objects.get(id=task_id)
        assert task.success
        assert task.func == "housecairn.core.tasks.heartbeat"
        assert task.result["label"] == "queued"
