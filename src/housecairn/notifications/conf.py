"""The settings of notifications, paired with their variables (docs/adr/0035, 0043).

Added to `housecairn.instance.registry` at the end of that module; like it, this module
imports no model, since `housecairn.settings` reads it before the database exists.
"""

from django.utils.translation import gettext_lazy as _

from housecairn.instance.registry import Kind, Section, Setting

SETTINGS: tuple[Setting, ...] = (
    Setting(
        "notifications_enabled",
        "HOUSECAIRN_NOTIFICATIONS_ENABLED",
        "HOUSECAIRN_NOTIFICATIONS_ENABLED",
        Kind.BOOL,
        Section.NOTIFICATIONS,
        _("Notifications"),
        _(
            "People may add channels (ntfy, Telegram, email...) and receive reminders. "
            "Off: nothing is sent and no channel can be added or tested."
        ),
        False,
    ),
    Setting(
        "notifications_interval",
        "HOUSECAIRN_NOTIFICATIONS_INTERVAL",
        "HOUSECAIRN_NOTIFICATIONS_INTERVAL",
        Kind.INT,
        Section.NOTIFICATIONS,
        _("Check for reminders every (minutes)"),
        _("How often the background worker looks for reminders to send, from 1 to 60."),
        5,
        minimum=1,
        maximum=60,
    ),
    Setting(
        "notifications_private_networks",
        "HOUSECAIRN_NOTIFICATIONS_PRIVATE_NETWORKS",
        "HOUSECAIRN_NOTIFICATIONS_PRIVATE_NETWORKS",
        Kind.BOOL,
        Section.NOTIFICATIONS,
        _("Channels on the local network"),
        _(
            "Channels may send to private network addresses (a home or office network, or "
            "a name that resolves to one), for a ntfy or a Gotify next to the instance. Any "
            "person with an account can then make the server call such an address. "
            "Loopback, link-local and cloud metadata addresses stay refused."
        ),
        False,
    ),
    Setting(
        "webpush_enabled",
        "HOUSECAIRN_WEBPUSH_ENABLED",
        "HOUSECAIRN_WEBPUSH_ENABLED",
        Kind.BOOL,
        Section.NOTIFICATIONS,
        _("Notifications on the device"),
        _(
            "People may receive their notifications on a phone or a computer, through the "
            "push service of their browser: Google for Chrome, Edge and most others, "
            "Mozilla for Firefox, Apple for Safari. The message is encrypted for the "
            "device; the push service sees when it is sent, its size and the device."
        ),
        False,
    ),
    Setting(
        "webpush_discreet",
        "HOUSECAIRN_WEBPUSH_DISCREET",
        "HOUSECAIRN_WEBPUSH_DISCREET",
        Kind.BOOL,
        Section.NOTIFICATIONS,
        _("Discreet notifications on the device"),
        _(
            "A notification on the device says only that a task is due or a problem was "
            "reported, with a link: no title of a task, no name of a home, on a locked "
            "screen either."
        ),
        True,
    ),
)
