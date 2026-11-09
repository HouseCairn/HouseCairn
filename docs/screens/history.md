# History

What was done or skipped in a home: the **Done** filter of the
[task list](tasks.md) (**All**, then **Done**), at `/h/<home id>/tasks/?status=done`,
the most recent first. The former address, `/h/<home id>/history/`, leads there with
its filters. Each row shows the task, where it is, the contractor and who closed it, the
outcome with its date, and the real cost when one was entered. A row opens the
[task](task.md).

People are named by their [display name](profile.md), never by their address.

The form at the top narrows the list. It is folded under **Filters** (open when a
filter is active), so the list stays in reach on a phone. All fields are optional:

- **Search** looks in the task title and in the note written when it was closed.
- **Room**, **Item**, **Contractor** and **Done by**.
- **Outcome**: done or skipped (`?outcome=`).
- **From** and **To**: the dates it was closed. A skipped occurrence has no
  completion date, so the day it was skipped is used.

Above the list, a line gives the number of entries and the **real cost** entered on
them. An entry with no cost counts for nothing, not for zero: the sum is that of the
costs that were entered. The list shows 30 rows at a time, and the filters stay when
you change page.

Exporting the history (CSV, PDF file) comes with a later version.
