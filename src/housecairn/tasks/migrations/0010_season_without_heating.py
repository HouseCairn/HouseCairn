from django.db import migrations, models

# Frozen here: a migration does not follow the code (docs/adr/0045, change of 2026-11-11).
# The months of the heating season in each hemisphere, for a task whose months were lost.
HEATING_WINDOWS = {"north": (10, 4), "south": (4, 10)}


def heating_to_custom(apps, schema_editor):  # type: ignore[no-untyped-def]
    """A task on the heating season becomes a custom season of the same months.

    The months of a task on a predefined season always held its window in the hemisphere
    of the home (October to April in the north, April to October in the south): they are
    kept, so nothing changes for the task. Missing months take that window.
    """
    tasks = apps.get_model("tasks", "Task").objects
    for task in tasks.filter(season="heating").select_related("home"):
        months = (task.season_start_month, task.season_end_month)
        if None in months:
            months = HEATING_WINDOWS.get(task.home.hemisphere, HEATING_WINDOWS["north"])
        tasks.filter(pk=task.pk).update(
            season="custom", season_start_month=months[0], season_end_month=months[1]
        )


def keep_custom(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Going back, the tasks stay custom: the same months, valid and read the same before.

    A custom season of October to April cannot be told from a former heating season, and
    turning every one into the heating season would change tasks that never were.
    """


class Migration(migrations.Migration):

    dependencies = [
        ("homes", "0004_home_hemisphere"),
        ("tasks", "0009_materialdraw"),
    ]

    operations = [
        migrations.RunPython(heating_to_custom, keep_custom),
        migrations.AlterField(
            model_name="task",
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
                verbose_name="season",
            ),
        ),
    ]
