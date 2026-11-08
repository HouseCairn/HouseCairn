import unicodedata

import django.core.validators
from django.db import migrations, models

# What people wrote as a trade, in English or French, and the code of the list it becomes
# (docs/adr/0045). Frozen here: a migration does not follow the code.
TRADES = {
    "plumber": ("plumber", "plombier", "plomberie"),
    "electrician": ("electrician", "electricien", "electricite"),
    "heating_engineer": ("heating engineer", "heating", "chauffagiste", "chauffage"),
    "roofer": ("roofer", "couvreur", "toiture"),
    "carpenter": ("carpenter", "joiner", "menuisier", "charpentier"),
    "painter": ("painter", "peintre"),
    "mason": ("mason", "macon"),
    "gardener": ("gardener", "jardinier"),
    "locksmith": ("locksmith", "serrurier"),
    "chimney_sweep": ("chimney sweep", "ramoneur"),
}
LABELS = {
    "plumber": "Plumber",
    "electrician": "Electrician",
    "heating_engineer": "Heating engineer",
    "roofer": "Roofer",
    "carpenter": "Carpenter",
    "painter": "Painter",
    "mason": "Mason",
    "gardener": "Gardener",
    "locksmith": "Locksmith",
    "chimney_sweep": "Chimney sweep",
}


def _plain(text):  # type: ignore[no-untyped-def]
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    kept = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(kept.split())


WORDS = {_plain(word): code for code, words in TRADES.items() for word in words}


def to_list(apps, schema_editor):  # type: ignore[no-untyped-def]
    """A text that is a trade of the list becomes its code; any other becomes Other, kept."""
    contractors = apps.get_model("tasks", "Contractor").objects
    for contractor in contractors.exclude(trade=""):
        code = WORDS.get(_plain(contractor.trade))
        if code:
            contractors.filter(pk=contractor.pk).update(trade=code, trade_other="")
        else:
            contractors.filter(pk=contractor.pk).update(
                trade="other", trade_other=contractor.trade[:120]
            )


def to_text(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Going back, the trade is the label of the list, or the text kept with Other."""
    contractors = apps.get_model("tasks", "Contractor").objects
    for contractor in contractors.exclude(trade=""):
        text = contractor.trade_other if contractor.trade == "other" else LABELS.get(contractor.trade)
        contractors.filter(pk=contractor.pk).update(trade=(text or contractor.trade)[:120])


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0005_task_season"),
    ]

    operations = [
        migrations.AddField(
            model_name='contractor',
            name='address',
            field=models.TextField(blank=True, validators=[django.core.validators.MaxLengthValidator(400)], verbose_name='address'),
        ),
        migrations.AddField(
            model_name='contractor',
            name='email',
            field=models.EmailField(blank=True, max_length=254, verbose_name='email address'),
        ),
        migrations.AddField(
            model_name='contractor',
            name='phone',
            field=models.CharField(blank=True, max_length=40, validators=[django.core.validators.RegexValidator('^[0-9+()./ -]{3,40}$', 'Digits, spaces and + ( ) - . / only.')], verbose_name='phone'),
        ),
        migrations.AddField(
            model_name='contractor',
            name='trade_other',
            field=models.CharField(blank=True, help_text='Only with the trade Other. Example: Pool maintenance.', max_length=120, verbose_name='which trade'),
        ),
        migrations.RunPython(to_list, to_text),
        migrations.AlterField(
            model_name='contractor',
            name='trade',
            field=models.CharField(blank=True, choices=[('plumber', 'Plumber'), ('electrician', 'Electrician'), ('heating_engineer', 'Heating engineer'), ('roofer', 'Roofer'), ('carpenter', 'Carpenter'), ('painter', 'Painter'), ('mason', 'Mason'), ('gardener', 'Gardener'), ('locksmith', 'Locksmith'), ('chimney_sweep', 'Chimney sweep'), ('other', 'Other')], max_length=20, verbose_name='trade'),
        ),
    ]
