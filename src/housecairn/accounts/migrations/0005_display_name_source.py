"""Where the display name comes from (docs/adr/0045).

Every account starts as `oidc`: an account linked to a sign-in provider that has no display
name takes one at its next sign-in through it, and an account that is not linked never gets
one from a provider. A name already typed is the person's own: it becomes `manual`, which no
sign-in overwrites. Going back drops both fields; the names themselves never move.
"""

from typing import Any

from django.db import migrations, models


def mark_typed_names(apps: Any, schema_editor: Any) -> None:
    User = apps.get_model("accounts", "User")
    User.objects.exclude(display_name="").update(display_name_source="manual")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_user_display_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="display_name_source",
            field=models.CharField(
                choices=[("oidc", "sign-in provider"), ("manual", "typed by the person")],
                default="oidc",
                max_length=8,
                verbose_name="source of the display name",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="display_name_provider",
            field=models.CharField(
                blank=True,
                editable=False,
                max_length=32,
                verbose_name="provider of the display name",
            ),
        ),
        migrations.RunPython(mark_typed_names, migrations.RunPython.noop, elidable=False),
    ]
