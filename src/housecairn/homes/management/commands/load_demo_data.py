"""Fill a local instance with a fictional home, in English or in French.

For screenshots, demonstrations and manual tests: `manage.py load_demo_data --owner
<e-mail of an existing account> --language fr`. Every name is generic and invented;
dates are relative to today, so the Today screen always has something overdue, due
and coming. The names are data, not interface text: they are written here in both
languages instead of going through the translation catalogs.
"""

import datetime
from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from housecairn.accounts.models import User
from housecairn.homes import services as homes
from housecairn.homes.models import Home
from housecairn.projects import services as projects
from housecairn.rooms import services as rooms
from housecairn.tasks import services as tasks

# Room keys, with their kind and their name in each language.
ROOMS: dict[str, tuple[str, dict[str, str]]] = {
    "living": ("living", {"en": "Living room", "fr": "Salon"}),
    "kitchen": ("kitchen", {"en": "Kitchen", "fr": "Cuisine"}),
    "bathroom": ("bathroom", {"en": "Bathroom", "fr": "Salle de bain"}),
    "hallway": ("hallway", {"en": "Hallway", "fr": "Entrée"}),
    "utility": ("utility", {"en": "Utility room", "fr": "Buanderie"}),
    "garden": ("outdoor", {"en": "Garden", "fr": "Jardin"}),
}

# Title in each language, room key, days from today, other fields.
TASKS: list[tuple[dict[str, str], str, int, dict[str, Any]]] = [
    (
        {"en": "Test the smoke detector", "fr": "Tester le détecteur de fumée"},
        "hallway",
        -3,
        {
            "repeat_mode": "fixed",
            "repeat_unit": "month",
            "repeat_interval": 6,
            "priority": "high",
            "estimated_minutes": 5,
        },
    ),
    (
        {"en": "Clean the ventilation filter", "fr": "Nettoyer le filtre de la VMC"},
        "bathroom",
        0,
        {
            "repeat_mode": "after_last",
            "repeat_unit": "month",
            "repeat_interval": 3,
            "estimated_minutes": 15,
        },
    ),
    (
        {"en": "Descale the kettle", "fr": "Détartrer la bouilloire"},
        "kitchen",
        0,
        {
            "repeat_mode": "after_last",
            "repeat_unit": "month",
            "repeat_interval": 2,
            "estimated_minutes": 10,
        },
    ),
    (
        {"en": "Boiler yearly service", "fr": "Entretien annuel de la chaudière"},
        "utility",
        6,
        {"repeat_mode": "fixed", "repeat_unit": "year", "repeat_interval": 1, "priority": "high"},
    ),
    (
        {"en": "Clear the gutters", "fr": "Nettoyer les gouttières"},
        "garden",
        12,
        {
            "repeat_mode": "fixed",
            "repeat_unit": "year",
            "repeat_interval": 1,
            "estimated_minutes": 60,
        },
    ),
    (
        {"en": "Bleed the radiators", "fr": "Purger les radiateurs"},
        "living",
        20,
        {
            "repeat_mode": "fixed",
            "repeat_unit": "year",
            "repeat_interval": 1,
            "estimated_minutes": 30,
        },
    ),
]

HOME_NAME = {"en": "Example house", "fr": "Maison d'exemple"}
PAINT_TITLE = {"en": "Repaint the living room", "fr": "Repeindre le salon"}
PAINT_GOAL = {"en": "Walls and ceiling, before winter.", "fr": "Murs et plafond, avant l'hiver."}
# Label in each language, nature, planned amount.
PAINT_LINES: list[tuple[dict[str, str], str, str]] = [
    ({"en": "Paint and primer", "fr": "Peinture et sous-couche"}, "material", "240"),
    ({"en": "Painter (ceiling)", "fr": "Peintre (plafond)"}, "labour", "650"),
]
BATHROOM = {"en": "Redo the bathroom", "fr": "Refaire la salle de bain"}
LANGUAGES = ("en", "fr")


def load(owner: User, language: str, today: datetime.date) -> Home:
    """Create the demo home of `owner` in `language`, with rooms, tasks and projects."""
    with transaction.atomic():
        home = homes.create_home(owner, name=HOME_NAME[language])
        made = {
            key: rooms.create_room(owner, home, name=names[language], kind=kind)
            for key, (kind, names) in ROOMS.items()
        }
        for titles, room, days, fields in TASKS:
            tasks.create_task(
                owner,
                home,
                due_on=today + datetime.timedelta(days=days),
                title=titles[language],
                room=made[room],
                **fields,
            )
        paint = projects.create_project(
            owner,
            home,
            rooms=[made["living"]],
            title=PAINT_TITLE[language],
            goal=PAINT_GOAL[language],
            status="planned",
            priority="normal",
            estimated_minutes=960,
        )
        for labels, nature, planned in PAINT_LINES:
            projects.create_line(
                owner,
                paint,
                label=labels[language],
                nature=nature,
                planned=Decimal(planned),
                paid=Decimal("0"),
            )
        projects.create_project(
            owner,
            home,
            rooms=[made["bathroom"]],
            title=BATHROOM[language],
            status="idea",
            priority="low",
        )
    return home


class Command(BaseCommand):
    help = "Add a fictional demo home to an existing account, in English or in French."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--owner", required=True, help="E-mail of an existing account.")
        parser.add_argument("--language", choices=LANGUAGES, default="en")

    def handle(self, *args: Any, **options: Any) -> None:
        owner = User.objects.filter(email__iexact=options["owner"]).first()
        if owner is None:
            raise CommandError("No account with this e-mail: create it first.")
        language: str = options["language"]
        if Home.objects.filter(memberships__user=owner, name=HOME_NAME[language]).exists():
            raise CommandError(f"This account already has the home {HOME_NAME[language]!r}.")
        home = load(owner, language, datetime.date.today())
        self.stdout.write(f"{home.name} ({home.pk})")
