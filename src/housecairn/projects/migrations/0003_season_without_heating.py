from django.db import migrations, models

# Frozen here: a migration does not follow the code (docs/adr/0045, change of 2026-11-11).
HEATING_WINDOWS = {"north": (10, 4), "south": (4, 10)}


def heating_to_custom(apps, schema_editor):  # type: ignore[no-untyped-def]
    """A project wished for the heating season becomes a custom season of the same months.

    A predefined season of a project keeps no months (they are worked out from the
    hemisphere of the home when read): the custom season takes those months, October to
    April in the north, April to October in the south, so the project reads the same.
    """
    projects = apps.get_model("projects", "Project").objects
    for project in projects.filter(season="heating").select_related("home"):
        start, end = HEATING_WINDOWS.get(project.home.hemisphere, HEATING_WINDOWS["north"])
        projects.filter(pk=project.pk).update(
            season="custom", season_start_month=start, season_end_month=end
        )


def keep_custom(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Going back, the projects stay custom: the same months, valid and read the same before."""


class Migration(migrations.Migration):

    dependencies = [
        ("homes", "0004_home_hemisphere"),
        ("projects", "0002_links"),
    ]

    operations = [
        migrations.RunPython(heating_to_custom, keep_custom),
        migrations.AlterField(
            model_name="project",
            name="season",
            field=models.CharField(
                blank=True,
                choices=[
                    ("spring", "Spring"),
                    ("summer", "Summer"),
                    ("autumn", "Autumn"),
                    ("winter", "Winter"),
                    ("custom", "Custom months"),
                ],
                default="",
                max_length=10,
                verbose_name="preferred season",
            ),
        ),
    ]
