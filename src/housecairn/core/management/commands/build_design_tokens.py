from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from housecairn.core import design


class Command(BaseCommand):
    help = "Generate static/css/tokens.css from design/tokens.json."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--check",
            action="store_true",
            help="Exit with an error if the generated CSS is out of date; write nothing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        css = design.expected_css()
        current = design.CSS_PATH.read_text(encoding="utf-8") if design.CSS_PATH.exists() else ""
        if options["check"]:
            if current != css:
                raise CommandError(
                    "tokens.css is out of date: run `manage.py build_design_tokens`."
                )
            self.stdout.write("tokens.css is up to date.")
            return
        design.CSS_PATH.parent.mkdir(parents=True, exist_ok=True)
        design.CSS_PATH.write_text(css, encoding="utf-8")
        self.stdout.write(f"Wrote {design.CSS_PATH.name}.")
