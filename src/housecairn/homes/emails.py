"""Invitation email, in plain text and HTML, in the language of the person who invites."""

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation

from housecairn.homes.models import Invitation
from housecairn.instance.config import get_setting


def invitation_link(base_url: str, raw: str) -> str:
    """Absolute address of the invitation page.

    `base_url` is `HOUSECAIRN_SITE_URL` when set, else the scheme and host of
    the request, which Django has checked against `ALLOWED_HOSTS`.
    """
    return base_url.rstrip("/") + reverse("invitation", kwargs={"token": raw})


def send_invitation(invitation: Invitation, link: str, *, language: str | None) -> None:
    with translation.override(language or get_setting("default_language")):
        context = {
            "home_name": invitation.home.name,
            "role": invitation.get_role_display(),
            "link": link,
            "expires_at": invitation.expires_at,
        }
        # A subject is one line: a home name with a line break must not add a
        # header to the message.
        subject = " ".join(render_to_string("homes/email/invitation_subject.txt", context).split())
        text = render_to_string("homes/email/invitation_message.txt", context)
        html = render_to_string("homes/email/invitation_message.html", context)
    message = EmailMultiAlternatives(subject, text, to=[invitation.email])
    message.attach_alternative(html, "text/html")
    message.send()
