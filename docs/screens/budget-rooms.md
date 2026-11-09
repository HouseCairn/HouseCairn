# Budget by room

`/h/<home id>/budget/rooms/`, with `?year=` for the year and `?export=csv` for a file.

One row per room that has a figure, and **No room** for what belongs to none. A room adds up
the projects counted in the year that name it and the upkeep of its tasks in that year. A
project in several rooms is shared evenly between them, in whole cents, the odd cents going
to the first rooms, so the rooms always add up to the project. A row shows **Planned**,
**Committed**, **Paid**, the gauge of **Used** against planned and, in words, where it
stands. The total is at the foot of the table. Read-only members see the same page.

A room of the table opens the budget of that room, in Budget.

## Budget of one room

`/h/<home id>/budget/rooms/<room id>/`, with `?year=` for the year and `?export=csv` for the
row of the room as a file.

The same figures as the row of the room, line by line: each project counted in the year
that names the room, with the share of the room, and each task of the room with a cost in
the year. A project or a task opens its page, whose link at the top comes back here.

**Open the room** opens the [page of the room](room.md); Budget stays marked in the bar,
and the link at the top of the room says **Budget** and comes back here. The link at the
top of this page leads back to where it was opened from (the room, or the table), and to
the budget by room otherwise.
