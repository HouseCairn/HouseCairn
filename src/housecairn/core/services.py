"""Core services: views and API call them, never the other way round."""

from django.db import DatabaseError, connection
from django_q.tasks import async_task


def database_is_available() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            return bool(cursor.fetchone() == (1,))
    except DatabaseError:
        return False


def enqueue_heartbeat(label: str) -> str:
    """Queue the demonstration task and return its task identifier."""
    task_id: str = async_task("housecairn.core.tasks.heartbeat", label)
    return task_id
