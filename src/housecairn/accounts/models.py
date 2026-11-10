"""Custom user model, in place from the first migration (docs/adr/0007)."""

import uuid
from typing import Any, ClassVar

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

from housecairn.accounts.names import DISPLAY_NAME_MAX_LENGTH


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


class DisplayNameSource(models.TextChoices):
    """Who sets the display name (docs/adr/0045)."""

    OIDC = "oidc", _("sign-in provider")
    MANUAL = "manual", _("typed by the person")


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = None  # type: ignore[assignment]
    email = models.EmailField(_("email address"), unique=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)
    # How the person is named to the others (docs/adr/0045); see accounts.names.person_name.
    display_name = models.CharField(
        _("display name"),
        max_length=DISPLAY_NAME_MAX_LENGTH,
        blank=True,
        help_text=_("How the other members of your homes see you. Optional."),
    )
    # Where the display name comes from: the sign-in provider rewrites it at each sign-in
    # through it while this is `oidc`; a name typed by the person is `manual` and stays.
    display_name_source = models.CharField(
        _("source of the display name"),
        max_length=8,
        choices=DisplayNameSource.choices,
        default=DisplayNameSource.OIDC,
    )
    # The identifier of the provider the current display name was taken from; empty when
    # the person typed it or no provider ever gave one. Never a claim of the provider.
    display_name_provider = models.CharField(
        _("provider of the display name"), max_length=32, blank=True, editable=False
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    objects: ClassVar[UserManager] = UserManager()

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def __str__(self) -> str:
        return self.email


class SetupMethod(models.TextChoices):
    OIDC = "oidc", _("first sign-in through OIDC")
    OTHER = "other", _("created another way")
    SETUP_SCREEN = "setup_screen", _("first-account screen")


class InstanceSetup(models.Model):
    """Marks that the instance has had a first account (docs/adr/0007).

    One row at most, created with the first user and never removed: once it
    exists, no sign-in can make someone an administrator by being first. The
    fixed primary key also settles two simultaneous first sign-ins, since only
    one of them can insert the row. It is the audit record of how the first
    account was created.
    """

    SINGLETON_ID = 1

    id = models.PositiveSmallIntegerField(primary_key=True, default=SINGLETON_ID, editable=False)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    method = models.CharField(_("method"), max_length=16, choices=SetupMethod.choices)
    first_user = models.OneToOneField(
        User,
        verbose_name=_("first account"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = _("instance setup")
        verbose_name_plural = _("instance setup")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(id=1), name="accounts_instancesetup_single_row"
            )
        ]

    def __str__(self) -> str:
        return str(self.get_method_display())


class KnownDevice(models.Model):
    """A browser the account has signed in from (docs/adr/0023).

    The browser holds a random secret in a cookie; only its SHA-256 digest is
    kept here. A sign-in from a browser without a known secret raises a
    security alert by email, once the account has at least one known device.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="known_devices")
    digest = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("known device")
        verbose_name_plural = _("known devices")

    def __str__(self) -> str:
        return f"{self.user} ({self.created_at:%Y-%m-%d})"


class SetupCode(models.Model):
    """The one-time code that opens the first-account screen (docs/adr/0056).

    The code itself is written in the process log at start-up and never stored: only
    its SHA-256 digest is. A code that is used is kept (with the time) so that it cannot
    be played again; the unused ones are replaced by each new code.
    """

    digest = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("setup code")
        verbose_name_plural = _("setup codes")

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M}"
