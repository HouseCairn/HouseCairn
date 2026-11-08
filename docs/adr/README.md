# Architecture decision records

Each significant architecture decision is recorded here, in a short format:
context, decision, consequences. A record is never rewritten once accepted: a
later record supersedes it.

| No. | Decision | Date |
| --- | --- | --- |
| [0001](0001-record-architecture-decisions-and-dependencies.md) | Record decisions; runtime dependencies | 2026-11-07 |
| [0002](0002-single-service-layer.md) | A single service layer for web and API | 2026-11-07 |
| [0003](0003-web-api-parity.md) | Web/API parity, checked by a test | 2026-11-07 |
| [0004](0004-versioned-rest-api.md) | Versioned REST API, OpenAPI 3.1, cursor pagination | 2026-11-07 |
| [0005](0005-stable-identifiers-and-soft-deletion.md) | UUID identifiers, timestamps, soft deletion | 2026-11-07 |
| [0006](0006-home-scoping.md) | Every query scoped to the user's homes | 2026-11-07 |
| [0007](0007-authentication-and-api-tokens.md) | django-allauth, scoped API tokens, OAuth 2 later | 2026-11-07 |
| [0008](0008-background-tasks.md) | Background tasks with django-q2 and the ORM broker | 2026-11-07 |
| [0009](0009-design-tokens.md) | Design tokens in one JSON file | 2026-11-07 |
| [0010](0010-stable-urls.md) | Stable addresses for every record | 2026-11-07 |
| [0011](0011-no-external-resources-and-csp.md) | No external resources, strict CSP | 2026-11-07 |
| [0012](0012-configuration-and-security-defaults.md) | Configuration by environment, safe defaults | 2026-11-07 |
| [0013](0013-internationalization.md) | English source, French shipped, no hard-coded strings | 2026-11-07 |
| [0014](0014-continuous-integration-and-supply-chain.md) | Continuous integration and supply-chain security | 2026-11-07 |
| [0015](0015-container-image-and-publication.md) | Container image, signed publication to GHCR | 2026-11-07 |
| [0016](0016-documentation-site.md) | Documentation site: Sphinx, two languages, screenshots, checks | 2026-11-07 |
| [0017](0017-visual-system-and-brand.md) | Visual system, brand and application shell | 2026-11-07 |
| [0018](0018-sign-in-page-and-passkeys.md) | Sign-in page: passkeys without a button, one button per provider | 2026-11-07 |
| [0019](0019-property-based-tests.md) | Property-based tests with Hypothesis | 2026-11-07 |
| [0020](0020-household-roles-and-invitations.md) | Household roles and invitations | 2026-11-07 |
| [0021](0021-per-home-single-sign-on.md) | Single sign-on required per home | 2026-11-07 |
| [0022](0022-instance-administrator-without-content.md) | Instance administrator without access to content | 2026-11-08 |
| [0023](0023-audit-log-export-erasure-and-email-alerts.md) | Audit log, export, erasure and security emails | 2026-11-08 |
| [0024](0024-open-sign-up-and-anti-robot-check.md) | Open sign-up and its anti-robot check | 2026-11-08 |
| [0025](0025-rate-limit-counters-and-workers.md) | Rate-limit counters and several web processes | 2026-11-08 |
| [0029](0029-rooms-items-and-room-memory.md) | Rooms, items and room memory | 2026-11-08 |
| [0030](0030-photo-storage-and-processing.md) | Photo storage and processing | 2026-11-08 |
| [0031](0031-tasks-occurrences-and-recurrence.md) | Tasks, occurrences and recurrence | 2026-11-08 |
| [0032](0032-dates-and-time-zone-of-tasks.md) | Dates and time zone of tasks | 2026-11-08 |
| [0033](0033-done-with-undo.md) | "Done" in one gesture, with undo | 2026-11-08 |
| [0034](0034-task-attachments.md) | Photos and files attached to tasks | 2026-11-08 |
| [0035](0035-instance-settings-in-the-interface.md) | Instance settings in the interface, paired with environment variables | 2026-11-08 |
| [0036](0036-export-rooms-photos-and-file-erasure.md) | Export of rooms and photos, erasure of files with the home | 2026-11-08 |
| [0037](0037-today-my-home-history-and-display-preferences.md) | Today, My home, History and display preferences | 2026-11-08 |
| [0038](0038-stock-suppliers-and-movements.md) | Stock: items, suppliers and an append-only ledger of movements | 2026-11-08 |
| [0040](0040-merge-queue.md) | Merge queue, required checks on each queue entry | 2026-11-08 |
| [0041](0041-sign-in-providers-in-the-interface.md) | Sign-in providers in the interface, last way to sign in | 2026-11-08 |
| [0042](0042-rate-limits-quotas-language-and-instance-name.md) | Rate limits, quotas per home, language, time zone and name of the instance | 2026-11-08 |
| [0043](0043-notifications-through-apprise.md) | Notifications through Apprise: channels of a person, reminders, quiet hours | 2026-11-08 |
