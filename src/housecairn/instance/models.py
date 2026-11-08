"""Invitations to the instance itself: an account, without any home (docs/adr/0022)."""

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from housecairn.core.models import BaseModel


class InstanceInvitation(BaseModel):
    """The administrator invites an address to create an account.

    Same guarantees as an invitation to a home (docs/adr/0020): the link carries
    a random secret of which only the SHA-256 digest is stored, it works once,
    expires, can be revoked, and sending it again replaces the secret. The link
    only ever goes by email: the administrator never holds it, so nobody but
    the mailbox owner can open the account.
    """

    email = models.EmailField(_("email address"))
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    digest = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField(_("expires at"))
    sent_at = models.DateTimeField(_("sent at"))
    accepted_at = models.DateTimeField(_("accepted at"), null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    revoked_at = models.DateTimeField(_("revoked at"), null=True, blank=True)

    class Meta:
        verbose_name = _("instance invitation")
        verbose_name_plural = _("instance invitations")
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                condition=models.Q(
                    accepted_at__isnull=True, revoked_at__isnull=True, deleted_at__isnull=True
                ),
                name="unique_pending_instance_invitation",
            )
        ]

    def __str__(self) -> str:
        return str(self.email)

    @property
    def is_pending(self) -> bool:
        return (
            self.accepted_at is None
            and self.revoked_at is None
            and self.deleted_at is None
            and self.expires_at > timezone.now()
        )


class OidcProvider(BaseModel):
    """A single sign-on provider declared in the interface (docs/adr/0041).

    `slug` is the identifier django-allauth knows the provider by: it is in the redirect
    URI, in the identities linked to it and in the rule of a home that requires it. It
    never changes and is never given to another provider, even after deletion (the row
    is only marked deleted), so that no new provider inherits those links. The client
    secret is encrypted with the key of the instance settings (docs/adr/0035).
    """

    slug = models.SlugField(_("identifier"), max_length=32, unique=True)
    name = models.CharField(_("name"), max_length=64)
    issuer = models.CharField(_("issuer"), max_length=255)
    client_id = models.CharField(_("client identifier"), max_length=255)
    secret = models.TextField(_("client secret"), blank=True, default="")
    pkce = models.BooleanField(_("PKCE"), default=True)
    enabled = models.BooleanField(_("enabled"), default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )

    class Meta:
        verbose_name = _("sign-in provider")
        verbose_name_plural = _("sign-in providers")
        ordering = ("created_at",)

    def __str__(self) -> str:
        return str(self.name)


class SettingValue(models.Model):
    """A setting chosen in the interface (docs/adr/0035).

    `value` is JSON for an ordinary setting and an encrypted token for a secret. A row
    exists only while the value differs from the default: resetting deletes it.
    """

    key = models.CharField(max_length=64, unique=True)
    value = models.TextField()
    is_secret = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )

    class Meta:
        verbose_name = _("instance setting")
        verbose_name_plural = _("instance settings")

    def __str__(self) -> str:
        return str(self.key)
