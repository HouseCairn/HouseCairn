"""Print the table of the instance settings, as the documentation shows it (docs/adr/0031).

`docs/administration/settings.md` holds this table between two markers; a test fails when
it differs, so that a setting added without a documentation entry cannot be merged.
"""

from typing import Any

from django.core.management.base import BaseCommand
from django.utils import translation

from housecairn.instance import registry

START = "% settings-table:start"
END = "% settings-table:end"


def default_text(setting: registry.Setting) -> str:
    default = setting.default
    if setting.secret:
        return "(none)"
    if isinstance(default, bool):
        return "`true`" if default else "`false`"
    if isinstance(default, list):
        return "(none)"
    return f"`{default}`" if default != "" else "(none)"


def table() -> str:
    with translation.override("en"):
        rows = [
            "| Setting | Variable | Section | Default | Takes effect |",
            "| --- | --- | --- | --- | --- |",
        ]
        for setting in registry.SETTINGS.values():
            effect = "At once" if setting.reload is registry.Reload.LIVE else "After a restart"
            rows.append(
                f"| {setting.label} | `{setting.env}` | {registry.SECTION_LABELS[setting.section]} "
                f"| {default_text(setting)} | {effect} |"
            )
    return "\n".join(rows)


class Command(BaseCommand):
    help = "Print the Markdown table of the instance settings."

    def handle(self, *args: Any, **options: Any) -> None:
        self.stdout.write(table())
