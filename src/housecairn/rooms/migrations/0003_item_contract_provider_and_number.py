"""The maintenance contract of an item becomes a provider and a number (docs/adr/0045).

The old free text, "who services it, and the contract number if any", goes whole into the
provider: nothing is lost, and people split it when they next open the item. Going back,
the provider and the number are joined into the one text again.
"""

from django.db import migrations, models

CONTRACT_MAX = 200


def split(apps, schema_editor):  # type: ignore[no-untyped-def]
    items = apps.get_model("rooms", "Item").objects
    items.exclude(contract="").update(contract_provider=models.F("contract"))


def join(apps, schema_editor):  # type: ignore[no-untyped-def]
    items = apps.get_model("rooms", "Item").objects
    for item in items.exclude(contract_provider="", contract_number=""):
        text = " · ".join(part for part in (item.contract_provider, item.contract_number) if part)
        items.filter(pk=item.pk).update(contract=text[:CONTRACT_MAX])


class Migration(migrations.Migration):

    dependencies = [
        ("rooms", "0002_photo_categories"),
    ]

    operations = [
        migrations.AddField(
            model_name="item",
            name="contract_provider",
            field=models.CharField(
                blank=True,
                help_text="Who services it. Example: Acme Heating.",
                max_length=200,
                verbose_name="maintenance contract: provider",
            ),
        ),
        migrations.AddField(
            model_name="item",
            name="contract_number",
            field=models.CharField(
                blank=True,
                help_text="The number to quote when you call them. Example: C-2024-0187.",
                max_length=120,
                verbose_name="maintenance contract: number",
            ),
        ),
        migrations.RunPython(split, join),
        migrations.RemoveField(
            model_name="item",
            name="contract",
        ),
    ]
