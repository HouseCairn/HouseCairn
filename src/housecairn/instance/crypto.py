"""Encryption at rest of the secrets kept in the database (docs/adr/0031).

The key is derived from the instance's `SECRET_KEY`, never stored. If the key changes the
stored secrets can no longer be read: they are then treated as not set, and the
administrator enters them again. `SECRET_KEY_FALLBACKS` lets a rotation keep them.
"""

import base64
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

PREFIX = "v1:"
_INFO = b"housecairn instance settings secrets v1"


class SecretUnreadableError(Exception):
    """The stored secret was encrypted with a key the instance no longer has."""


def _derive(key: str) -> Fernet:
    raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(key.encode())
    return Fernet(base64.urlsafe_b64encode(raw))


@lru_cache(maxsize=8)
def _cipher(keys: tuple[str, ...]) -> MultiFernet:
    return MultiFernet([_derive(k) for k in keys])


def _keys() -> tuple[str, ...]:
    return (str(settings.SECRET_KEY), *(str(k) for k in settings.SECRET_KEY_FALLBACKS))


def encrypt(plain: str) -> str:
    return PREFIX + _cipher(_keys()).encrypt(plain.encode()).decode("ascii")


def decrypt(stored: str) -> str:
    if not stored.startswith(PREFIX):
        raise SecretUnreadableError
    try:
        return _cipher(_keys()).decrypt(stored[len(PREFIX) :].encode("ascii")).decode()
    except (InvalidToken, UnicodeError) as exc:
        raise SecretUnreadableError from exc
