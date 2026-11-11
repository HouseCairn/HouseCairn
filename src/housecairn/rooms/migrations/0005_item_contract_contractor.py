import django.db.models.deletion
from django.db import migrations, models

# What a contractor made from a provider typed as text is (docs/adr/0058). Frozen here: a
# migration does not follow the code. The trade is "other", said as "Maintenance", which
# reads the same in English and in French; it can be changed on the contractor's sheet.
NEW_TRADE = "other"
NEW_TRADE_OTHER = "Maintenance"
NAME_MAX = 120


def _plain(text):  # type: ignore[no-untyped-def]
    """The text without the case and the extra spaces: what makes two names the same."""
    return " ".join(text.split()).casefold()


def text_to_contractor(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Each provider typed as text becomes the contractor of the home of that name.

    The contractor of the home whose name is the same (case and spaces ignored) is linked;
    if the home has none, one is made, with the trade Other, and shared by the items that
    name the same provider. A text longer than a name goes whole into the note.
    """
    items = apps.get_model("rooms", "Item").objects
    contractors = apps.get_model("tasks", "Contractor").objects
    known: dict[tuple[object, str], object] = {}
    for contractor in contractors.filter(deleted_at__isnull=True).order_by("created_at", "id"):
        known.setdefault((contractor.home_id, _plain(contractor.name)), contractor)
    for item in items.exclude(contract_provider="").order_by("created_at", "id"):
        text = " ".join(item.contract_provider.split())
        if not text:
            continue
        key = (item.home_id, _plain(text))
        contractor = known.get(key)
        if contractor is None:
            contractor = contractors.create(
                home_id=item.home_id,
                name=text[:NAME_MAX],
                trade=NEW_TRADE,
                trade_other=NEW_TRADE_OTHER,
                note=text if len(text) > NAME_MAX else "",
            )
            known[key] = contractor
        items.filter(pk=item.pk).update(contract_contractor=contractor)


def contractor_to_text(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Going back, the provider is the name of the contractor; the contractors stay."""
    items = apps.get_model("rooms", "Item").objects
    for item in items.exclude(contract_contractor=None).select_related("contract_contractor"):
        items.filter(pk=item.pk).update(contract_provider=item.contract_contractor.name[:200])


class Migration(migrations.Migration):
    dependencies = [
        ("rooms", "0004_room_paint_article"),
        ("tasks", "0011_estimate_up_to_a_year"),
    ]

    operations = [
        migrations.AddField(
            model_name="item",
            name="contract_contractor",
            field=models.ForeignKey(
                blank=True,
                help_text="Who services it, from the contractors of the home. Example: Acme Heating.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="maintained_items",
                to="tasks.contractor",
                verbose_name="maintenance contract: provider",
            ),
        ),
        migrations.RunPython(text_to_contractor, contractor_to_text),
        migrations.RemoveField(model_name="item", name="contract_provider"),
    ]
