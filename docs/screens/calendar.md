# Calendar

The tasks of your homes by week, month or year, at `/calendar/` (the **Calendar** tab of **Today**).
It shows what is planned, done, postponed and skipped, with the status written in words, and
what is still to come for a task that repeats.

- **Home**: the calendar shows the [current home](my-home.md#the-current-home), or all
  your homes together when you chose **All homes** in the selector of the app bar.
- **Today, All, Calendar**: the tabs of the Today section, which lead back to the Today
  and the task list of the home shown. With all homes: **Today** (the page of all
  homes) and **Calendar**.
- **Week, Month, Year**: the three views switch from the segmented control under the
  tabs. The week lists
  each day with its tasks; the month adds a grid in which every day links to its week and says
  how many tasks it holds; the year counts the tasks of each month by status and links to it.
- **Filters**: room, person, priority. A person is shown by their name, never by their email address.
- **Previous, Next, Today** move by one period. With the focus inside the calendar, the left and
  right arrows do the same and `T` goes to today; the shortcuts work nowhere else on the page.
- **Done** marks a task done in one tap; the calendar comes back to the same task, with the
  **Undo** banner at the bottom, as on [Today](today.md). A reader of a home sees its tasks but has no **Done** button.
- **Forecast**: the dates after the open occurrence of a task that repeats are computed from its
  rule and marked as forecast. They are not created until the task is done; they have no button.

The range is limited to 400 days and 5 000 entries; past that the screen says so. What is left out
is always the farthest dates; narrowing the filters or the range shows the rest. The same data is in the [API](../api/index.md)
(`GET /api/v1/calendar/?from=&to=`).

## Feeds

**Calendar in another application**, in the **Me** group of [More](more.md)
(`/calendar/feeds/`), gives the address of a calendar that Google Calendar, Apple
Calendar, Thunderbird or Home Assistant can subscribe to; see the
[guide](../guides/calendar.md). You can have one feed per home and one for all your homes.

- **Create** shows the address once: copy it then. Only a digest is kept, so nobody, you
  included, can read it again.
- **New address** replaces the secret; the old address stops working at once.
- **Revoke** deletes the feed. Leaving a home revokes your feed of that home.

A feed shows the title, home, room, date, status and a link to each task, and nothing more. It
is a secret address: anyone who has it reads the feed, so share it with nobody.

The link at the top of the feeds leads back to [More](more.md), on a phone.
