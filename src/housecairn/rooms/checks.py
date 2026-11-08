"""System check: an unusable photo size limit stops `manage.py check` and the start-up."""

from typing import Any

from django.core import checks
from django.core.exceptions import ImproperlyConfigured

from housecairn.rooms import conf


@checks.register()
def photo_limit(app_configs: Any, **kwargs: Any) -> list[checks.CheckMessage]:
    try:
        conf.photo_max_bytes()
    except ImproperlyConfigured as exc:
        return [checks.Error(str(exc), id="housecairn.rooms.E001")]
    return []
