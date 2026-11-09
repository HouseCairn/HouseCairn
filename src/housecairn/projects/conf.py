"""The setting of the preview of links, paired with its variable (docs/adr/0035, 0050).

The limits of a preview are constants of `projects.preview`, not settings. Added to
`housecairn.instance.registry` at the end of that module; like it, this module imports no
model, since `housecairn.settings` reads it before the database exists.
"""

from django.utils.translation import gettext_lazy as _

from housecairn.instance.registry import Kind, Section, Setting

SETTINGS: tuple[Setting, ...] = (
    Setting(
        "link_preview_enabled",
        "HOUSECAIRN_LINK_PREVIEW_ENABLED",
        "HOUSECAIRN_LINK_PREVIEW_ENABLED",
        Kind.BOOL,
        Section.PROJECTS,
        _("Preview of inspiration links"),
        _(
            "When a link is added to a project, the server reads the page to find its title "
            "and its picture. Off: nothing is read, a link stays a plain address. The server "
            "never calls a private network or a cloud metadata service."
        ),
        False,
    ),
)
