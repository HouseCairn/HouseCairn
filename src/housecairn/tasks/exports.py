"""Tasks, their history, materials and files in the export of their home (docs/adr/0048).

The files of the attachments go into `files/attachments/`, as stored: images already
stripped of their metadata at upload (docs/adr/0030), documents untouched. Thumbnails are
not exported; a restore makes them again from the image.
"""

from housecairn.homes import exports
from housecairn.tasks.models import (
    Attachment,
    Contractor,
    MaterialDraw,
    Occurrence,
    Task,
    TaskMaterial,
)


def register() -> None:
    exports.register(
        "tasks",
        exports.Section("contractors", Contractor),
        exports.Section("tasks", Task),
        exports.Section("task_materials", TaskMaterial),
        exports.Section("occurrences", Occurrence),
        exports.Section("stock_draws", MaterialDraw),
        exports.Section(
            "attachments",
            Attachment,
            files=(exports.FileSpec("file", "attachments", thumbnail="thumbnail", documents=True),),
        ),
    )
