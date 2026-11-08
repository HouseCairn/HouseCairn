# Photos and files of a task

The photos and files of a task, shown on its [page](task.md). **Add photos or
files** opens `/h/<home id>/tasks/<task id>/attachments/new/`, where several
files can be chosen at once; from a phone, the chooser offers the camera. Files can
also be joined when the task is added.

| Kind | Accepted |
| --- | --- |
| Images | JPEG, PNG and WebP, treated like the [photos of a room](photo-form.md): the location and the other information stored in the file are removed, a large image is reduced, a thumbnail is made. |
| Documents | PDF, plain text (UTF-8), Word (`.docx`), Excel (`.xlsx`) and OpenDocument text and spreadsheet (`.odt`, `.ods`). |

HouseCairn checks the content of each file, not its name or the type your browser
announces: anything else is refused with the file named. Documents are stored as
they are and only ever sent back as a download, so a document cannot run in your
browser. The default limit is 10 MB per file, the one of
`HOUSECAIRN_PHOTO_MAX_BYTES` (see [Rooms and items](../guides/rooms-and-items.md)),
and a task holds 30 files at most. The name you see is the name of the file, cleaned
of any folder and special character.

A file opens at `/h/<home id>/task-files/<file id>/` for the members of the home
only. **Delete** next to a file removes it from the screens and the API and erases the
file from the disk; deleting the task does the same for all its files. The files are
part of the [export of the home](../administration/data.md) and go with the home
when it is deleted. A voice note cannot be recorded yet.
