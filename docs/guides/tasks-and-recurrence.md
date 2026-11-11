# Tasks and recurrence

A task is something to do in the home: check the smoke detector, repaint the
living room. Only the title is required; you can add the room, the item, a date, a
budget and a procedure when you have them. This guide shows how a task comes
back and how to close it.

## Add a task

**Today** in the navigation, then **Add a task**. From the page of a room or of an
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
| Once (**Repeat this task** unticked) | None: the task is finished when done. |
| Fixed date (**Count from** the due date) | The next date of the series that starts at the first date, for example the 15th of every month. |
| After the last time (**Count from** the day it is done) | The day it was done plus the interval: a filter changed on 3 March, every 6 months, is due again on 3 September. |

The months do what you would expect: a task set on the 31st falls on the last day of
the shorter months, and a task set on 29 February falls on 28 February in the years
that are not leap years. With **Fixed date**, a task done very late does not bring
back every date it missed: the next occurrence is the first date of the series after
today, and the one not done yet stays on top of the list as arrears.

A **season** limits the task to some months. Pick a predefined one (spring, summer,
autumn or winter), which follows the hemisphere of the home, or **Custom months** (April
to October for the lawn, October to April for the heating, over the new year if needed).
A date that falls outside the season moves to the first day of the next one. The
hemisphere is set on the page of the [home](../screens/home.md): never guessed.

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
real cost is entered when the task is done; the page of the task shows its cost, and the
[budget](budget.md) adds it all up.

## Materials and the stock

In **Materials**, on the form and on the page of the task, list the stock items the task
needs and how many: three filters, two litres of paint. Only items of the
[stock](stock.md) of the same home can be chosen; each is listed once. To remove a line
from the form, set its stock item back to the dash; on the page, use **Remove**.

**Done** takes the planned quantities from the stock, in the same gesture, and the page of
each stock item names the task on the movement. **Undo** puts them back with new entries:
nothing is erased from the history of the stock. Skipping a task takes nothing.

If the stock holds less than needed, **Done** still goes through: the stock goes down to
zero, never below, and a message tells what was missing. The quantity you really used is
entered afterwards, in the **Details** of what was done (one field per stock item taken):
less puts the difference back, more takes it as far as the stock allows.

## Contractors

Name the person or the company on the task, in one field: pick one that the home already
knows from the suggestions, or type a new name, which creates the contractor when you save.
Each contractor has a [sheet](../screens/contractor.md) (trade from a list, phone, email
address, address, note, the tasks that name them) that downloads as a contact file (.vcf)
to put in your phone. The API also lists and edits them.

## Estimated duration and who does it

The estimated duration is a number and a unit (minutes, hours or days). The person in
charge is shown by their [display name](../screens/profile.md), never by their address.

## For scripts

Everything above is available through the [API](../api/index.md): tasks,
occurrences (with `complete`, `undo`, `skip` and `postpone`), contractors,
attachments and the materials of the tasks (`task-materials`). The answer to `complete`
lists in `short` the stock items the stock could not give in full, and a `PATCH` of an
occurrence takes `used`, the quantities really used.
