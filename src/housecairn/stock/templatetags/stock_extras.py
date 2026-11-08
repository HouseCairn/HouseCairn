"""Stock on the pages of other apps: the room page shows the articles that concern it."""

from typing import Any

from django import template

from housecairn.rooms.models import Room
from housecairn.stock import services
from housecairn.stock.models import Article

register = template.Library()


@register.simple_tag
def room_articles(room: Room) -> list[dict[str, Any]]:
    """The articles that concern the room, each with its quantity and whether it is low."""
    return [
        {"article": a, "low": services.is_low(a, a.quantity)}  # type: ignore[attr-defined]
        for a in services.articles_of_room(room.home, room.pk)
    ]


@register.simple_tag
def paint_article_of(room: Room) -> Article | None:
    """The tin of paint left over, with its quantity; none if there is none or it was deleted."""
    if room.paint_article_id is None:
        return None
    return services.articles_of(room.home).filter(pk=room.paint_article_id).first()
