# Export and deletion

The data of a home belongs to its owners, who can take it out and delete it;
the data of a person is erased with their account
([ADR 0023](../adr/0023-audit-log-export-erasure-and-email-alerts.md)). The
administrator of the instance does neither for a home they do not own.

## Export of a home

An owner downloads the archive from the page of the home (**Export all
data**) or from the API (`POST /api/v1/homes/<id>/export/`, signed in; an API
token cannot). The export is written to the audit log of the home.

The archive is a zip:

| Part | Content |
| --- | --- |
| `export.json` | The data, as JSON (below). |
| `files/` | The files of the home, at the paths `export.json` lists. None yet. |
| `README.txt` | A reminder of the format. |

`export.json` is versioned. Version `1` has these keys:

| Key | Content |
| --- | --- |
| `format`, `version` | `"housecairn-export"` and `1`. A change that removes or renames a key raises the version. |
| `exported_at`, `application_version` | When, and by which version. |
| `home` | `id`, `name`, `currency`, `required_provider`, `created_at`. |
| `members` | `id`, `email`, `name`, `role`, `joined_at` of each member. |
| `pending_invitations` | `id`, `email`, `role`, `sent_at`, `expires_at`; never a link. |
| `events` | `id`, `kind`, `payload`, `received_at` of the events received. |
| `files` | `path` and `size` of each file in `files/`. |

Each lot that adds data adds its section here and to the archive. The archive
holds the home it was made for and nothing of another.

## Deletion of a home

An owner deletes the home from its page (**Delete this home**): type its exact
name. The home and everything in it go for good, for all its members: members,
invitations, events, its audit log and its files; an API token left without a
home is revoked. **There is no grace period and no way back**: export first.
The audit log of the instance records that a home was deleted, without its
name.

## Erasure of an account

**Delete my account** (see [Account pages](../screens/account.md)) erases the
account, its sign-in methods, devices and API tokens, the homes where it is
the only member, and the invitations to its address. It is refused for the only
administrator and for the only owner of a home with other members: hand
ownership over, or delete the home, first. The audit log keeps that it happened
and no longer says who.

## Backups

Deleted data stays in backups until they expire: tell people how long you keep
them (see [Backup](backup.md)).
