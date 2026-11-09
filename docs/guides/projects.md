# Projects and quotes

A project is a piece of work with an end: redo the bathroom, paint the living room. It
holds the steps as tasks, the quotes you collect and a budget you can follow. Only the
title is required, so you can start with an idea and fill in the rest as it firms up.

## Start a project

Open **Tasks** in the navigation, then the **Projects** tab, then **Add a project**. Say
what it is, its status (idea, planned, in progress, finished, abandoned) and, if you
already know it, the **budget**: for "redo the bathroom, 5000 euros", type 5000. The
amount is in the currency of the home and becomes the first budget line.

The rooms concerned, the estimated duration and the preferred season are optional and help
to compare projects later. The season follows the hemisphere of the home.

## List the steps as tasks

On the page of the project, **Add a task to the project** makes a task with a title, an
optional date and an optional room. It is a normal task: it shows in the task list and on
Today, you tick it done like any other, and its page names the project. A task you already
have can be put into a project with **Put an existing task in the project**; a task is in
one project at most, and taking it out keeps it.

## Collect quotes and commit one

**Add a quote** with the contractor (pick one or type a new name), the amount, the date and
how long it is valid, and attach the PDF or the photo of the quote. A quote starts as
*requested*, becomes *received* when it arrives, and *accepted* or *rejected* when you
decide.

**Accept the quote** next to the budget line it pays for. Its amount is then *committed* on
that line. Rejecting it, or deleting the line, releases the commitment. Nothing stops you
from accepting several quotes on one line, or none: the commitment is the sum of the
accepted ones.

## Follow the budget

Each budget line has three amounts, in the currency of the home:

| Amount | Where it comes from |
| --- | --- |
| Planned | What you plan to spend; you type it. |
| Committed | The sum of the quotes accepted on the line. |
| Paid | What has been paid so far; you type it. |

The gap is the planned amount less the more of committed and paid. The page says it in
words, never by colour alone: **... left**, **On budget** or **Over budget by ...**. For
the living room painted with a plan of 800, a quote of 620 accepted and 120 paid, the gap
is 180 and the page says "180.00 EUR left". Amounts have two decimals and go up to
9,999,999,999.99.

## Compare and plan the year

Tick projects in the list and **Compare the ticked projects** to see their cost, duration,
priority and season side by side. **Set the envelope** on the list gives the amount you
want to spend on work this year; the list sets it against the planned budget of the
projects that are not finished nor abandoned.

## Share

Everyone in the home sees the same projects; members and owners change them, read-only
members change nothing. The same data is available to scripts through the
[API](../api/index.md) (`projects`, `budget-lines`, `quotes`, `project-files`,
`project-tasks` and `envelope`), with the `read` and `write` scopes of an API token. The
projects are part of the [export of the home](../administration/data.md), photos and files
of quotes included, and are erased with it.
