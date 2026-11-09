# Budget

The budget answers "how much, where, and are we within it" for the year, from what you
already enter: the budget lines and quotes of [projects](projects.md), and the estimate and
real cost of [tasks](tasks-and-recurrence.md). Nothing new is typed for it, and nothing is
stored: the figures are worked out each time you open a page. Open **Tasks**, then
**Budget**. Typing an amount is explained in [Entering an amount](amounts.md).

## What you enter

- On a **task**, a labour budget and a material budget: what it costs each time. They are in
  the form of the task, under **Time and budget**.
- When the task is **done**, its real cost, in **Details** of what was done. The page of the
  task shows its **Cost**: the estimate, what it comes to in a year and what was paid so far.
- On a **project**, budget lines with a planned and a paid amount, and quotes accepted on
  them.

The money of a task that is in a project is the project's: its lines hold it, and the task
is left out of the upkeep so that nothing is counted twice.

## Planned, committed, paid, used, gap

*Planned* is what you plan to spend. *Committed* is what accepted quotes promise. *Paid* is
what was spent. *Used* is the more of committed and paid, line by line, and the *gap* is
planned less used: **... left**, **On budget** or **Over budget by ...**. Rows also show a
gauge with its percentage; colour is never the only signal.

## Example: painting the living room

A project "Paint the living room" has two lines, paint 300 and labour 500, so 800 planned.
You ask two painters; you accept the one at 620 on the labour line, and you pay 350 for the
paint. Used is 350 + 620 = 970 and the gap is 800 - 970 = -170: **Over budget by 170.00
EUR**, on the budget of the room, on the project and in the totals of the year. A task of
upkeep in the same room, "Wash the walls", estimated at 50 and done for 80, adds a gap of
-30 to the room and shows in the upkeep, so the room reads 850 planned and 1050 used, -200.

## By room, by project, by task

- **By room**: projects (shared evenly between the rooms they name, in whole cents) and the
  upkeep of the room's tasks.
- **By project**: each project once, in **the year it starts**, whole, even if the work runs
  into the next year. A year is chosen by the earliest date of its tasks and accepted quotes;
  with none, the year it was created. An abandoned project plans nothing any more; what was
  paid on it shows as spent without a plan.
- **By task**: the tasks that are in no project. The **cost a year** follows the repetition:
  a task every 3 years costs a third of its estimate a year, every 6 months twice, a weekly
  task 52 times, rounded once to the cent. A task that does not repeat has none, and a task
  that repeats by use, when there is one, will not be annualised either.

For a year, **Planned** counts what the task did that year (each time done, at its estimate),
the occurrence that is open, and the times its repetition will still bring before 31
December. A task every month at 25, read in February after a first time in January, plans 12
times 25 for the year, not only the two rows that exist. A year that is over counts only what
happened; a year to come counts the whole repetition, and a task that counts from the last
time is followed from its open date, as the calendar does. Nothing is written: these times
are worked out when you read the page.

A task done with no cost typed counts at its estimate in the plan and as nothing paid, and is
flagged, so that the gap does not look better than it is.

## The envelope, years and the last 12 months

The overview sets the envelope of a year against the projects counted in it and the upkeep of
the year, and splits the year by nature (materials, labour, rental, other; the real cost of a
task has no nature and counts under Other). **By year** lists every year with a figure.
**Last 12 months** is the upkeep done since the same day last year; payments on projects have
no date and are not in it. The envelope is set from **Projects**.

## Several homes and currencies

**Budget** in the navigation adds your homes up by currency; amounts in different currencies
are never converted. With one home it opens that home.

## Files and scripts

Every page has **Download as CSV**: UTF-8, a comma, amounts with a dot. A text that would
start a formula in a spreadsheet (`=`, `+`, `-`, `@`) is written with a leading quote so that
it stays text. The same figures are in the [API](../api/index.md). Read-only members read
everything; nothing here changes data.
