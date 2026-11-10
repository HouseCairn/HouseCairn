"""Static files storage whose addresses follow the path prefix of each request (docs/adr/0055).

Django keeps the base URL of a storage, and `settings.STATIC_URL` with its script prefix,
from the first time they are read: a prefix given per request by a proxy header would then
be the one of the first request, or none. Here the base URL is built at each call from the
script prefix of the request and `STATIC_PATH`, the relative `STATIC_URL`.
"""

from typing import Any

from django.contrib.staticfiles.storage import StaticFilesStorage
from django.urls import get_script_prefix
from whitenoise.storage import CompressedManifestStaticFilesStorage  # type: ignore[import-untyped]

from housecairn.core.prefix import STATIC_PATH


class _ScriptPrefixBaseUrl:
    # StaticFilesStorage copies STATIC_URL into its base URL when it is created: ignored here.
    _base_url: Any

    @property
    def base_url(self) -> str:
        return get_script_prefix() + STATIC_PATH


class ManifestStorage(_ScriptPrefixBaseUrl, CompressedManifestStaticFilesStorage):  # type: ignore[misc]
    """The storage of the image: hashed names, compressed copies (docs/adr/0015)."""


class PlainStorage(_ScriptPrefixBaseUrl, StaticFilesStorage):
    """Without a manifest, for tests and development."""
