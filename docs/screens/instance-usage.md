# Files of the homes

The space and the number of files each home takes, at `/instance/usage/`, reached from
**Instance administration**. Administrators only; anyone else gets a 404.

Each home is shown by its identifier, with the space its files take, their number and the
share of the quota closer to its limit; the fullest come first. Photos, attachments, labels
and their thumbnails count, and so do deleted files until they are purged. You see no name,
no member and no file: the identifier only tells homes apart (see
[Instance administrator](../administration/instance.md)).

The quotas are settings of the instance, in the **Files of a home** section of
[Instance settings](instance-settings.md). The API gives the same numbers at
`GET /api/v1/instance/usage/`.
