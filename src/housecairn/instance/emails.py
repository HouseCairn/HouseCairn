"""Instance invitation email, in plain text and HTML, in the language of the administrator."""

from collections.abc import Callable

from django.core.mail import EmailMultiAlternatives
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation
from rest_framework.request import Request

from housecairn.homes.scoping import site_url
from housecairn.instance.config import get_setting
from housecairn.instance.models import InstanceInvitation


def invitation_link(base_url: str, raw: str) -> str:
    return base_url.rstrip("/") + reverse("instance-invitation", kwargs={"token": raw})


def send_invitation(invitation: InstanceInvitation, link: str, *, language: str | None) -> None:
    with translation.override(language or get_setting("default_language")):
        context = {"link": link, "expires_at": invitation.expires_at}
        subject = " ".join(
            render_to_string("instance/email/invitation_subject.txt", context).split()
        )
        text = render_to_string("instance/email/invitation_message.txt", context)
        html = render_to_string("instance/email/invitation_message.html", context)
    message = EmailMultiAlternatives(subject, text, to=[invitation.email])
    message.attach_alternative(html, "text/html")
    message.send()


def sender_for(request: HttpRequest | Request) -> Callable[[InstanceInvitation, str], None]:
    base = site_url(request)
    language = translation.get_language()

    def send(invitation: InstanceInvitation, raw: str) -> None:
        send_invitation(invitation, invitation_link(base, raw), language=language)

    return send
