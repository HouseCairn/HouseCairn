"""Projects in the export of their home (docs/adr/0050, 0048).

Amounts are text with a point, never a float. The photos, the pictures of links and the
files of quotes go into `files/projects/`, as stored. What is committed on a budget line
is not a field: it is the sum of its accepted quotes.
"""

from housecairn.homes import exports
from housecairn.projects.models import (
    AnnualEnvelope,
    BudgetLine,
    Project,
    ProjectFile,
    ProjectLink,
    ProjectTask,
    Quote,
)


def register() -> None:
    exports.register(
        "projects",
        exports.Section("projects", Project),
        exports.Section("project_budget_lines", BudgetLine),
        exports.Section("project_quotes", Quote),
        exports.Section(
            "project_files",
            ProjectFile,
            files=(exports.FileSpec("file", "projects", thumbnail="thumbnail", documents=True),),
        ),
        exports.Section("project_links", ProjectLink),
        exports.Section("project_tasks", ProjectTask),
        exports.Section("project_envelopes", AnnualEnvelope, order_by=("year", "id")),
    )
