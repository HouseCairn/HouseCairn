"""One list of photo categories (docs/adr/0045).

`open_walls` becomes `behind_walls`; `general` stays. Going back, `behind_walls` returns to
`open_walls` and the three categories that did not exist before (`before`, `after`, `other`)
return to `general`: no photo is lost, only its finer category.
"""

from django.db import migrations, models


def to_behind_walls(apps, schema_editor):  # type: ignore[no-untyped-def]
    apps.get_model("rooms", "Photo").objects.filter(category="open_walls").update(
        category="behind_walls"
    )


def to_open_walls(apps, schema_editor):  # type: ignore[no-untyped-def]
    photos = apps.get_model("rooms", "Photo").objects
    photos.filter(category="behind_walls").update(category="open_walls")
    photos.filter(category__in=["before", "after", "other"]).update(category="general")


class Migration(migrations.Migration):

    dependencies = [
        ("rooms", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="photo",
            name="category",
            field=models.CharField(
                choices=[
                    ("general", "General"),
                    ("behind_walls", "Behind the walls"),
                    ("before", "Before the work"),
                    ("after", "After the work"),
                    ("other", "Other"),
                ],
                default="general",
                max_length=16,
                verbose_name="category",
            ),
        ),
        migrations.RunPython(to_behind_walls, to_open_walls),
    ]
