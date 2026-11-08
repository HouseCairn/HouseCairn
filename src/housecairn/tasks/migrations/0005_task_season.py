from django.db import migrations, models

# The windows of the predefined seasons in the northern hemisphere, which every home has until
# its owner says otherwise (docs/adr/0045). Frozen here: a migration does not follow the code.
NORTH_WINDOWS = {
    (3, 5): "spring",
    (6, 8): "summer",
    (9, 11): "autumn",
    (12, 2): "winter",
    (10, 4): "heating",
}


def attach(apps, schema_editor):  # type: ignore[no-untyped-def]
    """A window that is a predefined season becomes it; any other becomes a custom season."""
    tasks = apps.get_model("tasks", "Task").objects
    for task in tasks.filter(season_start_month__isnull=False, season_end_month__isnull=False):
        window = (task.season_start_month, task.season_end_month)
        tasks.filter(pk=task.pk).update(season=NORTH_WINDOWS.get(window, "custom"))


def detach(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Going back, the months stay where they are: they always held the window."""


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0004_displaypreference_language"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="season",
            field=models.CharField(
                blank=True,
                choices=[
                    ("spring", "Spring"),
                    ("summer", "Summer"),
                    ("autumn", "Autumn"),
                    ("winter", "Winter"),
                    ("heating", "Heating season"),
                    ("custom", "Custom months"),
                ],
                default="",
                max_length=10,
                verbose_name="season",
            ),
        ),
        migrations.RunPython(attach, detach),
    ]
