from django.db import migrations


def zero_to_unset(apps, schema_editor):
    """A duration of 0 was accepted before the bound of a minute: it means "not estimated"."""
    apps.get_model("tasks", "Task").objects.filter(estimated_minutes=0).update(
        estimated_minutes=None
    )


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0006_contractor_record"),
    ]

    operations = [
        # Undone, nothing comes back: a 0 said nothing, and those rows stay unset.
        migrations.RunPython(zero_to_unset, migrations.RunPython.noop),
    ]
