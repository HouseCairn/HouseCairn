"""Outgoing email with the settings in force at the time of sending (docs/adr/0035).

Django reads `EMAIL_*` once at start-up; this backend asks `get_setting` for each
connection instead, so that a change made in the interface applies without a restart.
With no server set it prints messages to the console, as before.
"""

import logging
import smtplib
import ssl
from collections.abc import Sequence
from typing import Any

from django.core.mail import EmailMessage
from django.core.mail.backends.console import EmailBackend as ConsoleBackend
from django.core.mail.backends.smtp import EmailBackend as SmtpBackend

from housecairn.instance.config import get_setting

logger = logging.getLogger("housecairn.mail")


class EmailBackend(SmtpBackend):
    def __init__(self, **kwargs: Any) -> None:
        ssl_on = bool(get_setting("email_use_ssl"))
        defaults: dict[str, Any] = {
            "host": get_setting("email_host"),
            "port": get_setting("email_port"),
            "username": get_setting("email_host_user"),
            "password": get_setting("email_host_password"),
            "use_tls": bool(get_setting("email_use_tls")) and not ssl_on,
            "use_ssl": ssl_on,
            "timeout": get_setting("email_timeout"),
        }
        super().__init__(**{**defaults, **kwargs})
        self._console = ConsoleBackend(**kwargs)

    def send_messages(self, email_messages: Sequence[EmailMessage]) -> int:
        sender = str(get_setting("default_from_email"))
        for message in email_messages:
            if message.from_email == _static_sender():
                message.from_email = sender
        if not self.host:
            return self._console.send_messages(email_messages)
        return super().send_messages(email_messages)


def _static_sender() -> str:
    from django.conf import settings

    return str(settings.DEFAULT_FROM_EMAIL)


def check_connection() -> str:
    """Open a connection with the settings in force and close it; nothing is sent.

    Returns a code: `ok`, `no_server`, `auth`, `tls` or `unreachable`. It says what failed
    in a word, never what the server replied.
    """
    if not get_setting("email_host"):
        return "no_server"
    backend = EmailBackend(fail_silently=False)
    try:
        backend.open()
    except smtplib.SMTPAuthenticationError:
        return "auth"
    except (ssl.SSLError, smtplib.SMTPNotSupportedError):
        return "tls"
    except (smtplib.SMTPException, OSError) as exc:
        logger.info("SMTP check failed: %s", type(exc).__name__)
        return "unreachable"
    finally:
        backend.close()
    return "ok"
