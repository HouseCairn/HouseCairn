"""Custom user model, in place from the first migration (docs/adr/0007)."""

import uuid
from typing import Any, ClassVar

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserManager(DjangoUserManager["User"]):
    """Users sign in with their email address; there is no username."""

    use_in_migrations = True

    def _create_user_object(
        self, username: str | None, email: str | None, password: str | None, **extra: Any
    ) -> "User":
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email), **extra)
        user.password = ""
        if password is not None:
            user.set_password(password)
        else:
            user.set_unusable_password()
        return user

    def _create_user(
        self, username: str | None, email: str | None, password: str | None, **extra: Any
    ) -> "User":
        user = self._create_user_object(username, email, password, **extra)
        user.save(using=self._db)
        return user

    def create_user(  # type: ignore[override]
        self, email: str | None = None, password: str | None = None, **extra: Any
    ) -> "User":
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(None, email, password, **extra)

    def create_superuser(  # type: ignore[override]
        self, email: str | None = None, password: str | None = None, **extra: Any
    ) -> "User":
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if not (extra["is_staff"] and extra["is_superuser"]):
            raise ValueError("A superuser must have is_staff and is_superuser set.")
        return self._create_user(None, email, password, **extra)


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = None  # type: ignore[assignment]
    email = models.EmailField(_("email address"), unique=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    objects: ClassVar[UserManager] = UserManager()

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def __str__(self) -> str:
        return self.email
