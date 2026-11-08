# Tasks and recurrence

A task is something to do in the home: check the smoke detector, repaint the
living room. Only the title is required; you can add the room, the item, a date, a
budget and a procedure when you have them. This guide shows how a task comes
back and how to close it.

## Add a task

**Tasks** in the navigation, then **Add a task**. From the page of a room or of an
item, **Add a task** already knows where the task belongs. Everything else is in the
sections of the [form](../screens/task-form.md), opened only when needed. Photos and
files (a photo of the label, the manual in PDF) can be added right away.

## Done, in one tap

**Done** is on every row of the list and on the page of every task, one-time or
repeating. The occurrence is closed today and, if the task repeats, the next one
appears at once. A banner offers **Undo**: it brings the task back exactly as it was
and removes the occurrence that was created. Once you have worked on that next
occurrence (postponed it, written a note, added a photo, done it), **Undo** is no
longer possible for the previous one.

The real date, the cost and a note can be filled in afterwards, from **Details** in
the history of the task. **Skip this time** closes an occurrence without doing it,
for a season where the chore does not apply, and also creates the next one.
**Postpone** moves the date; the occurrence stays on the list as *postponed*.

## How a task repeats

| Mode | The next date is |
| --- | --- |
| Once | None: the task is finished when done. |
| Fixed date | The next date of the series that starts at the first date, for example the 15th of every month. |
| After the last time | The day it was done plus the interval: a filter changed on 3 March, every 6 months, is due again on 3 September. |

The months do what you would expect: a task set on the 31st falls on the last day of
the shorter months, and a task set on 29 February falls on 28 February in the years
that are not leap years. With **Fixed date**, a task done very late does not bring
back every date it missed: the next occurrence is the first date of the series after
today, and the one not done yet stays on top of the list as arrears.

A **season** limits the task to some months (April to October for the lawn,
November to March for the heating, over the new year if needed). A date that falls
outside the season moves to the first day of the next one.

With **Fixed date**, the first day of a season is one more date of the series, not a
new start: a monthly task set on 31 March with a season from March to May is due on
30 April and 31 May, then on 1 March of the next year (30 June is out of the season),
then on 31 March, 30 April and 31 May again.

Dates stay within 100 years of today: a task cannot be dated 1850 or 2300.

**Hide until** keeps a task off the list until a number of days before its date,
for what you do not want to see a year ahead; the list tells how many tasks are
hidden. Repeating on usage (litres, hours) or from a sensor does not exist yet.

Dates are days, with no time of day, so a change to summer or winter time never moves
a task. "Today" is the day in the time zone of the instance
(`TIME_ZONE`, see [Variables](../administration/variables.md)).

## Procedure and budget

The **How to do it** text is written in Markdown (titles, lists, bold, links to web
pages) and shown on the page of the task, safely: HTML is not interpreted and
images are not loaded. The budgets (labour, materials) are the planned amounts; the
real cost is entered when the task is done. The materials with their quantities
come with the stock, in a later version.

## Contractors

Name the person or the company on the task: pick one that the home already knows or
type a new name and trade in the form. The API also lists and edits them.

## For scripts

Everything above is available through the [API](../api/index.md): tasks,
occurrences (with `complete`, `undo`, `skip` and `postpone`), contractors and
attachments.
