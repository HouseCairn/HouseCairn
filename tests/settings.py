"""Test settings: the production settings, fed with test environment variables."""

import os

os.environ.setdefault("SECRET_KEY", "test-only-key-" + "x" * 40)
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("ALLOWED_HOSTS", "testserver")
os.environ.setdefault("DATABASE_URL", "sqlite://:memory:")
os.environ.setdefault("SECURE_SSL_REDIRECT", "false")
os.environ.setdefault("HOUSECAIRN_TASKS_SYNC", "true")

from housecairn.settings import *  # noqa: F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
