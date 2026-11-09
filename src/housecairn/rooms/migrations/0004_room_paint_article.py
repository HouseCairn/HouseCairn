import django.db.models.deletion
from django.db import migrations, models

# The line the free text of "paint left in stock" becomes in the memory notes of the room
# (docs/adr/0046). Frozen here: a migration does not follow the code.
PREFIX = "Paint left in stock: "


def text_to_note(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Keep the old text, word for word, as a line of the memory notes: nothing is lost."""
    rooms = apps.get_model("rooms", "Room").objects
    for room in rooms.exclude(paint_stock=""):
        line = PREFIX + room.paint_stock
        notes = f"{room.memory_notes}\n{line}" if room.memory_notes else line
        rooms.filter(pk=room.pk).update(memory_notes=notes)


def note_to_text(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Going back, the last such line of the notes becomes the text again."""
    rooms = apps.get_model("rooms", "Room").objects
    for room in rooms.filter(memory_notes__contains=PREFIX):
        lines = room.memory_notes.split("\n")
        found = [i for i, line in enumerate(lines) if line.startswith(PREFIX)]
        if not found:
            continue
        taken = lines.pop(found[-1])
        rooms.filter(pk=room.pk).update(
            paint_stock=taken.removeprefix(PREFIX)[:120], memory_notes="\n".join(lines)
        )


class Migration(migrations.Migration):
    dependencies = [
        ("rooms", "0003_item_contract_provider_and_number"),
        ("stock", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="room",
            name="paint_article",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="stock.article",
                verbose_name="paint left in stock",
            ),
        ),
        migrations.RunPython(text_to_note, note_to_text),
        migrations.RemoveField(model_name="room", name="paint_stock"),
    ]
