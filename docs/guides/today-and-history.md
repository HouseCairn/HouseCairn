# Today and history

Three screens to look at your tasks without setting anything up, and one setting to
make them yours.

## Start the day on Today

The application opens on [Today](../screens/today.md), whichever way you come in: the
logo, **Today** in the navigation, the installed application and signing in lead to
it. With several homes, [one page](../screens/my-home.md) shows what is assigned to
you, what is late in each home, what nobody has taken yet and the warranties that end
soon; pick a home there to open its Today.

## Do the day on Today

The
arrears are on top; then what comes up in the next days; then what is in season.
**Done** is on every row: one tap, and a banner offers **Undo** if it was a mistake.

By default the screen is ordered by urgency over one week. If you think by room (the
bathroom first), by person (what is mine, what is hers) or by day, change it in the
[display preferences](../screens/display-preferences.md): **Group by**, how far to
look ahead, and which sections to show. Your choice is yours alone, in every home.

## Remember what was done

The [history](../screens/history.md), **Done** in the **All** tab, lists what was done or skipped, the most recent
first. Search a word of the title or of the note, or narrow by room, item, contractor
or person, by outcome and by dates: this is how you find who changed the filter, or
when the plumber came last. The total is that of the real costs you entered when
closing the tasks; an entry without a cost is not counted.

## For scripts

The [API](../api/index.md) has the same three views: `GET /api/v1/me/home/`,
`GET /api/v1/homes/<home id>/today/` and the occurrences with `ordering=recent`.
`GET`/`PATCH /api/v1/me/display-preferences/` reads and changes the layout.
