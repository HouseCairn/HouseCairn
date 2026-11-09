"""QR labels: an opaque code on a sticker that opens a room, an item or a stock item.

The code is the only thing the sticker carries (docs/adr/0047). It is random, 128 bits
long, and names nothing: not the object, not the home, not a person. Revoking a label
keeps its row, so that a printed code never comes back to life nor to another object.
"""

import secrets
from typing import Any

from django.db import models
from django.utils.translation import gettext_lazy as _

from housecairn.homes.models import HomeOwnedModel
from housecairn.rooms.models import Item, Room
from housecairn.stock.models import Article

# 16 random bytes: 128 bits, 22 URL-safe characters.
CODE_BYTES = 16
CODE_LENGTH = 22
CODE_ALPHABET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def new_code() -> str:
    return secrets.token_urlsafe(CODE_BYTES)


def is_code_shaped(value: str) -> bool:
    """True for a string that could be a code; anything else cannot match a label."""
    return len(value) == CODE_LENGTH and set(value) <= CODE_ALPHABET


class LabelKind(models.TextChoices):
    ROOM = "room", _("Room")
    ITEM = "item", _("Item")
    ARTICLE = "article", _("Stock item")


class Label(HomeOwnedModel):
    """The QR label of one object of the home. At most one is active per object."""

    code = models.CharField(max_length=32, unique=True, editable=False, default=new_code)
    kind = models.CharField(_("type"), max_length=16, choices=LabelKind.choices)
    room = models.ForeignKey(
        Room, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    item = models.ForeignKey(
        Item, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    article = models.ForeignKey(
        Article, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    revoked_at = models.DateTimeField(_("revoked at"), null=True, blank=True)

    class Meta:
        verbose_name = _("QR label")
        verbose_name_plural = _("QR labels")
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        kind="room", room__isnull=False, item__isnull=True, article__isnull=True
                    )
                    | models.Q(
                        kind="item", room__isnull=True, item__isnull=False, article__isnull=True
                    )
                    | models.Q(
                        kind="article", room__isnull=True, item__isnull=True, article__isnull=False
                    )
                ),
                name="label_one_target_of_its_kind",
            ),
            *(
                models.UniqueConstraint(
                    fields=[target],
                    condition=models.Q(revoked_at__isnull=True, deleted_at__isnull=True),
                    name=f"label_one_active_per_{target}",
                )
                for target in ("room", "item", "article")
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} label"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.deleted_at is None

    @property
    def target(self) -> Any:
        return {"room": self.room, "item": self.item, "article": self.article}[self.kind]

    @property
    def target_id(self) -> Any:
        return {"room": self.room_id, "item": self.item_id, "article": self.article_id}[self.kind]

    @property
    def target_alive(self) -> bool:
        target = self.target
        return target is not None and target.deleted_at is None

    @property
    def name(self) -> str:
        """What is printed in bold: the name of the object."""
        return str(self.target.name)

    @property
    def place(self) -> str:
        """Where it is, printed under the name: the room of an item, the storage place of a
        stock item, nothing for a room."""
        if self.kind == LabelKind.ITEM and self.item is not None:
            return str(self.item.room.name)
        if self.kind == LabelKind.ARTICLE and self.article is not None:
            return str(self.article.storage_location)
        return ""
