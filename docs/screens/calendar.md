# Calendar

The tasks of your homes by week, month or year, at `/calendar/` (**Tasks**, then **Calendar**).
It shows what is planned, done, postponed and skipped, with the status written in words, and
what is still to come for a task that repeats.

- **Week, Month, Year**: the three views switch from the bar under the title. The week lists
  each day with its tasks; the month adds a grid in which every day links to its week and says
  how many tasks it holds; the year counts the tasks of each month by status and links to it.
- **Filters**: home (when you belong to several, the default is all of them together), room,
  person, priority. A person is shown by their name, never by their email address.
- **Previous, Next, Today** move by one period. With the focus inside the calendar, the left and
  right arrows do the same and `T` goes to today; the shortcuts work nowhere else on the page.
- **Done** marks a task done in one tap, with **Undo** on the page you come back to, exactly as
  on [Today](today.md). A reader of a home sees its tasks but has no **Done** button.
- **Forecast**: the dates after the open occurrence of a task that repeats are computed from its
  rule and marked as forecast. They are not created until the task is done; they have no button.

The range is limited to 400 days and 5 000 entries; past that the screen says so. What is left out
is always the farthest dates; narrowing the filters or the range shows the rest. The same data is in the [API](../api/index.md)
(`GET /api/v1/calendar/?from=&to=`).

## Feeds

**Feeds** (`/calendar/feeds/`) gives the address of a calendar that Google Calendar, Apple
Calendar, Thunderbird or Home Assistant can subscribe to; see the
[guide](../guides/calendar.md). You can have one feed per home and one for all your homes.

- **Create** shows the address once: copy it then. Only a digest is kept, so nobody, you
  included, can read it again.
- **New address** replaces the secret; the old address stops working at once.
- **Revoke** deletes the feed. Leaving a home revokes your feed of that home.

A feed shows the title, home, room, date, status and a link to each task, and nothing more. It
is a secret address: anyone who has it reads the feed, so share it with nobody.
