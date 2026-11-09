# Budget of the upkeep

`/h/<home id>/budget/tasks/`, with `?year=` for the year and `?export=csv` for a file.

The tasks that are in no project and have an estimate (labour plus materials, each time) or
a cost. **Cost a year** is the estimate times how often the task comes back: a task every 3
years costs a third of its estimate a year, every 6 months twice. A task that does not
repeat on the calendar has none. For the year picked, **Planned** counts the occurrences done
in it and the one coming; **Paid** is the cost typed on those done. A task done with no cost
typed is counted in the plan with nothing paid, and flagged **done without a cost**, so the
gap does not look better than it is. **Paid in all** is every cost, any year. Tasks without
an estimate or a cost are not listed; the page counts them. A row opens the task, whose page
has a **Cost** block, and the page of what was done (**Details**) shows the estimate next to
the field for the real cost.
